"""
card_sheets.py — Load the card catalog from data/card-sheets/*.csv.

Each set has its own CSV (OGN.csv, VEN.csv, ...) with the same columns as
the old export format: id, name, set_code, card_number, card_type, cost,
traits, rules_text, image_filename. These files are shipped in the git repo
and are the source of truth for the card catalog — updating cards is just
a matter of pulling a new release and reseeding from the bundled sheets.
"""

import csv
from pathlib import Path

from card_db import Card
from config import IMAGE_DIR


def load_cards_from_sheets(sheets_dir: Path) -> tuple[list[Card], dict]:
    """
    Parse every *.csv in sheets_dir into Card objects.

    Returns (cards, report) where report has:
      - per_file: {filename: row_count}
      - skipped: [{file, row_number, reason}]   # blank id/name
      - missing_images: [card_id]                # image_filename set but not found in IMAGE_DIR
    """
    cards: list[Card] = []
    per_file: dict[str, int] = {}
    skipped: list[dict] = []
    missing_images: list[str] = []

    for sheet in sorted(sheets_dir.glob("*.csv")):
        with sheet.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            count = 0
            for row_number, row in enumerate(reader, start=2):  # header is row 1
                card_id = (row.get("id") or "").strip()
                name    = (row.get("name") or "").strip()
                if not card_id or not name:
                    skipped.append({
                        "file": sheet.name,
                        "row_number": row_number,
                        "reason": "missing id or name",
                    })
                    continue

                cost_raw = (row.get("cost") or "").strip()
                cost = int(cost_raw) if cost_raw.isdigit() else None
                image_filename = (row.get("image_filename") or "").strip()

                if image_filename and not (IMAGE_DIR / image_filename).exists():
                    missing_images.append(card_id)

                cards.append(Card(
                    id=card_id,
                    name=name,
                    set_code=(row.get("set_code") or "").strip(),
                    card_number=(row.get("card_number") or "").strip(),
                    card_type=(row.get("card_type") or "").strip(),
                    cost=cost,
                    traits=(row.get("traits") or "").strip(),
                    rules_text=(row.get("rules_text") or "").strip(),
                    image_filename=image_filename,
                ))
                count += 1
            per_file[sheet.name] = count

    report = {
        "per_file": per_file,
        "skipped": skipped,
        "missing_images": missing_images,
    }
    return cards, report
