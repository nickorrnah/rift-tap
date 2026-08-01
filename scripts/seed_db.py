"""
scripts/seed_db.py — Build the card database from the compiled card ID list.

Data source: docs/planning/card-id-list.txt
  Format:    {card_id}\t{card_name}  (one card per line)
  Example:   ogn-001\tBlazing Scorcher

Image lookup: images/{card_id}.webp
  Cards with no downloaded image get image_filename="" and will show
  the placeholder in the overlay until their image is available.

Run:
    cd card-scanner
    python scripts/seed_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from card_db import CardDatabase, Card
from config import DB_PATH, BASE_DIR, IMAGE_DIR

CARD_LIST = BASE_DIR / "docs" / "planning" / "card-id-list.txt"


def seed():
    if not CARD_LIST.exists():
        print(f"ERROR: card list not found at {CARD_LIST}")
        sys.exit(1)

    db = CardDatabase(DB_PATH)

    lines = CARD_LIST.read_text(encoding="utf-8").splitlines()
    cards = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Support both tab and space as separator (some lines use spaces)
        if "\t" in line:
            parts = line.split("\t", 1)
        else:
            parts = line.split(" ", 1)

        card_id = parts[0].strip().rstrip("*")  # strip trailing * (special marker)
        name    = parts[1].strip() if len(parts) > 1 else card_id  # fall back to ID if no name

        # Check if the image exists
        image_path = IMAGE_DIR / f"{card_id}.webp"
        image_filename = f"{card_id}.webp" if image_path.exists() else ""

        cards.append(Card(
            id=card_id,
            name=name,
            set_code=card_id.split("-")[0].upper() if "-" in card_id else "",
            card_number=card_id.split("-")[1] if "-" in card_id else "",
            card_type="",
            cost=None,
            traits="",
            rules_text="",
            image_filename=image_filename,
        ))

    print(f"Seeding {len(cards)} cards into {DB_PATH} ...")

    # ── Test card ───────────────────────────────────────────────────────
    # A hand-drawn placeholder used for OBS setup and demo mode.
    # Always inserted regardless of the card list.
    cards.insert(0, Card(
        id="tst-000",
        name="Placeholder Card",
        set_code="TST",
        card_number="000",
        card_type="",
        cost=None,
        traits="",
        rules_text="",
        image_filename="punching-poro.png",
    ))

    for card in cards:
        db.upsert_card(card)

    with_image    = sum(1 for c in cards if c.image_filename)
    without_image = sum(1 for c in cards if not c.image_filename)

    print(f"  {with_image} cards with images")
    print(f"  {without_image} cards missing images (will show placeholder)")
    print("Done.")
    db.close()


if __name__ == "__main__":
    seed()

