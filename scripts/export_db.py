"""
scripts/export_db.py — Export the card database to a CSV file.

Use this to pull the current DB state into a spreadsheet for editing
(e.g. filling in card_type values) and then re-import via the web UI
or scripts/seed_db.py.

Usage:
    python scripts/export_db.py                    # exports to cards_export.csv
    python scripts/export_db.py my_cards.csv       # exports to a custom filename

The exported CSV is UTF-8 with BOM so Excel opens it correctly without
needing to configure the import wizard.

Workflow:
  1. python scripts/export_db.py
  2. Open cards_export.csv in Excel or Google Sheets
  3. Fill in the card_type column:
       unit, action, rune, battlefield, legend, champion, token
  4. Fix any missing names or image filenames
  5. Save as CSV
  6. Upload via Settings → Card Database → Import from CSV
     (or run: python scripts/seed_db.py and replace the source file)
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from card_db import CardDatabase
from config import DB_PATH

FIELDNAMES = [
    "id", "name", "set_code", "card_number", "card_type",
    "cost", "traits", "rules_text", "image_filename",
]


def export(output_path: Path):
    db = CardDatabase(DB_PATH)
    rows = db._conn.execute(
        "SELECT id, name, set_code, card_number, card_type, "
        "cost, traits, rules_text, image_filename "
        "FROM cards ORDER BY set_code, card_number, id"
    ).fetchall()
    db.close()

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    print(f"Exported {len(rows)} cards to {output_path}")

    # Quick summary of what needs filling in
    missing_type  = sum(1 for r in rows if not r["card_type"])
    missing_image = sum(1 for r in rows if not r["image_filename"])
    if missing_type:
        print(f"  {missing_type} cards have no card_type — fill in this column")
    if missing_image:
        print(f"  {missing_image} cards have no image_filename")


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cards_export.csv")
    export(output)
