"""
scripts/seed_db.py — Rebuild the card database from data/card-sheets/*.csv.

Data source: data/card-sheets/{SET}.csv (one file per set, e.g. OGN.csv)
  Columns:   id,name,set_code,card_number,card_type,cost,traits,rules_text,image_filename

Image lookup: images/{image_filename}
  Cards with a blank or missing image_filename show the placeholder in the
  overlay until their image is available.

This wipes the entire `cards` table and reinserts from scratch — the CSVs
are the source of truth for the card catalog. NFC tag assignments are left
untouched since card IDs are stable across catalog updates.

Run:
    cd card-scanner
    python scripts/seed_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from card_db import CardDatabase
from card_sheets import load_cards_from_sheets
from config import DB_PATH, BASE_DIR

CARD_SHEETS_DIR = BASE_DIR / "data" / "card-sheets"


def seed():
    if not CARD_SHEETS_DIR.is_dir():
        print(f"ERROR: card sheets directory not found at {CARD_SHEETS_DIR}")
        sys.exit(1)

    cards, report = load_cards_from_sheets(CARD_SHEETS_DIR)

    print(f"Reseeding {len(cards)} cards into {DB_PATH} ...")
    for filename, count in report["per_file"].items():
        print(f"  {filename}: {count} cards")

    if report["skipped"]:
        print(f"  {len(report['skipped'])} rows skipped (missing id or name):")
        for entry in report["skipped"]:
            print(f"    {entry['file']} row {entry['row_number']}: {entry['reason']}")

    with_image    = len(cards) - len(report["missing_images"])
    without_image = len(report["missing_images"])
    print(f"  {with_image} cards with images")
    print(f"  {without_image} cards missing images (will show placeholder)")

    db = CardDatabase(DB_PATH)
    db.reseed_cards(cards)
    db.close()

    print("Done.")


if __name__ == "__main__":
    seed()
