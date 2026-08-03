"""
server.py — FastAPI web server: HTTP endpoints + WebSocket broadcast.

FastAPI is chosen here for a few reasons worth understanding:
  1. It is async-native, so the NFC polling loop and the web server share
     the same event loop without threads.
  2. It auto-generates interactive API docs at /docs — useful when you
     want to test endpoints manually.
  3. WebSocket support is first-class and requires very little boilerplate.

Key async concepts:
  - `async def` / `await` — marks a function that can pause while waiting
    for I/O (disk, network, NFC poll) without blocking other work.
  - `asyncio.create_task()` — schedules a coroutine to run concurrently
    in the background.  This is how the NFC loop runs alongside HTTP requests.
  - The WebSocket manager keeps track of every connected browser.  When a
    card is scanned, it fans the event out to all of them.

Run:
    cd card-scanner
    python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Allow `from config import …` when running from the src/ directory.
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from card_db import CardDatabase, Card
from card_sheets import load_cards_from_sheets
from nfc_reader import create_reader, NFCReader, TagScan
from led_feedback import blink_success, blink_unknown
from config import BASE_DIR, IMAGE_DIR, DISPLAY_DURATION_SECONDS, DB_PATH, SIMULATE_NFC

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
log = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────

db = CardDatabase(DB_PATH)

# ── Overlay settings ──────────────────────────────────────────────────────────
# Defaults used on first run; after that values are loaded from the DB and
# persisted there so they survive server restarts.
_SETTINGS_DEFAULTS: dict = {
    "show_card_info":        False,
    "display_duration":      8.0,
    "show_status_dot":       False,
    "entrance_animation":    "slide-right",
    "exit_animation":        "fade",
    "show_card_back":        False,
    "landscape_battlefields": True,
}

def _load_settings() -> dict:
    saved = db.get_settings()
    merged = dict(_SETTINGS_DEFAULTS)
    merged.update(saved)   # saved values win over defaults
    return merged

overlay_settings: dict = _load_settings()
_reader: Optional[NFCReader] = None

# When set, the next tag scan will write this card_id to the tag instead of
# broadcasting a card event.  Cleared after a successful write or timeout.
_pending_write: Optional[str] = None
_pending_write_deadline: float = 0.0
# UID of the last successfully written tag.
# Cleared when a DIFFERENT UID is seen, meaning the card was lifted and a new
# one placed.  Prevents the deck queue from writing twice to the same chip in
# a single tap when the re-arm fires before the card is removed.
_last_write_uid: Optional[str] = None

# Overlay display settings — lives in memory, resets on server restart.
# Kept simple intentionally; persist to DB later if needed.
overlay_settings: dict = {
    "show_card_info":     False,
    "display_duration":   8.0,
    "show_status_dot":    False,
    "entrance_animation": "slide-right",
    "exit_animation":     "fade",
}

# Demo mode — fires simulated scans on a timer so streamers can set up
# their OBS scene without needing real NFC hardware present.
demo_state: dict = {
    "active":   False,
    "interval": 5,
    "card_id":  "tst-000",  # default demo card; change via settings or set to None for random
}
demo_task: Optional[asyncio.Task] = None


class ConnectionManager:
    """
    Keeps track of every WebSocket client (i.e. every open OBS browser source
    or admin tab) and provides a single broadcast method.

    A set is used instead of a list so that disconnecting a client is O(1).
    """

    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        log.info("Overlay connected  (total: %d)", len(self._clients))

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)
        log.info("Overlay disconnected (total: %d)", len(self._clients))

    async def broadcast(self, payload: dict):
        """Send a JSON message to every connected client."""
        if not self._clients:
            return
        text = json.dumps(payload)
        # asyncio.gather runs all the sends concurrently rather than one-by-one.
        dead: list[WebSocket] = []
        results = await asyncio.gather(
            *[ws.send_text(text) for ws in self._clients],
            return_exceptions=True,
        )
        for ws, result in zip(list(self._clients), results):
            if isinstance(result, Exception):
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ── Demo scan loop ────────────────────────────────────────────────────────────

async def demo_scan_loop():
    """
    Fires card scan events on a timer.

    If demo_state["card_id"] is set, always shows that specific card.
    Otherwise picks a random card with an image from the full library
    each cycle.
    """
    log.info("Demo scan loop started (interval: %ds)", demo_state["interval"])

    while True:
        await asyncio.sleep(demo_state["interval"])

        specific_id = demo_state.get("card_id")

        if specific_id:
            card = db.get_card_by_id(specific_id)
            if not card:
                log.warning("Demo: card_id %r not in database", specific_id)
                continue
        else:
            # Pick a random card that has an image.
            # OFFSET approach is more reliable than ORDER BY RANDOM() on large tables.
            count_row = db._conn.execute(
                "SELECT COUNT(*) AS n FROM cards WHERE image_filename != ''"
            ).fetchone()
            total = count_row["n"] if count_row else 0
            if total == 0:
                log.warning("Demo mode: no cards with images in database")
                continue
            import random as _random
            offset = _random.randint(0, total - 1)
            row = db._conn.execute(
                "SELECT id FROM cards WHERE image_filename != '' LIMIT 1 OFFSET ?",
                (offset,)
            ).fetchone()
            card = db.get_card_by_id(row["id"])
            if not card:
                continue

        log.info("Demo scan: %s", card.name)
        payload = {
            "event": "card_scanned",
            "uid":   "demo",
            "demo":  True,
            "card": {
                "id":             card.id,
                "name":           card.name,
                "set_code":       card.set_code,
                "card_number":    card.card_number,
                "card_type":      card.card_type,
                "cost":           card.cost,
                "traits":         card.traits,
                "rules_text":     card.rules_text,
                "image_filename": card.image_filename,
            },
            "display_duration": overlay_settings["display_duration"],
        }
        await manager.broadcast(payload)

async def nfc_scan_loop():
    """
    Runs forever in the background.  For each TagScan it either:
      - Writes a pending card_id to the tag (if a write was requested), or
      - Looks up the card_id in the database and broadcasts to the overlay.
    """
    global _reader, _pending_write, _pending_write_deadline, _last_write_uid
    _reader = create_reader()
    async for scan in _reader.scan_loop():
        import time as _time

        if demo_state["active"] and SIMULATE_NFC:
            continue

        # ── UID-based write lock ─────────────────────────────────────────────────────
        # A different UID arriving means the previous card was lifted off the
        # reader — the lock is cleared so the new card can be written to.
        if _last_write_uid is not None and scan.uid != _last_write_uid:
            _last_write_uid = None

        # Same card still sitting on the reader after a write — skip until removed.
        if _last_write_uid == scan.uid:
            await asyncio.sleep(0.05)
            continue

        # ── Write mode ────────────────────────────────────────────────────────
        if _pending_write is not None:
            if _time.monotonic() > _pending_write_deadline:
                log.warning("Pending write timed out — clearing")
                await manager.broadcast({"event": "write_timeout"})
                _pending_write = None
            else:
                card_id_to_write = _pending_write
                _pending_write   = None
                success = await _reader.write_card_id(card_id_to_write)
                if success:
                    log.info("Wrote card_id=%s to tag %s", card_id_to_write, scan.uid)
                    _last_write_uid  = scan.uid   # lock this UID until card is lifted
                    db.assign_tag(scan.uid, card_id_to_write)   # record for admin UI
                    db.log_scan(scan.uid, card_id_to_write)
                    await blink_success()
                    await manager.broadcast({
                        "event":   "tag_written",
                        "uid":     scan.uid,
                        "card_id": card_id_to_write,
                    })
                else:
                    log.error("Write failed for tag %s", scan.uid)
                    await manager.broadcast({"event": "write_failed", "uid": scan.uid})
                continue   # don't also broadcast a card_scanned for this scan

        # ── Read mode ─────────────────────────────────────────────────────────
        if scan.card_id is None:
            log.info("Blank or unrecognised tag: %s", scan.uid)
            await blink_unknown()
            db.log_scan(scan.uid, None)
            await manager.broadcast({"event": "blank_tag", "uid": scan.uid})
            continue

        card: Optional[Card] = db.get_card_by_id(scan.card_id)
        db.log_scan(scan.uid, scan.card_id)

        if card:
            log.info("Card found: %s (%s)", card.name, scan.card_id)
            await blink_success()
            payload = {
                "event":    "card_scanned",
                "uid":      scan.uid,
                "card": {
                    "id":             card.id,
                    "name":           card.name,
                    "set_code":       card.set_code,
                    "card_number":    card.card_number,
                    "card_type":      card.card_type,
                    "cost":           card.cost,
                    "traits":         card.traits,
                    "rules_text":     card.rules_text,
                    "image_filename": card.image_filename,
                },
                "display_duration": overlay_settings["display_duration"],
            }
        else:
            log.warning("Card ID on tag not in database: %s", scan.card_id)
            await blink_unknown()
            payload = {
                "event":   "unknown_card_id",
                "uid":     scan.uid,
                "card_id": scan.card_id,
            }

        await manager.broadcast(payload)


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI's preferred way to run startup/shutdown code.
    `asyncio.create_task` schedules the NFC loop as a background task that
    runs concurrently with the web server.
    """
    task = asyncio.create_task(nfc_scan_loop())
    log.info("NFC scan loop started")
    yield
    task.cancel()
    if demo_task and not demo_task.done():
        demo_task.cancel()
    db.close()


