"""
card_db.py — SQLite database layer for cards and NFC tag mappings.

SQLite is a single-file database that requires no separate server process.
It is bundled with Python via the `sqlite3` module, so there is nothing to
install. For a prototype with ~800 cards it is more than fast enough.

Key concepts used here:
  - Context managers (`with conn:`) — automatically commit on success and
    roll back on error, preventing partial writes to the database.
  - Parameterised queries (`?` placeholders) — the correct way to pass
    user-controlled values into SQL. NEVER use f-strings or % formatting
    to build SQL queries; that opens you up to SQL injection.
  - dataclasses — lightweight containers for structured data; cheaper than
    a full ORM like SQLAlchemy for a project of this size.
"""

import sqlite3
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import DB_PATH

log = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────
# A dataclass is just a class where Python writes __init__, __repr__, etc.
# for you based on the field annotations. Think of it as a typed dictionary
# that you access with dot-notation (card.name) instead of brackets.

@dataclass
class Card:
    id: str                      # e.g. "riftbound_card_00427"
    name: str
    set_code: str                # e.g. "BASE"
    card_number: str             # e.g. "042"
    card_type: str               # e.g. "Unit", "Action", "Base"
    cost: Optional[int] = None
    traits: str = ""             # comma-separated trait list
    rules_text: str = ""
    image_filename: str = ""
    nfc_uid: Optional[str] = None  # populated when a tag is assigned


@dataclass
class ScanEvent:
    """Represents a single NFC scan that has been resolved to a card."""
    uid: str
    card: Optional[Card]
    assigned: bool = field(init=False)

    def __post_init__(self):
        self.assigned = self.card is not None


# ── Database class ────────────────────────────────────────────────────────────

