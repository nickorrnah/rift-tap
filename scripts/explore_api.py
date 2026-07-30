"""
scripts/explore_api.py — Probe the Riot Riftbound API to discover its structure.

Since the docs aren't public yet, this script tries a set of likely endpoints
and prints whatever the API returns so we can reverse-engineer the shape of
the data and build a proper client around it.

Usage:
    1. Edit .env and replace "your-api-key-here" with your actual key.
    2. Run:  python scripts/explore_api.py

The Riot API key goes in the X-Riot-Token header — standard across all
Riot APIs (LoL, LoR, Valorant, etc.).
"""

import json
import sys
from pathlib import Path

# Load .env before anything else so the key is available via os.environ.
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import os
import httpx

API_KEY = os.environ.get("RIOT_API_KEY", "")
if not API_KEY or API_KEY == "your-api-key-here":
    print("ERROR: Set RIOT_API_KEY in your .env file first.")
    sys.exit(1)

HEADERS = {"X-Riot-Token": API_KEY}

# ── Candidate base URLs ───────────────────────────────────────────────────────
# Riot tends to use one of these patterns. We'll try them all and see which
# responds with something meaningful rather than a 404 or 403.
CANDIDATES = [
    "https://api.riotgames.com/riftbound",
    "https://americas.api.riotgames.com/riftbound",
    "https://europe.api.riotgames.com/riftbound",
    "https://asia.api.riotgames.com/riftbound",
    # Some Riot APIs serve static card data from a CDN-style endpoint:
    "https://dd.b.pvp.net/latest/core/en_us/data",   # LoR pattern for reference
]

# ── Endpoint paths to try once we find a live base ───────────────────────────
PATHS_TO_TRY = [
    "/v1/cards",
    "/v1/cards/all",
    "/v1/catalog",
    "/v1/catalog/cards",
    "/v1/sets",
    "/cards/v1/all",
    "",   # bare base URL — sometimes returns a version or index
]


def pretty(data) -> str:
    """Print the first 2000 characters of a response so we see the structure
    without being overwhelmed by a huge card list."""
    text = json.dumps(data, indent=2)
    if len(text) > 2000:
        return text[:2000] + f"\n  … ({len(text) - 2000} more characters)"
    return text


def probe(client: httpx.Client, url: str, label: str):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"  GET {url}")
    print(f"{'─'*60}")
    try:
        r = client.get(url, headers=HEADERS, timeout=10)
        print(f"  Status: {r.status_code}")
        print(f"  Content-Type: {r.headers.get('content-type', 'unknown')}")
        if r.status_code == 200:
            try:
                print(pretty(r.json()))
            except Exception:
                print(r.text[:500])
        elif r.status_code in (400, 401, 403, 404):
            try:
                print(pretty(r.json()))
            except Exception:
                print(r.text[:200])
    except httpx.RequestError as e:
        print(f"  Connection error: {e}")


def main():
    print("Riftbound API Explorer")
    print(f"Key prefix: {API_KEY[:8]}…  (showing first 8 chars only)\n")

    with httpx.Client() as client:
        for base in CANDIDATES:
            for path in PATHS_TO_TRY:
                url = base + path
                probe(client, url, f"{base}  →  {path or '/'}")


if __name__ == "__main__":
    main()
