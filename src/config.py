"""
config.py — Central configuration for the card scanner service.

Keeping all tuneable values in one place means you never have to hunt
through multiple files when you want to change something like the
WebSocket port or the scan cooldown.
"""

import os

# ── Database ──────────────────────────────────────────────────────────────────
# Using pathlib here keeps paths portable across operating systems.
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent   # root of the project
DB_PATH  = BASE_DIR / "data" / "cards.db"
IMAGE_DIR = BASE_DIR / "images"

# ── NFC Reader ────────────────────────────────────────────────────────────────
# How long (in seconds) to wait before the same tag can trigger another scan.
# Without a cooldown, one physical tap can fire dozens of read events.
SCAN_COOLDOWN_SECONDS = 3.0

# Which hardware interface the PN532 HAT uses.
# Options: "SPI", "I2C", "UART"
# The PN532 NFC HAT defaults to I2C — check the small jumper/switch on your
# board to confirm.  I2C uses only 4 pins (VCC, GND, SDA, SCL) and is the
# easiest to verify.  Switch to SPI later if you need faster polling.
NFC_INTERFACE = os.environ.get("NFC_INTERFACE", "I2C")

# Set this to True while you are developing without real NFC hardware.
# The service will generate fake scan events on a timer so you can work on
# the overlay and database logic without a physical reader.
SIMULATE_NFC = os.environ.get("SIMULATE_NFC", "true").lower() == "true"

# ── Web Server ────────────────────────────────────────────────────────────────
HOST = os.environ.get("HOST", "0.0.0.0")  # 0.0.0.0 = accept connections from any device on the LAN
PORT = int(os.environ.get("PORT", 8000))

# ── Overlay ───────────────────────────────────────────────────────────────────
# How many seconds the card image stays visible before fading out.
DISPLAY_DURATION_SECONDS = float(os.environ.get("DISPLAY_DURATION", 8.0))
