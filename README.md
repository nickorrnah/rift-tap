# Rift Tap

A physical NFC card scanner overlay for **Riftbound** streamers. Tap a tagged card sleeve on a reader and the official card art appears in your OBS stream — instantly, automatically, no keyboard shortcuts or screen capture required.

**Live demo:** https://unstuffed-liking-neon.ngrok-free.dev
→ [Overlay](https://unstuffed-liking-neon.ngrok-free.dev/overlay/index.html) · [Admin](https://unstuffed-liking-neon.ngrok-free.dev/admin/index.html) · hit **▶ Start** in the header to trigger live card scans

> Demo requires the host machine to be running. If unavailable, see [Running Locally](#running-locally).

![Rift Tap demo](docs/readme-assets/rift-tap-demo.gif)

---

## What it does

A Raspberry Pi with an NFC HAT sits at the table. Each card sleeve has a small NFC sticker on the back. When a player taps a card on the reader, Rift Tap:

1. Reads the tag's unique ID
2. Looks up the associated Riftbound card in a local database
3. Pushes the card data to a browser overlay via WebSocket
4. The card art fades into the OBS stream with a configurable animation

**This is a display-only tool.** There is no rule enforcement, no game state tracking, and no automated gameplay of any kind. Players play the game manually at the table — Rift Tap gives their audience a live view of what card was just played.

All card art and text is sourced exclusively through the Riot Games API.

---

## Key features

- **15 entrance and exit animations** — fade, slide, slam, bounce, elastic, flip, rotate from any corner
- **Configurable display duration** — set to 0 to keep the card visible until the next scan
- **Card info toggle** — show just the image, or include name, type, traits, and rules text
- **Tag assignment interface** — tap a card, search by name, assign; stays locked on a card for rapid multi-copy assignment
- **Demo mode** — fire continuous scans for OBS setup without physical hardware
- **LED scan feedback** — the Pi's built-in LED blinks on every successful scan
- **Works over USB** — Pi presents as a USB Ethernet adapter; one cable connects it to the streaming laptop

---

## Hardware

A Raspberry Pi with a PN532 NFC HAT and NTAG215 NFC stickers on the card sleeves. The Pi connects to the device running OBS over a single USB cable — no WiFi configuration, no network setup. The browser source URL is fixed regardless of location.

---

## Running Locally

Requires Python 3.11+. Runs in simulation mode by default (no hardware needed).

```bash
git clone https://github.com/nickorrnah/rift-tap.git
cd rift-tap
python -m venv .venv && .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/seed_db.py
python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` — the home page links to the overlay, card assignment, and settings pages. The simulated reader fires a fake scan every 5–10 seconds so the overlay can be tested without physical hardware.

---

## Pages

| URL | Purpose |
|---|---|
| `/` | Home |
| `/overlay/index.html` | OBS Browser Source (1920×1080, transparent background) |
| `/admin/index.html` | Card assignment — tap, search, assign |
| `/admin/settings.html` | Animations, display duration, overlay options, card library update |
| `/docs` | Auto-generated REST API documentation |

---
