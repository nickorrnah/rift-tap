# Rift Tap — Product Architecture & Roadmap

This document captures product decisions, hardware choices, and technical
architecture for the Rift Tap NFC card scanner. It is a living document —
update it as decisions change.

---

## Product Models

Two tiers are planned. The Standard model is the primary focus and the one
currently under development.

### Standard — "Rift Tap"

A plug-and-play NFC scanner in a compact enclosure. The user plugs a single
USB cable into their laptop and adds a browser source in OBS. No other setup
is required.

**Target BOM (per unit, wholesale estimate):**

| Component | Part | Est. cost |
|---|---|---|
| SBC | Raspberry Pi Zero 2W | ~$15 |
| NFC reader | PN532 NFC HAT (40-pin GPIO) | ~$12 |
| NFC stickers | NTAG215, 50-pack (one per sleeve) | ~$8 |
| Storage | 16 GB SanDisk Endurance microSD | ~$9 |
| Cable | USB-C to micro-USB (data + power) | ~$3 |
| Enclosure | Custom or off-the-shelf Pi Zero case | ~$5 |
| **Total** | | **~$52** |

**User setup (target experience):**
1. Plug USB-C cable from laptop to device
2. Windows auto-installs USB Ethernet driver (RNDIS, built-in since Win7)
3. Open OBS → Add Browser Source → `http://rift-tap.local:8000/overlay/index.html`
4. Open `http://rift-tap.local:8000/admin` in a browser to assign cards

That is the entire setup. No WiFi credentials, no IP addresses, no
configuration files.

**Scan feedback:**
The Pi Zero 2W's built-in green ACT LED provides tactile confirmation without
any additional hardware:
- **Two quick blinks** — card recognised and matched to a card record
- **One long pulse** — tag scanned but not yet assigned to a card

Implemented in `src/led_feedback.py`. The LED is controlled via the kernel
sysfs interface (`/sys/class/leds/ACT/`) and is a no-op on non-Pi systems.

---

### Pro — "Rift Tap Display" *(planned, not started)*

The same scanner with a touchscreen for at-a-glance card confirmation and
on-device settings management. Aimed at streamers who want the device to be
self-contained and visually impressive on stream or at a card shop.

**Target BOM delta over Standard:**

| Component | Part | Est. additional cost |
|---|---|---|
| SBC upgrade | Raspberry Pi 3B or 4 (2GB) | +$20–30 |
| Display | Waveshare 5" or official 7" DSI touchscreen | +$30–45 |
| Enclosure | Custom enclosure with display cutout | +$15 |
| **Additional cost** | | **+$65–90** |

**Extra features over Standard:**
- Touchscreen shows the admin and settings pages (Chromium in kiosk mode, no code changes needed — the existing web interface is the touchscreen UI)
- When a card is scanned, the card image appears on the local screen as visual confirmation for players at the table
- Touch to access settings without needing a phone or laptop

**No additional software work required.** Chromium in kiosk mode pointing at
`http://localhost:8000` provides the full UI. The overlay page doubles as the
on-device display.

---

## Connectivity: USB Gadget Mode

### Why USB gadget instead of WiFi

The Pi and the OBS laptop must be on the same network. Options considered:

| Approach | Pros | Cons |
|---|---|---|
| Same LAN / ethernet | Simple | Requires network infrastructure at venue |
| Pi as WiFi AP | No existing network needed | Laptop must switch WiFi; breaks internet if not on ethernet |
| USB gadget (chosen) | Single cable, zero config, always works | Pi Zero 2W micro-USB; Pi 3B requires dwc2 config |

USB gadget mode creates a private point-to-point network between the Pi and
the laptop over a single USB cable. OBS traffic to `rift-tap.local` travels
over this private link; the laptop's internet connection (ethernet or WiFi) is
unaffected.

### Pi Zero 2W setup

The Pi Zero 2W has a dedicated OTG (USB data) port separate from its power
input. Both USB OTG and power can be supplied by the laptop's USB port if it
provides sufficient current (~500–900mA, well within USB 3.0 spec for a Pi
Zero 2W at idle).

Configuration (added to `/boot/firmware/config.txt` and
`/boot/firmware/cmdline.txt` on the Pi SD card):

```
# config.txt
dtoverlay=dwc2

# cmdline.txt (appended, space-separated)
modules-load=dwc2,g_cdc
```

After reboot, Windows detects the Pi as a "USB Ethernet/RNDIS Gadget" and
installs the built-in driver automatically.

### Fixed IP and mDNS hostname

The Pi is assigned a static IP on the USB gadget interface (`10.55.55.1`).
The `rift-tap.local` mDNS hostname (via `avahi-daemon`) resolves to this IP
on the same network, so the browser source URL never changes regardless of
which laptop is used.

```
http://rift-tap.local:8000/overlay/index.html
```

### Pi 3B fallback

The Pi 3B can run USB gadget mode via its micro-USB power port using the same
`dtoverlay=dwc2` approach. Caveats:
- The power and data share the same micro-USB port, so the cable must be a
  full data cable (not a charge-only cable — a common failure point with
  users)
- Power draw is higher (~1A under load vs ~300mA for Pi Zero 2W); most USB 3.0
  ports supply this but it is marginal
- Viable for development and testing; not ideal for a shipped product

### WiFi AP as fallback mode

If USB gadget mode is unavailable (e.g., the user only has a USB-A to USB-A
cable), the Pi can fall back to broadcasting its own WiFi AP. This requires
the user to connect their laptop WiFi to "RiftTap" while keeping ethernet
connected for internet. No code changes needed; this is a Pi OS configuration.

---

