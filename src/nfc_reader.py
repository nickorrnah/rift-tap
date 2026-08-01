"""
nfc_reader.py — NTAG215 NFC reader with NDEF card-ID storage.

Architecture:
  The card ID (e.g. "OGN001") is written directly onto the NFC tag's user
  memory in a simple 4-byte-aligned format.  On scan the reader extracts the
  card ID from the tag and returns it — no UID-to-card database mapping needed.

  This means a tagged sleeve works on any Rift Tap device without reconfiguration.

Tag memory format (NTAG215 user memory starts at page/block 4):
  Block 4:  magic bytes b'RT01'  (Rift Tap format version 1)
  Block 5+: card ID as UTF-8, null-terminated, zero-padded to 4-byte boundary

  Example — card ID "OGN001" (6 bytes):
    Block 4: 52 54 30 31   ("RT01")
    Block 5: 4F 47 4E 30   ("OGN0")
    Block 6: 30 31 00 00   ("01\x00\x00")

  A blank or foreign tag has no RT01 magic → card_id is None.

Hardware note (Pi 3 A+ / Zero 2W with PN532 HAT):
  The HAT plugs onto the 40-pin GPIO header.  Set the mode jumper on the HAT
  to I2C, then enable I2C via raspi-config before using this module.
  Verify the HAT is detected: i2cdetect -y 1  (should show address 0x24)
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from config import NFC_INTERFACE, SCAN_COOLDOWN_SECONDS, SIMULATE_NFC

log = logging.getLogger(__name__)

NDEF_MAGIC = b"RT01"   # 4-byte header written at block 4
MAX_CARD_ID_BYTES = 32 # card IDs are short; cap reads for safety


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class TagScan:
    """Result of a single NFC tag read."""
    uid:     str            # Factory UID (hex string, always present)
    card_id: Optional[str]  # Card ID from tag NDEF, or None if blank/foreign


# ── NDEF encoding helpers ─────────────────────────────────────────────────────

def encode_card_id(card_id: str) -> bytes:
    """
    Encode a card ID into the Rift Tap NTAG215 block format.

    Returns bytes padded to a 4-byte boundary, ready to be written
    starting at block 4.
    """
    payload = card_id.encode("utf-8") + b"\x00"  # null-terminated
    # Pad to 4-byte boundary
    while (len(payload) % 4) != 0:
        payload += b"\x00"
    return NDEF_MAGIC + payload


def decode_card_id(data: bytes) -> Optional[str]:
    """
    Decode a card ID from raw bytes read from the tag starting at block 4.

    Returns None if the data does not start with the RT01 magic header.
    """
    if len(data) < 8 or data[:4] != NDEF_MAGIC:
        return None
    payload = data[4:]
    # Extract null-terminated string
    null_pos = payload.find(b"\x00")
    if null_pos < 0:
        null_pos = MAX_CARD_ID_BYTES
    text = payload[:null_pos].decode("utf-8", errors="replace").strip()
    return text if text else None


# ── Abstract base ─────────────────────────────────────────────────────────────

class NFCReader(ABC):
    @abstractmethod
    async def scan_loop(self) -> AsyncIterator[TagScan]:
        """Yield a TagScan for each tag detection event."""
        ...

    @abstractmethod
    async def write_card_id(self, card_id: str) -> bool:
        """
        Write a card ID to the tag currently held in front of the reader.

        Returns True on success, False if no tag is present or write fails.
        Should complete within ~500 ms so callers can await it directly.
        """
        ...


# ── Simulated reader ──────────────────────────────────────────────────────────

# Simulated tag pool: uid → card_id.  write_card_id() updates this dict.
# Uses real card IDs from the first set so demo scans show actual cards.
_SIM_TAGS: dict[str, Optional[str]] = {
    "04:A2:91:7C:3B:12:80": "ogn-001",
    "04:B3:12:5D:4E:23:91": "ogn-013",
    "04:C4:33:6E:5F:34:A2": "ogn-027",
    "04:D5:54:7F:60:45:B3": "ogn-028",
    "04:E6:75:80:71:56:C4": "ogn-007",
}
_SIM_LAST_WRITTEN_UID: Optional[str] = None  # track which tag to "write" to


class SimulatedReader(NFCReader):
    """
    Fires fake tag scans every 5–10 seconds.
    Simulates pre-written NTAG215 tags (card_id is already on each tag).
    """

    async def scan_loop(self) -> AsyncIterator[TagScan]:
        log.info("Simulated NFC reader active — producing a fake scan every 5–10 s")
        while True:
            await asyncio.sleep(random.uniform(5, 10))
            uid     = random.choice(list(_SIM_TAGS.keys()))
            card_id = _SIM_TAGS.get(uid)
            log.debug("Simulated scan: uid=%s card_id=%s", uid, card_id)
            yield TagScan(uid=uid, card_id=card_id)

    async def write_card_id(self, card_id: str) -> bool:
        global _SIM_LAST_WRITTEN_UID
        # Simulate a write to the most recently scanned tag
        if _SIM_LAST_WRITTEN_UID:
            _SIM_TAGS[_SIM_LAST_WRITTEN_UID] = card_id
            log.info("Simulated write: uid=%s card_id=%s", _SIM_LAST_WRITTEN_UID, card_id)
            return True
        # If no recent scan, pick a random tag
        uid = random.choice(list(_SIM_TAGS.keys()))
        _SIM_TAGS[uid] = card_id
        log.info("Simulated write (no recent scan): uid=%s card_id=%s", uid, card_id)
        return True


# ── Real PN532 reader ─────────────────────────────────────────────────────────

class PN532Reader(NFCReader):
    """
    Reads NTAG215 tags via the Adafruit CircuitPython PN532 library.

    Requires (uncomment in requirements.txt before use on the Pi):
      adafruit-circuitpython-pn532
      RPi.GPIO
      spidev  (for SPI) or smbus2 (for I2C)
    """

    # How many 4-byte blocks to read for the card ID (magic + up to 32 chars)
    _READ_BLOCKS = 10   # 40 bytes — plenty for any card ID

    def __init__(self, interface: str = NFC_INTERFACE):
        self._interface = interface.upper()
        self._pn532 = self._init_hardware()
        self._last_uid_bytes: Optional[bytes] = None

    def _init_hardware(self):
        try:
            import board
            import busio
            import digitalio
            from adafruit_pn532.i2c  import PN532_I2C
            from adafruit_pn532.spi  import PN532_SPI
            from adafruit_pn532.uart import PN532_UART

            if self._interface == "I2C":
                i2c   = busio.I2C(board.SCL, board.SDA)
                pn532 = PN532_I2C(i2c, debug=False)
            elif self._interface == "SPI":
                spi   = busio.SPI(board.SCK, board.MOSI, board.MISO)
                cs    = digitalio.DigitalInOut(board.CE0)
                pn532 = PN532_SPI(spi, cs, debug=False)
            elif self._interface == "UART":
                uart  = busio.UART(board.TX, board.RX, baudrate=115200, timeout=100)
                pn532 = PN532_UART(uart, debug=False)
            else:
                raise ValueError(f"Unknown interface: {self._interface!r}")

            pn532.SAM_configuration()
            ic, ver, rev, _ = pn532.firmware_version
            log.info("PN532 firmware v%d.%d detected via %s", ver, rev, self._interface)
            return pn532

        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialise PN532 over {self._interface}. "
                "Check wiring and that I2C is enabled (raspi-config)."
            ) from exc

    def _uid_hex(self, uid_bytes: bytes) -> str:
        return ":".join(f"{b:02X}" for b in uid_bytes)

    def _read_tag_blocks(self, start_block: int, num_blocks: int) -> bytes:
        """Read consecutive 4-byte blocks and return concatenated bytes."""
        data = b""
        for block in range(start_block, start_block + num_blocks):
            chunk = self._pn532.ntag2xx_read_block(block)
            if chunk is None:
                break
            data += bytes(chunk)
        return data

    def _write_tag_blocks(self, start_block: int, data: bytes) -> bool:
        """Write data (must be multiple of 4 bytes) starting at start_block."""
        if len(data) % 4 != 0:
            raise ValueError("Data length must be a multiple of 4 bytes")
        for i, block in enumerate(range(start_block, start_block + len(data) // 4)):
            chunk = data[i * 4:(i + 1) * 4]
            if not self._pn532.ntag2xx_write_block(block, chunk):
                log.error("Write failed at block %d", block)
                return False
        return True

    async def scan_loop(self) -> AsyncIterator[TagScan]:
        log.info("PN532 reader active on %s", self._interface)
        last_card_id: Optional[str] = None
        last_scan_time: float = 0.0

        while True:
            uid_bytes: Optional[bytes] = await asyncio.get_event_loop().run_in_executor(
                None, self._pn532.read_passive_target, 0.5
            )

            if uid_bytes is None:
                # No tag in range — reset cooldown so removal + re-tap works
                last_card_id  = None
                last_scan_time = 0.0
                self._last_uid_bytes = None
                await asyncio.sleep(0.05)
                continue

            self._last_uid_bytes = uid_bytes
            uid = self._uid_hex(uid_bytes)

            # Read NDEF data from user memory (starts at block 4)
            raw   = self._read_tag_blocks(4, self._READ_BLOCKS)
            card_id = decode_card_id(raw) if raw else None

            now = time.monotonic()
            if card_id == last_card_id and (now - last_scan_time) < SCAN_COOLDOWN_SECONDS:
                await asyncio.sleep(0.05)
                continue

            last_card_id  = card_id
            last_scan_time = now
            log.info("Tag detected: uid=%s card_id=%s", uid, card_id)
            yield TagScan(uid=uid, card_id=card_id)

    async def write_card_id(self, card_id: str) -> bool:
        """
        Write a card ID to the tag currently in range.
        Must be called while the tag is held on the reader.
        """
        uid_bytes = self._last_uid_bytes
        if uid_bytes is None:
            log.warning("write_card_id: no tag currently in range")
            return False

        data = encode_card_id(card_id)
        log.info("Writing card_id=%s to tag %s (%d bytes)", card_id, self._uid_hex(uid_bytes), len(data))

        success = await asyncio.get_event_loop().run_in_executor(
            None, self._write_tag_blocks, 4, data
        )
        if success:
            log.info("Write successful")
        return success


# ── Factory ───────────────────────────────────────────────────────────────────

def create_reader() -> NFCReader:
    if SIMULATE_NFC:
        return SimulatedReader()
    return PN532Reader()
