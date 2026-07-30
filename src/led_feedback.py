"""
led_feedback.py — Blink the Pi's built-in ACT LED on card scan events.

The green ACT LED is the only output available on the Pi Zero 2W without
attaching additional hardware.  On the Pi 3B/4 it works the same way.

LED sysfs paths:
  Pi Zero 2W / Pi 3B: /sys/class/leds/ACT/
  Some Pi 4 revisions: /sys/class/leds/led0/

The LED normally blinks on SD card activity (trigger = "mmc0").  We
temporarily take control, blink it, then restore the default trigger so
it goes back to behaving normally.

This module is a no-op on non-Pi systems — if the sysfs path doesn't
exist, all functions silently do nothing.  That means the rest of the
code can call blink() freely without checking whether it's running on
a Pi.
"""

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Try both known paths; some Pi revisions use led0, others use ACT.
_LED_PATHS = [
    Path("/sys/class/leds/ACT"),
    Path("/sys/class/leds/led0"),
]

def _find_led() -> Path | None:
    for p in _LED_PATHS:
        if p.exists():
            return p
    return None

LED_PATH = _find_led()

if LED_PATH:
    log.info("LED feedback available at %s", LED_PATH)
else:
    log.info("No controllable LED found — running without scan feedback")


def _write(filename: str, value: str) -> None:
    """Write to a sysfs LED file, ignoring errors gracefully."""
    if LED_PATH is None:
        return
    try:
        (LED_PATH / filename).write_text(value)
    except OSError:
        pass  # permissions or hardware not available


async def blink(times: int = 2, on_ms: int = 80, off_ms: int = 80) -> None:
    """
    Blink the ACT LED `times` times asynchronously.

    Default: 2 quick blinks — distinct enough to notice, fast enough
    not to be annoying on rapid scans.

    Args:
        times:  Number of blink cycles.
        on_ms:  Milliseconds LED stays on per cycle.
        off_ms: Milliseconds LED stays off per cycle.
    """
    if LED_PATH is None:
        return

    _write("trigger", "none")  # take manual control
    try:
        for _ in range(times):
            _write("brightness", "1")
            await asyncio.sleep(on_ms / 1000)
            _write("brightness", "0")
            await asyncio.sleep(off_ms / 1000)
    finally:
        _write("trigger", "mmc0")  # restore default SD activity trigger


async def blink_success() -> None:
    """Two quick blinks — card recognised and found in database."""
    await blink(times=2, on_ms=80, off_ms=80)


async def blink_unknown() -> None:
    """One long pulse — tag scanned but not assigned to a card yet."""
    await blink(times=1, on_ms=400, off_ms=0)
