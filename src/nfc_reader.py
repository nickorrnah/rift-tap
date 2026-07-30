"""
nfc_reader.py — Abstraction layer for the PN532 NFC reader.

This file does something important: it separates the *hardware concern*
(talking to the PN532 chip) from the *application concern* (what to do
when a card is scanned).  The rest of the code only ever calls
`reader.read_uid()` — it does not care whether that UID came from real
hardware or a simulator.

This pattern is called "dependency inversion" and it pays off immediately:
you can build and test the whole overlay and database logic before the
hardware arrives.

── Hardware setup (PN532 NFC HAT) ───────────────────────────────────────────
  The HAT plugs directly onto the Pi's 40-pin GPIO header — no jumper wires
  needed.  Before powering on, set the interface jumper on the HAT:

    I2C  (default / recommended for this project)
      Waveshare HAT: short the I2C jumper pads, leave SPI/UART open.
      Pi side: enable I2C via `sudo raspi-config` → Interface Options → I2C.

    SPI  (faster, needs spidev)
      Short the SPI jumper pads instead.
      Pi side: enable SPI via `sudo raspi-config` → Interface Options → SPI.

  NFC tag notes:
    NTAG215 stickers are used (504 bytes user memory).  Only the 7-byte
    factory UID is read by this software — the extra memory is available
    for future use (e.g. writing a URL for a phone-tap feature).
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from config import NFC_INTERFACE, SCAN_COOLDOWN_SECONDS, SIMULATE_NFC

log = logging.getLogger(__name__)


# ── Abstract base ─────────────────────────────────────────────────────────────
# Defining an interface (abstract class) means the server only depends on
# "something that yields UIDs", never on the specific implementation.

class NFCReader(ABC):
    @abstractmethod
    async def scan_loop(self) -> AsyncIterator[str]:
        """
        Yields raw NFC UIDs as hex strings (e.g. "04:A2:91:7C:3B:12:80").
        This is an async generator — the `await asyncio.sleep` inside lets
        other coroutines run between polls, which is essential on a Pi where
        the NFC poll itself can block for tens of milliseconds.
        """
        ...


# ── Simulated reader ──────────────────────────────────────────────────────────

# A pool of fake UIDs that map to your seeded test cards (see seed_db.py).
_SIMULATED_UIDS = [
    "04:A2:91:7C:3B:12:80",
    "04:B3:12:5D:4E:23:91",
    "04:C4:33:6E:5F:34:A2",
    "04:D5:54:7F:60:45:B3",
    "04:E6:75:80:71:56:C4",
]

class SimulatedReader(NFCReader):
    """
    Fires a random fake scan every 5–10 seconds.

    Set SIMULATE_NFC=true in your environment (it defaults to true in
    config.py) to use this instead of real hardware.
    """

    async def scan_loop(self) -> AsyncIterator[str]:
        log.info("Simulated NFC reader active — producing a fake scan every 5–10 s")
        while True:
            await asyncio.sleep(random.uniform(5, 10))
            uid = random.choice(_SIMULATED_UIDS)
            log.debug("Simulated scan: %s", uid)
            yield uid


# ── Real PN532 reader ─────────────────────────────────────────────────────────

class PN532Reader(NFCReader):
    """
    Reads UIDs from a physical PN532 module via the Adafruit CircuitPython
    library.  Requires the following packages (see requirements.txt):
      adafruit-circuitpython-pn532
      RPi.GPIO
      spidev   (for SPI) OR smbus2 (for I2C)

    The Adafruit library handles the low-level SPI/I2C framing so you
    don't have to.  Underneath it's sending PN532 "host controller
    interface" (HCI) commands — see the PN532 user manual if you're curious.
    """

    def __init__(self, interface: str = NFC_INTERFACE):
        self._interface = interface.upper()
        self._pn532 = self._init_hardware()

    def _init_hardware(self):
        """
        Import and initialise the Adafruit PN532 driver.

        Imports are intentionally inside this method so the module can be
        imported on non-Pi machines without crashing (the GPIO libraries
        are Pi-only).
        """
        try:
            import board
            import busio
            from adafruit_pn532.spi import PN532_SPI
            from adafruit_pn532.i2c import PN532_I2C
            from adafruit_pn532.uart import PN532_UART
            import digitalio

            if self._interface == "SPI":
                spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
                cs  = digitalio.DigitalInOut(board.CE0)
                pn532 = PN532_SPI(spi, cs, debug=False)
            elif self._interface == "I2C":
                i2c = busio.I2C(board.SCL, board.SDA)
                pn532 = PN532_I2C(i2c, debug=False)
            elif self._interface == "UART":
                uart = busio.UART(board.TX, board.RX, baudrate=115200, timeout=100)
                pn532 = PN532_UART(uart, debug=False)
            else:
                raise ValueError(f"Unknown NFC interface: {self._interface!r}")

            pn532.SAM_configuration()  # puts the PN532 into "normal" mode
            ic, ver, rev, support = pn532.firmware_version
            log.info("PN532 firmware v%d.%d detected via %s", ver, rev, self._interface)
            return pn532

        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialise PN532 over {self._interface}. "
                "Check wiring and that the correct interface libraries are installed."
            ) from exc

    async def scan_loop(self) -> AsyncIterator[str]:
        log.info("PN532 reader active on %s", self._interface)
        last_uid: Optional[str] = None
        last_time: float = 0.0

        while True:
            # run_in_executor moves the blocking poll to a thread-pool worker
            # so the asyncio event loop stays responsive.
            uid_bytes: Optional[bytes] = await asyncio.get_event_loop().run_in_executor(
                None, self._pn532.read_passive_target, 0.5  # 0.5 s timeout
            )

            if uid_bytes is None:
                await asyncio.sleep(0.05)  # nothing in range; yield control briefly
                continue

            uid = ":".join(f"{b:02X}" for b in uid_bytes)
            now = time.monotonic()

            # Cooldown: ignore repeated reads of the same tag within the window.
            if uid == last_uid and (now - last_time) < SCAN_COOLDOWN_SECONDS:
                await asyncio.sleep(0.05)
                continue

            last_uid = uid
            last_time = now
            log.info("Tag detected: %s", uid)
            yield uid


# ── Factory function ──────────────────────────────────────────────────────────

def create_reader() -> NFCReader:
    """
    Returns the right reader based on configuration.

    Using a factory function means you can swap implementations by
    changing one environment variable instead of editing code.
    """
    if SIMULATE_NFC:
        return SimulatedReader()
    return PN532Reader()
