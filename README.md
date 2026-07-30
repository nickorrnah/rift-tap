# Rift Tap

**Live demo:** https://unstuffed-liking-neon.ngrok-free.dev
- [Overlay](https://unstuffed-liking-neon.ngrok-free.dev/overlay/index.html) — the OBS Browser Source
- [Admin](https://unstuffed-liking-neon.ngrok-free.dev/admin/index.html) — card assignment interface

> **Note:** The live demo requires the host machine to be running. If it is unavailable, see [Running Locally](#running-locally) below.

---

Rift Tap is a physical NFC card scanner overlay tool for **Riftbound** streamers and content creators. Tap a sleeved card on a reader connected to a Raspberry Pi and the official card art instantly appears in your OBS stream — no manual lookups, no keyboard shortcuts, no screen capture of another app.

This is a display-only tool. There is no rule enforcement, no game simulation, and no automated gameplay of any kind. Players still play the game manually at the table; Rift Tap gives their stream audience a live look at what was just played.

![Rift Tap demo](docs/readme-assets/rift-tap-demo.gif)

---

## How it works

```
NFC sticker on card sleeve
        ↓
PN532 NFC HAT (on Raspberry Pi 3)
        ↓
Python service reads tag UID
        ↓
SQLite lookup: UID → card record
        ↓
WebSocket broadcast
        ↓
OBS Browser Source overlay
```

1. Each card sleeve gets a small NFC sticker (NTAG215, 504 bytes).
2. A one-time setup maps each sticker's unique ID to the correct Riftbound card via the admin web page.
3. During play, tapping a sleeved card on the reader causes the card art to appear in the stream overlay and automatically hide after a configurable duration.

---

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi 3 Model B | Any Pi 3/4/5 works |
| PN532 NFC HAT | 40-pin GPIO HAT; set jumper to I2C |
| NTAG215 NFC stickers | 50-pack; one per card sleeve |
| MicroSD card (16 GB+) | For Raspberry Pi OS |

The HAT plugs directly onto the Pi's 40-pin GPIO header — no soldering or jumper wires needed.

---

## Running Locally

Requires Python 3.11+.

```bash
# 1. Clone the repo
git clone https://github.com/nickorrnah/rift-tap.git
cd rift-tap

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate        # macOS / Linux / Pi

# 3. Install dependencies
pip install -r requirements.txt

# 4. Seed the test database (5 sample cards)
python scripts/seed_db.py

# 5. Start the server
python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 — links to the overlay, card assignment, settings, and API docs are on the home screen.

> `SIMULATE_NFC=true` is the default. The simulated reader fires a fake card scan every 5–10 seconds so you can work on the overlay without physical hardware.

---

## OBS Setup

1. In OBS, add a **Browser Source** to your scene.
2. Set the URL to `http://<pi-ip>:8000/overlay/index.html`  
   (or `http://localhost:8000/overlay/index.html` for local testing).
3. Set **Width** to `1920` and **Height** to `1080` (match your stream resolution).
4. Click **Refresh browser when scene becomes active**.

The card panel appears in the **bottom-right corner** by default. Position and size are configurable via CSS variables in `overlay/overlay.css` (`--panel-bottom`, `--panel-right`, `--panel-width`).

Use the **▶ Start** demo button on the Settings page to trigger continuous card scans while you position and size the source in OBS — no physical hardware needed.

---

## Pages

| URL | Purpose |
|---|---|
| `/` | Home — links to all pages |
| `/overlay/index.html` | OBS Browser Source |
| `/admin/index.html` | Card Assignment — scan tags, search cards, assign |
| `/admin/settings.html` | Settings — animations, display duration, overlay options |
| `/docs` | Auto-generated REST API documentation |

---

## Settings

All settings apply in real time via WebSocket — no page refresh required.

### Overlay
| Setting | Default | Description |
|---|---|---|
| Show card info | Off | Display card name, type, traits, and rules text alongside the image |
| Display duration | 8s | How long the card stays visible. Set to **0** to keep it on screen until the next scan |
| Show connection dot | Off | Green dot in the overlay corner showing WebSocket status |

### Animations

15 entrance and exit animations including:

| Animation | Notes |
|---|---|
| Fade | Clean default |
| Slide from Right / Left / Bottom / Top | Directional |
| Zoom In / Out | Scales from/to center |
| **Slam** | Crashes in oversized and thuds to size |
| **Bounce** | Drops in with a bounce |
| **Elastic Pop** | Overshoots and snaps back |
| Flip Horizontal / Vertical | 3D card-flip with perspective |
| Rotate — TL / TR / BL / BR (CW or CCW) | Pivots from each corner, both directions |

When a new card is scanned while one is already on screen, the old card plays its configured exit animation simultaneously with the new card's entrance animation.

### Demo Mode
Fire continuous card scans on a configurable interval. Useful for positioning the OBS overlay without physical hardware present.

---

## Card Assignment

Open `http://<pi-ip>:8000/admin/index.html` from any browser on your local network.

1. Tap a card on the reader — the UID appears in **Last Scanned Tag**
2. Search by card name in the search box
3. Click the matching card in the results
4. Click **Assign Tag → Card**

The selected card stays pinned after assigning so you can scan multiple copies of the same card back-to-back without re-searching. Search a new card name when ready to move on.

---

## Raspberry Pi Setup

```bash
# Enable I2C on the Pi
sudo raspi-config
# Interface Options → I2C → Enable

# Verify the PN532 HAT is detected (should show address 0x24)
sudo apt install i2c-tools
i2cdetect -y 1

# Clone the repo and install dependencies
git clone https://github.com/nickorrnah/rift-tap.git
cd rift-tap
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Uncomment the Pi NFC packages in requirements.txt, then:
pip install adafruit-circuitpython-pn532 RPi.GPIO spidev

# Seed the database
python scripts/seed_db.py

# Run once manually to test
SIMULATE_NFC=false python -m uvicorn src.server:app --host 0.0.0.0 --port 8000

# Install as a systemd service (auto-starts on boot)
sudo cp deploy/rift-tap.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable rift-tap
sudo systemctl start rift-tap
```

Set the Pi's hostname to `rift-tap` for a fixed local URL that works on any network:
```bash
sudo hostnamectl set-hostname rift-tap
```
Then use `http://rift-tap.local:8000` from any device — no IP address needed.

---

## Project Structure

```
rift-tap/
├── src/
│   ├── server.py        # FastAPI server — HTTP + WebSocket
│   ├── card_db.py       # SQLite database layer
│   ├── nfc_reader.py    # PN532 driver + simulated reader
│   └── config.py        # Tuneable settings
├── overlay/
│   ├── index.html       # OBS Browser Source page
│   ├── overlay.css      # Panel styling + all animation keyframes
│   └── overlay.js       # WebSocket client + animation state machine
├── admin/
│   ├── index.html       # Card assignment interface
│   └── settings.html    # Overlay and animation settings
├── index.html           # Home page
├── scripts/
│   ├── seed_db.py       # Load test card data
│   └── explore_api.py   # Riot API endpoint discovery
├── deploy/
│   └── rift-tap.service # systemd unit file for Pi auto-start
├── docs/
│   └── readme-assets/   # Screenshots and demo GIF
├── images/              # Card images served by the overlay
├── data/                # SQLite database (auto-created, gitignored)
└── requirements.txt
```

---

## API Key

Card art and official card data are sourced exclusively through the [Riot Games API](https://developer.riotgames.com). This project has applied for an approved Riftbound API key.

Rift Tap is not endorsed or sponsored by Riot Games. All Riftbound assets are the property of Riot Games.

---

## License

MIT


**Live demo:** https://unstuffed-liking-neon.ngrok-free.dev
- [Overlay](https://unstuffed-liking-neon.ngrok-free.dev/overlay/index.html) — the OBS Browser Source
- [Admin](https://unstuffed-liking-neon.ngrok-free.dev/admin/index.html) — tag assignment interface (hit ▶ Demo to trigger live card scans)

> **Note:** The live demo requires the host machine to be running. If it is unavailable, see [Running Locally](#running-locally) below.

---

Rift Tap is a physical NFC card scanner overlay tool for **Riftbound** streamers and content creators. Tap a sleeved card on a reader connected to a Raspberry Pi and the official card art instantly appears in your OBS stream — no manual lookups, no keyboard shortcuts, no screen capture of another app.

This is a display-only tool. There is no rule enforcement, no game simulation, and no automated gameplay of any kind. Players still play the game manually at the table; Rift Tap gives their stream audience a live look at what was just played.

![Overlay preview showing a card fading in on a stream](docs/preview.png)

---

## How it works

```
NFC sticker on card sleeve
        ↓
PN532 NFC HAT (on Raspberry Pi 3)
        ↓
Python service reads tag UID
        ↓
SQLite lookup: UID → card record
        ↓
WebSocket broadcast
        ↓
OBS Browser Source overlay
```

1. Each card sleeve gets a small NFC sticker (NTAG215, 504 bytes).
2. A one-time setup maps each sticker's unique ID to the correct Riftbound card via the admin web page.
3. During play, tapping a sleeved card on the reader causes the card art to fade into the stream overlay and automatically hide after a few seconds.

---

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi 3 Model B | Any Pi 3/4/5 works |
| PN532 NFC HAT | 40-pin GPIO HAT; set jumper to I2C |
| NTAG215 NFC stickers | 50-pack; one per card sleeve |
| MicroSD card (16 GB+) | For Raspberry Pi OS |

The HAT plugs directly onto the Pi's 40-pin GPIO header — no soldering or jumper wires needed.

---

## Running Locally

Requires Python 3.11+.

```bash
# 1. Clone the repo
git clone https://github.com/nickorrnah/rift-tap.git
cd rift-tap

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate        # macOS / Linux / Pi

# 3. Install dependencies
pip install -r requirements.txt

# 4. Seed the test database (5 sample cards)
python scripts/seed_db.py

# 5. Start the server
python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 — links to the overlay and admin page are on the home screen.

> Set `SIMULATE_NFC=true` (the default) to run without physical hardware. The simulated reader fires a fake card scan every 5–10 seconds.

---

## OBS Setup

1. In OBS, add a **Browser Source** to your scene.
2. Set the URL to `http://<pi-ip>:8000/overlay/index.html` (or `http://localhost:8000/overlay/index.html` for local testing).
3. Set **Width** to `1920` and **Height** to `1080` (match your stream resolution).
4. Click **OK**.

The card panel appears in the **bottom-right corner** by default. Reposition it in `overlay/overlay.css` by changing `--panel-bottom` and `--panel-right`.

Use the **▶ Demo** button in the admin page to fire continuous card scans while you position and size the source in OBS — no physical hardware needed.

---

## Admin Interface

Open `http://<pi-ip>:8000/admin/index.html` from any browser on your local network.

| Feature | Description |
|---|---|
| **Last Scanned Tag** | Shows the UID of the most recently tapped card |
| **Assign to Card** | Search by card name and assign the UID |
| **Card info in overlay** | Toggle to show/hide card name, type, and rules text alongside the image |
| **▶ Demo** | Fire continuous fake scans for OBS setup |
| **Current Assignments** | View and remove all UID → card mappings |
| **Recent Scans** | Live log of every scan |

---

## Raspberry Pi Setup

```bash
# Enable I2C on the Pi
sudo raspi-config
# Interface Options → I2C → Enable

# Verify the PN532 HAT is detected (should show address 0x24)
sudo apt install i2c-tools
i2cdetect -y 1

# Clone the repo and install dependencies
git clone https://github.com/nickorrnah/rift-tap.git
cd rift-tap
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Uncomment the Pi NFC packages in requirements.txt, then:
pip install adafruit-circuitpython-pn532 RPi.GPIO spidev

# Seed the database
python scripts/seed_db.py

# Run once manually to test
SIMULATE_NFC=false python -m uvicorn src.server:app --host 0.0.0.0 --port 8000

# Install as a systemd service (auto-starts on boot)
sudo cp deploy/rift-tap.service /etc/systemd/system/
 sudo systemctl daemon-reload
 sudo systemctl enable rift-tap
 sudo systemctl start rift-tap
```

Set the Pi's hostname to `rift-tap` for a fixed local URL:
```bash
sudo hostnamectl set-hostname rift-tap
```
Then use `http://rift-tap.local:8000` from any device on your network — no IP address needed.

---

## Project Structure

```
rift-tap/
├── src/
│   ├── server.py        # FastAPI server — HTTP endpoints + WebSocket
│   ├── card_db.py       # SQLite database layer
│   ├── nfc_reader.py    # PN532 driver + simulated reader
│   └── config.py        # All tuneable settings
├── overlay/
│   ├── index.html       # OBS Browser Source page
│   ├── overlay.css      # Styling + fade animation
│   └── overlay.js       # WebSocket client
├── admin/
│   └── index.html       # Tag assignment interface
├── scripts/
│   ├── seed_db.py       # Load test card data
│   └── explore_api.py   # Riot API endpoint discovery
├── deploy/
│   └── rift-tap.service             # systemd unit file
├── images/              # Card images served by the overlay
├── data/                # SQLite database (auto-created)
└── requirements.txt
```

---

## API Key

Card art and official card data are sourced exclusively through the [Riot Games API](https://developer.riotgames.com). This project has applied for an approved Riftbound API key.

Rift Tap is not endorsed or sponsored by Riot Games. All Riftbound assets are the property of Riot Games.

---

## License

MIT