app = FastAPI(title="Rift Tap", lifespan=lifespan)

# Serve card images at /images/<filename>
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(IMAGE_DIR)), name="images")

# Serve the overlay and admin pages from the project root
OVERLAY_DIR = BASE_DIR / "overlay"
ADMIN_DIR   = BASE_DIR / "admin"
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
ADMIN_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/overlay", StaticFiles(directory=str(OVERLAY_DIR), html=True), name="overlay")
app.mount("/admin",   StaticFiles(directory=str(ADMIN_DIR),   html=True), name="admin")


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    OBS Browser Source (and the admin page) connect here.
    The server pushes events; the browser never needs to ask.
    """
    await manager.connect(ws)
    # Push current settings immediately so a freshly opened overlay or admin
    # page doesn't have to wait for the next scan to know the display state.
    await ws.send_text(json.dumps({"event": "settings", **overlay_settings}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── REST API ──────────────────────────────────────────────────────────────────
# These endpoints power the admin assignment interface.

@app.get("/api/cards/search")
async def search_cards(q: str):
    """Search cards by name. Used by the assignment page autocomplete."""
    if len(q) < 2:
        raise HTTPException(400, "Query must be at least 2 characters")
    cards = db.search_cards(q)
    return [
        {"id": c.id, "name": c.name, "set_code": c.set_code, "card_type": c.card_type}
        for c in cards
    ]


@app.post("/api/assign")
async def assign_tag(body: dict):
    """
    Assign an NFC UID to a card.

    Expected JSON body:
      { "uid": "04:A2:91:7C:3B:12:80", "card_id": "riftbound_card_00001" }
    """
    uid     = body.get("uid", "").strip()
    card_id = body.get("card_id", "").strip()
    if not uid or not card_id:
        raise HTTPException(400, "uid and card_id are required")
    card = db.get_card_by_id(card_id)
    if card is None:
        raise HTTPException(404, f"Card {card_id!r} not found")
    db.assign_tag(uid, card_id)
    return {"status": "ok", "uid": uid, "card_id": card_id}


@app.delete("/api/assign/{uid}")
async def unassign_tag(uid: str):
    db.unassign_tag(uid)
    return {"status": "ok", "uid": uid}


@app.get("/api/demo")
async def get_demo():
    return demo_state


@app.post("/api/demo")
async def set_demo(body: dict):
    """
    Start or stop the demo scan loop.

    Body: { "active": true }  or  { "active": false }
    Optional fields:
      interval  — seconds between scans (1–60)
      card_id   — show this specific card every cycle (null = random)
    """
    global demo_task

    if "interval" in body:
        interval = int(body["interval"])
        if not 1 <= interval <= 60:
            raise HTTPException(400, "interval must be between 1 and 60 seconds")
        demo_state["interval"] = interval

    if "card_id" in body:
        cid = body["card_id"]
        if cid is not None:
            if db.get_card_by_id(cid) is None:
                raise HTTPException(404, f"Card {cid!r} not in database")
        demo_state["card_id"] = cid

    active = body.get("active")
    if active is None:
        raise HTTPException(400, "active (bool) is required")

    if active and not demo_state["active"]:
        demo_state["active"] = True
        demo_task = asyncio.create_task(demo_scan_loop())
        log.info("Demo mode ON")

    elif not active and demo_state["active"]:
        demo_state["active"] = False
        if demo_task and not demo_task.done():
            demo_task.cancel()
        log.info("Demo mode OFF")

    await manager.broadcast({"event": "demo_state", **demo_state})
    return demo_state


@app.get("/api/settings")
async def get_settings():
    return overlay_settings


@app.post("/api/settings")
async def update_settings(body: dict):
    """
    Update one or more overlay settings and broadcast the change to all
    connected clients so the overlay updates instantly without a refresh.

    Example body: { "show_card_info": true }
    """
    allowed = {"show_card_info", "display_duration", "show_status_dot",
               "entrance_animation", "exit_animation",
               "show_card_back", "landscape_battlefields"}
    unknown = set(body) - allowed
    if unknown:
        raise HTTPException(400, f"Unknown settings: {unknown}")
    overlay_settings.update(body)
    db.save_settings(body)          # persist across restarts
    await manager.broadcast({"event": "settings", **overlay_settings})
    return overlay_settings


@app.post("/api/write-tag")
async def write_tag(body: dict):
    """
    Queue a card ID to be written to the next tag presented to the reader.

    The user taps (or holds) a card on the reader after calling this endpoint.
    The scan loop sees the pending write and calls reader.write_card_id().

    Body: { "card_id": "OGN001" }

    The result arrives as a WebSocket event:
      tag_written   — success
      write_failed  — tag was in range but write failed
      write_timeout — no tag appeared within 30 seconds
    """
    global _pending_write, _pending_write_deadline
    import time as _time

    card_id = body.get("card_id", "").strip()
    if not card_id:
        raise HTTPException(400, "card_id is required")
    card = db.get_card_by_id(card_id)
    if card is None:
        raise HTTPException(404, f"Card {card_id!r} not in database")

    timeout_seconds = float(body.get("timeout_seconds", 60))  # default 60 s
    _pending_write          = card_id
    _pending_write_deadline = _time.monotonic() + timeout_seconds

    log.info("Pending write queued: card_id=%s (%.0f s window)", card_id, timeout_seconds)
    return {"status": "waiting", "card_id": card_id}


@app.delete("/api/write-tag")
async def cancel_write():
    """Cancel a pending tag write."""
    global _pending_write, _pending_write_deadline
    _pending_write          = None
    _pending_write_deadline = 0.0
    return {"status": "cancelled"}


@app.get("/api/assignments")
async def list_assignments():
    """Return all current UID → card mappings for the admin page."""
    rows = db._conn.execute("""
        SELECT ta.uid, c.id AS card_id, c.name
        FROM tag_assignments ta
        JOIN cards c ON c.id = ta.card_id
        ORDER BY c.name
    """).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/scans/recent")
async def recent_scans(limit: int = 20):
    return db.recent_scans(limit)


@app.get("/riot.txt")
async def riot_verification():
    """Riot developer portal domain verification file."""
    return FileResponse(str(BASE_DIR / "riot.txt"))


@app.post("/api/cards/reseed")
async def reseed_cards():
    """
    Wipe the card catalog and rebuild it from data/card-sheets/*.csv.

    This is destructive by design: the entire `cards` table is cleared and
    reloaded from the CSVs bundled in the repo, so updating the catalog is
    just a matter of pulling a new release and hitting this endpoint.
    tag_assignments, scan_log and app_settings are left untouched — card
    IDs are stable across catalog updates, so existing NFC tag mappings
    keep resolving after a reseed.

    Returns a summary: { total, per_file, skipped, missing_images }.
    """
    sheets_dir = BASE_DIR / "data" / "card-sheets"
    if not sheets_dir.is_dir():
        raise HTTPException(404, f"No card sheets found at {sheets_dir}")

    cards, report = load_cards_from_sheets(sheets_dir)
    db.reseed_cards(cards)

    log.info(
        "Card reseed: %d cards from %d files, %d skipped, %d missing images",
        len(cards), len(report["per_file"]), len(report["skipped"]), len(report["missing_images"]),
    )
    return {"total": len(cards), **report}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Tracks an in-progress sync so we don't start two at once.
_sync_task: Optional[asyncio.Task] = None
_sync_log:  list[str] = []


@app.get("/api/sync/status")
async def sync_status():
    return {
        "running": _sync_task is not None and not _sync_task.done(),
        "log":     _sync_log[-50:],   # last 50 lines
    }


@app.post("/api/sync")
async def start_sync():
    """
    Begin a card library sync in the background.
    Returns immediately; poll /api/sync/status for progress.
    """
    global _sync_task, _sync_log

    if _sync_task and not _sync_task.done():
        raise HTTPException(409, "Sync already in progress")

    _sync_log = []

    async def _run():
        # Import here so the module is only loaded when actually needed
        # and avoids any import-time side effects on startup.
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
        from sync_cards import sync

        async def _log(msg: str):
            _sync_log.append(msg)
            await manager.broadcast({"event": "sync_progress", "message": msg})

        try:
            stats = await sync(progress_callback=_log)
            await manager.broadcast({"event": "sync_complete", "stats": stats})
        except Exception as exc:
            msg = f"Sync failed: {exc}"
            _sync_log.append(msg)
            await manager.broadcast({"event": "sync_error", "message": msg})

    _sync_task = asyncio.create_task(_run())
    return {"status": "started"}


# ── Root page ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "index.html"))
