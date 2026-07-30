"""
sync_cards.py — Download card images and metadata from the Riot API.

This module is called when the user triggers a card library sync from
the settings page.  It is intentionally separated from the main server
so it can also be run standalone from the command line during development.

Usage (standalone):
    python scripts/sync_cards.py

Usage (from the server):
    Called via POST /api/sync — see server.py

Design:
  - Incremental: only downloads images that are not already on disk.
  - Safe to interrupt: a partial sync leaves existing data intact.
  - The Riot API base URL and card data format are placeholders until
    the approved API key comes through with actual endpoint docs.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Allow running as a standalone script from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")

from card_db import CardDatabase, Card
from config import DB_PATH, IMAGE_DIR

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")

API_KEY = os.environ.get("RIOT_API_KEY", "")

# ── Placeholders — update these once the API docs are available ───────────────
# These will be filled in when the approved API key arrives with endpoint docs.
CARD_LIST_URL = "https://americas.api.riotgames.com/riftbound/v1/cards"
IMAGE_URL_TEMPLATE = "https://americas.api.riotgames.com/riftbound/v1/cards/{card_id}/image"
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {"X-Riot-Token": API_KEY}


async def sync(progress_callback=None) -> dict:
    """
    Sync card metadata and images from the Riot API.

    Args:
        progress_callback: optional async callable(message: str) that
                           receives status updates for display in the UI.

    Returns:
        dict with keys: cards_added, cards_updated, images_downloaded, errors
    """
    if not API_KEY or API_KEY == "your-api-key-here":
        raise RuntimeError("RIOT_API_KEY is not set in .env")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    db = CardDatabase(DB_PATH)

    stats = {"cards_added": 0, "cards_updated": 0, "images_downloaded": 0, "errors": 0}

    async def report(msg: str):
        log.info(msg)
        if progress_callback:
            await progress_callback(msg)

    await report("Fetching card list from Riot API…")

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        # ── Step 1: Fetch card list ───────────────────────────────────────────
        try:
            resp = await client.get(CARD_LIST_URL)
            resp.raise_for_status()
            cards_data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch card list: {exc}") from exc

        await report(f"Retrieved {len(cards_data)} cards from API")

        # ── Step 2: Upsert card records ───────────────────────────────────────
        # The field mapping below is a best guess at the API shape.
        # Update these key names once the real API response is known.
        for raw in cards_data:
            card_id       = raw.get("id") or raw.get("cardCode") or raw.get("cardId")
            name          = raw.get("name", "Unknown")
            set_code      = raw.get("set") or raw.get("setCode", "")
            card_number   = raw.get("number") or raw.get("cardNumber", "")
            card_type     = raw.get("type") or raw.get("cardType", "")
            cost          = raw.get("cost")
            traits        = ", ".join(raw.get("traits", []) or [])
            rules_text    = raw.get("rulesText") or raw.get("text", "")
            # Derive the local filename from the card id.
            # Adjust this once we know the actual image filename convention.
            image_filename = f"{card_id}.avif"

            card = Card(
                id=card_id,
                name=name,
                set_code=set_code,
                card_number=card_number,
                card_type=card_type,
                cost=int(cost) if cost is not None else None,
                traits=traits,
                rules_text=rules_text,
                image_filename=image_filename,
            )
            db.upsert_card(card)
            stats["cards_added"] += 1  # upsert handles both add + update

        await report(f"Card database updated ({stats['cards_added']} records)")

        # ── Step 3: Download missing images ───────────────────────────────────
        # Only download images that aren't already on disk.
        existing = {f.name for f in IMAGE_DIR.iterdir() if f.is_file()}
        missing  = [c for c in cards_data
                    if f"{c.get('id', '')}.avif" not in existing]

        await report(f"{len(missing)} images to download ({len(existing)} already cached)")

        for i, raw in enumerate(missing, 1):
            card_id = raw.get("id") or raw.get("cardCode") or raw.get("cardId")
            if not card_id:
                continue

            image_url = IMAGE_URL_TEMPLATE.format(card_id=card_id)
            dest      = IMAGE_DIR / f"{card_id}.avif"

            try:
                img_resp = await client.get(image_url)
                img_resp.raise_for_status()
                dest.write_bytes(img_resp.content)
                stats["images_downloaded"] += 1

                if i % 50 == 0 or i == len(missing):
                    await report(f"  Downloaded {i}/{len(missing)} images…")

            except Exception as exc:
                log.warning("Failed to download image for %s: %s", card_id, exc)
                stats["errors"] += 1

    db.close()
    await report(
        f"Sync complete — {stats['images_downloaded']} images downloaded, "
        f"{stats['errors']} errors"
    )
    return stats


if __name__ == "__main__":
    asyncio.run(sync())
