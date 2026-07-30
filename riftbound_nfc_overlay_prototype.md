# Riftbound NFC Card Scanner Prototype

## Project Goal

Build a simple prototype that lets a player tap an NFC-tagged **Riftbound** card on a scanner and automatically display that card in an OBS stream overlay.

The first version will use a single scan area rather than a full NFC-enabled playmat. This keeps the hardware inexpensive and makes it easier to validate the concept before expanding into zone-based tracking.

## Core User Flow

1. Attach a thin NFC sticker or inlay to the back of each card sleeve.
2. Associate each NFC tag with a specific Riftbound card.
3. During play, tap the sleeved card on the NFC reader.
4. The Raspberry Pi reads the tag's unique identifier.
5. The software looks up the associated card.
6. A browser-based OBS overlay displays the card image and relevant information.

## Prototype Hardware

- Raspberry Pi 3
- PN532 NFC reader module
- Approximately 50 NTAG213 NFC stickers or thin inlays
- MicroSD card and power supply for the Raspberry Pi
- Jumper wires or the appropriate cable for connecting the PN532
- Existing card sleeves, preferably double sleeves

The NTAG213 stickers do not need to store the full card information. The prototype can use each tag's unique identifier as a database key.

## Attaching NFC Tags

The safest approach is to attach the NFC tag to the sleeve rather than the card.

For double-sleeved cards:

- Place the NFC sticker or inlay between the inner and outer sleeve.
- Keep the tag in the same position on every card.
- A bottom-center or upper-center position should make scanning consistent.
- Avoid folding or sharply bending the antenna.

For the prototype, thin adhesive NFC stickers are sufficient. Custom sleeves with embedded NFC inlays can be explored later.

## Card Assignment Workflow

The recommended approach is to avoid writing card data directly onto the NFC tag.

Instead:

1. Scan the tag.
2. Read its UID.
3. Search for or select the corresponding Riftbound card.
4. Save the UID-to-card mapping in a local database.

Example mapping:

```json
{
  "04:A2:91:7C:3B:12:80": "riftbound_card_00427"
}
```

This makes reassignment fast and avoids tag-writing errors.

### Admin Mode

A simple local web page can provide an assignment interface:

- Scan an unassigned tag.
- Display the detected UID.
- Search the card database by name.
- Select the correct card.
- Click **Assign**.
- Save the mapping.

A later version could import a deck list and guide the user through assigning tags in deck order.

## Software Architecture

```text
NFC Sticker
    ↓
PN532 NFC Reader
    ↓
Raspberry Pi 3
    ↓
Python NFC Service
    ↓
Local Web Server / WebSocket
    ↓
OBS Browser Source
```

### Raspberry Pi Service

A small Python application will:

- Read NFC tag UIDs from the PN532.
- Look up the UID in the card database.
- Send the matching card data to the overlay.
- Ignore repeated scans for a short cooldown period.

### Local Database

The prototype can begin with SQLite or JSON.

Suggested card fields:

- Internal card ID
- Card name
- Set
- Card number
- Type
- Cost
- Tags or traits
- Rules text
- Image filename
- NFC UID

SQLite is preferable once the admin interface is added.

## OBS Overlay

The easiest OBS integration is a **Browser Source**.

The overlay will be a local HTML, CSS, and JavaScript page served by the Raspberry Pi or another computer on the local network.

When a card is scanned:

1. The Python service sends the card data through a WebSocket.
2. The browser overlay receives the event.
3. The card image appears with a fade or slide animation.
4. The card remains visible for a configured duration.
5. The overlay hides automatically.

The overlay can later include:

- Card name
- Cost
- Type
- Rules text
- Player name
- Scan history
- Sound effects
- Different animations for different card types

## Card Image Storage

The text metadata for roughly 800 cards will be very small, likely only a few megabytes.

The images will determine most of the storage requirement.

Estimated local storage for 800 card images:

- WebP: approximately 80–200 MB
- JPEG: approximately 120–300 MB
- PNG: potentially much larger

A practical target is around **250 MB or less** for the entire card image library using well-compressed WebP or JPEG files.

This is small enough to store locally on the Raspberry Pi.

## Prototype Milestones

### Phase 1: Hardware Test

- Purchase the PN532 reader and NFC stickers.
- Connect the PN532 to the Raspberry Pi.
- Install the required Python libraries.
- Confirm that the Pi can read tag UIDs reliably.

### Phase 2: Basic Card Lookup

- Create a small test database with 5–10 cards.
- Map several NFC UIDs to card IDs.
- Print the matching card name when a tag is scanned.
- Add a cooldown to prevent duplicate reads.

### Phase 3: Basic OBS Overlay

- Create a local web page for the overlay.
- Add it to OBS as a Browser Source.
- Send scan events from Python to the page.
- Display the matching card image.
- Automatically hide the image after several seconds.

### Phase 4: Assignment Interface

- Build a simple admin page.
- Scan an unassigned NFC tag.
- Search the card database.
- Assign or reassign the tag.
- Store the mapping in SQLite.

### Phase 5: Full Card Library

- Import the complete Riftbound card list.
- Download or prepare optimized card images.
- Normalize filenames and card IDs.
- Add search, filters, and missing-image handling.

## Initial Purchase List

For the first prototype:

- One PN532 NFC reader module
- One 50-pack of NTAG213 NFC stickers or inlays
- Jumper wires or connection cable
- Card sleeves
- Raspberry Pi 3, already available

No ESP32 is required for the first version.

## Future Expansion

Once the single-reader prototype works, possible upgrades include:

- Multiple reader zones
- Separate scan areas for each player
- Battlefield or base tracking
- Automatic play-history logging
- Deck recognition
- Multiple OBS overlay layouts
- Remote control from a phone
- Custom sleeves with embedded NFC tags
- A purpose-built playmat with several reader coils

## Recommended MVP

The minimum viable prototype is:

- One Raspberry Pi 3
- One PN532 NFC reader
- Ten NFC-tagged sleeves
- Ten test card records
- One Python scanning service
- One local OBS browser overlay

The main success criterion is simple:

> Tapping a tagged Riftbound card causes the correct card image to appear in OBS quickly and reliably.
