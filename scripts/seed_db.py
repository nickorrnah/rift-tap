"""
scripts/seed_db.py — Populate the database with test cards and tag mappings.

Run this once before starting the server:
    cd card-scanner
    python scripts/seed_db.py

You can run it again at any time — upsert_card is idempotent (safe to
repeat without duplicating data).
"""

import sys
from pathlib import Path

# Make sure imports from src/ work when run from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from card_db import CardDatabase, Card
from config import DB_PATH

# ── Test cards ────────────────────────────────────────────────────────────────
# These are fictional Riftbound-style cards for prototype testing.
# Replace with real card data once you have it.

TEST_CARDS: list[Card] = [
    Card(
        id="riftbound_card_00001",
        name="Punching Poro",
        set_code="OGN",
        card_number="001",
        card_type="Unit",
        cost=1,
        traits="Poro",
        rules_text="When Punching Poro attacks, it deals 1 damage to the defender.",
        image_filename="punching-poro.png",
    ),
]

# ── Simulated NFC UIDs ────────────────────────────────────────────────────────
# These match the UIDs in SimulatedReader._SIMULATED_UIDS in nfc_reader.py.
# When running in simulation mode, tapping these "virtual tags" will show
# the corresponding cards in the overlay.

TEST_ASSIGNMENTS = {
    "04:A2:91:7C:3B:12:80": "riftbound_card_00001",
    "04:B3:12:5D:4E:23:91": "riftbound_card_00001",
    "04:C4:33:6E:5F:34:A2": "riftbound_card_00001",
    "04:D5:54:7F:60:45:B3": "riftbound_card_00001",
    "04:E6:75:80:71:56:C4": "riftbound_card_00001",
}


def seed():
    db = CardDatabase(DB_PATH)

    print(f"Seeding database at {DB_PATH} …")

    for card in TEST_CARDS:
        db.upsert_card(card)
        print(f"  + {card.id}  {card.name}")

    for uid, card_id in TEST_ASSIGNMENTS.items():
        db.assign_tag(uid, card_id)
        print(f"  → {uid}  ⇒  {card_id}")

    db.close()
    print("Done.")


if __name__ == "__main__":
    seed()