class CardDatabase:
    """
    Thin wrapper around SQLite.

    We open one connection per CardDatabase instance.  On a Pi this will
    be a single long-lived object shared by the whole service.
    """

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False is safe here because we will access the DB
        # only from the main async loop.  If you ever add background threads,
        # revisit this.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row   # rows behave like dicts
        self._migrate()
        log.info("Database ready at %s", db_path)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _migrate(self):
        """
        Create tables if they do not exist yet.

        Using IF NOT EXISTS means this is safe to call every time the app
        starts — it is a no-op when the schema is already in place.
        """
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS cards (
                    id            TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    set_code      TEXT NOT NULL DEFAULT '',
                    card_number   TEXT NOT NULL DEFAULT '',
                    card_type     TEXT NOT NULL DEFAULT '',
                    cost          INTEGER,
                    traits        TEXT NOT NULL DEFAULT '',
                    rules_text    TEXT NOT NULL DEFAULT '',
                    image_filename TEXT NOT NULL DEFAULT ''
                );

                -- Separate table for the tag-to-card mapping.
                -- Keeping mappings separate means you can reassign a tag
                -- without touching the card record.
                CREATE TABLE IF NOT EXISTS tag_assignments (
                    uid     TEXT PRIMARY KEY,
                    card_id TEXT NOT NULL REFERENCES cards(id)
                );

                -- A simple log of every scan for future analytics / replay.
                CREATE TABLE IF NOT EXISTS scan_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid        TEXT NOT NULL,
                    card_id    TEXT,          -- NULL if unassigned at scan time
                    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- Persists overlay settings across server restarts.
                -- Each row is a key/value pair (value stored as JSON).
                CREATE TABLE IF NOT EXISTS app_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    # ── Card CRUD ─────────────────────────────────────────────────────────────

    def upsert_card(self, card: Card) -> None:
        """Insert or update a card record."""
        with self._conn:
            self._conn.execute("""
                INSERT INTO cards
                    (id, name, set_code, card_number, card_type, cost, traits, rules_text, image_filename)
                VALUES
                    (:id, :name, :set_code, :card_number, :card_type, :cost, :traits, :rules_text, :image_filename)
                ON CONFLICT(id) DO UPDATE SET
                    name           = excluded.name,
                    set_code       = excluded.set_code,
                    card_number    = excluded.card_number,
                    card_type      = excluded.card_type,
                    cost           = excluded.cost,
                    traits         = excluded.traits,
                    rules_text     = excluded.rules_text,
                    image_filename = excluded.image_filename
            """, {
                "id":             card.id,
                "name":           card.name,
                "set_code":       card.set_code,
                "card_number":    card.card_number,
                "card_type":      card.card_type,
                "cost":           card.cost,
                "traits":         card.traits,
                "rules_text":     card.rules_text,
                "image_filename": card.image_filename,
            })

    def get_card_by_id(self, card_id: str) -> Optional[Card]:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        return self._row_to_card(row) if row else None

    def search_cards(self, query: str) -> list[Card]:
        """
        Search by name OR card ID.
        Supports formats like "Ahri", "ven-031", "VEN031", "VEN-031".
        ID matches are sorted before name matches.
        """
        q      = f"%{query}%"
        # Normalised query: lowercase, hyphens removed — matches "ven031" → "ven-031"
        q_norm = f"%{query.lower().replace('-', '').replace(' ', '')}%"
        rows = self._conn.execute("""
            SELECT * FROM cards
            WHERE name LIKE ?
               OR LOWER(id) LIKE LOWER(?)
               OR REPLACE(LOWER(id), '-', '') LIKE ?
            ORDER BY
                CASE WHEN LOWER(id) = LOWER(?) THEN 0
                     WHEN LOWER(id) LIKE LOWER(?) THEN 1
                     ELSE 2 END,
                name
            LIMIT 50
        """, (q, q, q_norm, query, q)).fetchall()
        return [self._row_to_card(r) for r in rows]

    # ── Tag assignment ────────────────────────────────────────────────────────

    def assign_tag(self, uid: str, card_id: str) -> None:
        """Map an NFC UID to a card. Replaces any existing mapping."""
        with self._conn:
            self._conn.execute("""
                INSERT INTO tag_assignments (uid, card_id)
                VALUES (?, ?)
                ON CONFLICT(uid) DO UPDATE SET card_id = excluded.card_id
            """, (uid, card_id))
        log.info("Tag %s → card %s", uid, card_id)

    def unassign_tag(self, uid: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM tag_assignments WHERE uid = ?", (uid,))

    def lookup_uid(self, uid: str) -> Optional[Card]:
        """
        DEPRECATED — kept for migration compatibility only.
        Card IDs are now read directly from tag NDEF data.
        Will be removed in a future version.
        """
        row = self._conn.execute("""
            SELECT c.*
            FROM tag_assignments ta
            JOIN cards c ON c.id = ta.card_id
            WHERE ta.uid = ?
        """, (uid,)).fetchone()
        return self._row_to_card(row) if row else None

    # ── App settings (persistent overlay config) ─────────────────────────────

    def get_settings(self) -> dict:
        """Load all persisted settings.  Returns {} if nothing saved yet."""
        rows = self._conn.execute(
            "SELECT key, value FROM app_settings"
        ).fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def save_setting(self, key: str, value) -> None:
        """Persist a single setting value (JSON-serialised)."""
        with self._conn:
            self._conn.execute("""
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, json.dumps(value)))

    def save_settings(self, settings: dict) -> None:
        """Persist multiple settings at once."""
        with self._conn:
            for k, v in settings.items():
                self._conn.execute("""
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (k, json.dumps(v)))

    # ── Scan log ──────────────────────────────────────────────────────────────

    def log_scan(self, uid: str, card_id: Optional[str]) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO scan_log (uid, card_id) VALUES (?, ?)",
                (uid, card_id)
            )

    def recent_scans(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute("""
            SELECT sl.uid, sl.card_id, c.name, sl.scanned_at
            FROM scan_log sl
            LEFT JOIN cards c ON c.id = sl.card_id
            ORDER BY sl.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> Card:
        return Card(
            id=row["id"],
            name=row["name"],
            set_code=row["set_code"],
            card_number=row["card_number"],
            card_type=row["card_type"],
            cost=row["cost"],
            traits=row["traits"],
            rules_text=row["rules_text"],
            image_filename=row["image_filename"],
        )

    def close(self):
        self._conn.close()