## Storage

### SD card selection

Use **SanDisk Endurance** or **Samsung Pro Endurance** microSD cards. Standard
consumer cards are rated for ~1,000–10,000 write cycles. Endurance cards are
rated for ~100,000 write cycles and are designed for always-on embedded
applications (dashcams, security cameras). Cost difference is ~$2–3 wholesale.

**Recommended: 16 GB SanDisk Endurance.**

### Capacity projections

- 980 cards currently at 26 KB/card (AVIF format from Riot's CDN) = **25.5 MB**
- Growth rate: ~250 cards per set × 4 sets/year = **~1,000 cards/year**

| Year | Total cards | Image storage | Full device footprint |
|---|---|---|---|
| Now | 980 | 25.5 MB | ~3.5 GB |
| Year 1 | 1,980 | 51.5 MB | ~3.6 GB |
| Year 3 | 3,980 | 103 MB | ~3.7 GB |
| Year 5 | 5,980 | 155 MB | ~3.8 GB |
| Year 10 | 10,980 | 285 MB | ~4.1 GB |

16 GB provides ~4× headroom after a decade of card releases. Card images are
genuinely small in AVIF format.

---

## API Key & Backend Security

### The problem with key-per-device

Storing the Riot API key directly on each Pi's `.env` file is acceptable for
your own prototype but has serious problems for a shipped product:

- Anyone who removes and mounts the SD card can read the key in plain text
- Revoking or rotating the key requires reflashing every device
- You have no visibility into which devices are making API calls
- 100 devices = 100 copies of your API key in the wild

### Target architecture: backend proxy

You operate one small backend server. The Riot API key **never leaves this
server**.

```
Pi device  ──→  YOUR backend  ──→  Riot API
               (key lives here)
                      │
               caches card images
                      │
               per-device auth
```

**What lives where:**

| Data | Location |
|---|---|
| Riot API key | Backend environment variable only |
| Per-device UUID token | `.env` on each Pi (unique, revocable) |
| Cached card images | Backend object storage + Pi local disk |
| App code | GitHub (public) + installed on Pi |

### Per-device tokens

When you provision (flash) a new SD card, a script generates a UUID token,
writes it to the Pi's `.env`, and registers it with the backend. You can
revoke a token for any individual unit without affecting others.

### Recommended infrastructure

For 50–200 units with infrequent sync operations, the cost is effectively zero:

- **Cloudflare Workers** — serverless proxy functions (100k free requests/day)
- **Cloudflare R2** — object storage for cached card images ($0.015/GB; 25 MB
  of card images is free)
- No server to maintain; global CDN built-in

Alternative: a small FastAPI app on Railway or Fly.io (~$5/month free tier).

### Short-term (prototype / pre-launch)

Riot API key in `.env` on the Pi is acceptable while:
- You control all hardware
- Devices do not leave your hands
- You are iterating quickly

Switch to the backend proxy before shipping the first unit to a customer.

---

## OTA Updates

### Code updates via GitHub Releases

App code is distributed as tagged GitHub releases. The Pi runs a scheduled
check (e.g., nightly at 3am) that:

1. Calls `https://api.github.com/repos/nickorrnah/rift-tap/releases/latest`
2. Compares the tag to the installed version in `version.txt`
3. If newer: downloads the tarball, extracts it, runs a migration script,
   restarts the systemd service

This requires no credentials — the repo is public. The Pi never needs a
GitHub token.

**Deploy script location:** `deploy/update.sh` *(to be written)*

### Card library updates

Card images and metadata are updated separately from code, triggered manually
by the user via **Settings → Sync card library**.

In the backend proxy architecture:
- The backend polls the Riot API on a schedule for new cards
- Pi devices sync from the backend (no Riot API key on device)

In the interim (key-on-device) architecture:
- Pi calls Riot API directly
- Only missing images are downloaded (incremental)
- Requires temporary internet access on the Pi

The sync script is `scripts/sync_cards.py`. The API endpoint details are
placeholders pending receipt of the approved Riot API key and documentation.

### Update lifecycle

```
New set released
      │
      ▼
Riot API has new cards
      │
      ▼
YOUR backend syncs from Riot (automated, or manual trigger)
      │
      ▼
New card images cached in R2
      │
      ▼
Pi devices sync on next "Sync card library" press
      │
      ▼
New cards available for assignment
```

---

## Device Provisioning Workflow *(planned)*

The workflow for preparing a unit before shipping:

1. Flash Raspberry Pi OS Lite to 16 GB SanDisk Endurance card
2. Run `deploy/provision.sh` which:
   - Installs the Rift Tap app and Python dependencies
   - Configures USB gadget mode (`dwc2`, `g_cdc`)
   - Sets hostname to `rift-tap`
   - Enables `avahi-daemon` for mDNS
   - Generates a unique device UUID token
   - Registers the token with the backend
   - Writes the token to `.env`
   - Installs and enables the `rift-tap.service` systemd service
   - Runs a smoke test (server starts, LED blinks, USB gadget interface comes up)
3. Install the SD card into the Pi, attach the PN532 HAT
4. Test scan with a physical NFC tag
5. Package and ship

---

## Open Questions

- [ ] Riot API endpoint structure (pending API key approval)
- [ ] Exact card JSON field names from the Riot API response
- [ ] Whether Riot permits caching card images on a third-party CDN (check ToS)
- [ ] PN532 HAT size compatibility with Pi Zero 2W enclosure options
- [ ] Touchscreen HAT GPIO conflict check with PN532 HAT (for Pro model)
- [ ] Pricing strategy and target margin
- [ ] Packaging / unboxing experience
