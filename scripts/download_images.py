"""
download_images.py — Download card images from Piltover Archive.

Reads the card ID list from docs/planning/card-id-list.txt and downloads
a .webp image for each card from cdn.piltoverarchive.com.

Features:
  - Incremental: skips cards whose image file already exists on disk.
  - Concurrent: downloads up to MAX_CONCURRENT images at a time.
  - Cards whose ID contains a '*' are skipped (errata/placeholder entries).
  - Cards with no name entry are still downloaded (ID-only lines are valid).

Usage:
    python scripts/download_images.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from config import IMAGE_DIR

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")

CARD_ID_LIST = Path(__file__).parent.parent / "docs" / "planning" / "card-id-list.txt"
IMAGE_URL = "https://cdn.piltoverarchive.com/cards/{card_id}.webp?width=3840"

MAX_CONCURRENT = 8  # simultaneous downloads


def load_card_ids(path: Path) -> list[str]:
    """Return all card IDs from the list, skipping blank lines and '*' IDs."""
    ids = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            card_id = parts[0].strip()
            if not card_id:
                continue
            if "*" in card_id:
                log.debug("Skipping errata ID: %s", card_id)
                continue
            ids.append(card_id)
    return ids


async def download_card(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    card_id: str,
    stats: dict,
) -> None:
    dest = IMAGE_DIR / f"{card_id.lower()}.webp"

    if dest.exists():
        log.debug("Already exists, skipping: %s", card_id)
        stats["skipped"] += 1
        return

    url = IMAGE_URL.format(card_id=card_id.upper())

    async with semaphore:
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            log.info("Downloaded: %s", card_id)
            stats["downloaded"] += 1
        except httpx.HTTPStatusError as exc:
            log.warning("HTTP %s for %s — skipping", exc.response.status_code, card_id)
            stats["errors"] += 1
        except Exception as exc:
            log.warning("Failed to download %s: %s", card_id, exc)
            stats["errors"] += 1


async def main() -> None:
    if not CARD_ID_LIST.exists():
        log.error("Card ID list not found: %s", CARD_ID_LIST)
        sys.exit(1)

    card_ids = load_card_ids(CARD_ID_LIST)
    log.info("Loaded %d card IDs", len(card_ids))

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    stats = {"downloaded": 0, "skipped": 0, "errors": 0}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [
            download_card(client, semaphore, card_id, stats)
            for card_id in card_ids
        ]
        await asyncio.gather(*tasks)

    total = len(card_ids)
    log.info(
        "Done. %d downloaded, %d already existed, %d errors (total: %d)",
        stats["downloaded"],
        stats["skipped"],
        stats["errors"],
        total,
    )


if __name__ == "__main__":
    asyncio.run(main())
