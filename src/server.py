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
from nfc_reader import create_reader
from config import BASE_DIR, IMAGE_DIR, DISPLAY_DURATION_SECONDS, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
log = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────

db = CardDatabase(DB_PATH)

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
    "interval": 5,    # seconds between demo scans
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
    Fires a real card scan event on a timer using whatever cards are
    currently assigned in the database.  Rotates through all assigned
    cards in sequence so the overlay shows real imagery.

    This runs as a cancellable asyncio Task — cancelling it (when demo
    mode is turned off) raises CancelledError internally which exits the
    loop cleanly.
    """
    log.info("Demo scan loop started (interval: %ds)", demo_state["interval"])
    assigned: list[dict] = []
    idx = 0

    while True:
        await asyncio.sleep(demo_state["interval"])

        # Refresh the card list each cycle so newly assigned tags show up.
        rows = db._conn.execute(
            "SELECT ta.uid FROM tag_assignments ta"
        ).fetchall()
        assigned = [r["uid"] for r in rows]

        if not assigned:
            log.warning("Demo mode: no assigned tags in database — nothing to show")
            continue

        uid = assigned[idx % len(assigned)]
        idx += 1

        card: Optional[Card] = db.lookup_uid(uid)
        if not card:
            continue

        log.info("Demo scan: %s (%s)", card.name, uid)
        payload = {
            "event": "card_scanned",
            "uid":   uid,
            "demo":  True,   # flag so the overlay/admin can style it differently if desired
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
            "display_duration": DISPLAY_DURATION_SECONDS,
        }
        await manager.broadcast(payload)

async def nfc_scan_loop():
    """
    Runs forever in the background.  For each scanned UID it:
      1. Looks up the card in the database.
      2. Logs the scan.
      3. Broadcasts an event to all connected overlay windows.
    """
    reader = create_reader()
    async for uid in reader.scan_loop():
        card: Optional[Card] = db.lookup_uid(uid)
        db.log_scan(uid, card.id if card else None)

        if card:
            log.info("Card found: %s (%s)", card.name, uid)
            payload = {
                "event":    "card_scanned",
                "uid":      uid,
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
            log.warning("Unknown tag: %s", uid)
            payload = {
                "event": "unknown_tag",
                "uid":   uid,
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
    Optional: { "active": true, "interval": 3 }  to change scan speed.
    """
    global demo_task

    if "interval" in body:
        interval = int(body["interval"])
        if not 1 <= interval <= 60:
            raise HTTPException(400, "interval must be between 1 and 60 seconds")
        demo_state["interval"] = interval

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
               "entrance_animation", "exit_animation"}
    unknown = set(body) - allowed
    if unknown:
        raise HTTPException(400, f"Unknown settings: {unknown}")
    overlay_settings.update(body)
    await manager.broadcast({"event": "settings", **overlay_settings})
    return overlay_settings


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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ── Root page ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "index.html"))
