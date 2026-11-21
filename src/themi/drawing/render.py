"""SVG to PNG with resvg (DC1).

resvg is given only the bundled fonts, never the system's, so the Pi and CI draw the same
pixels. Characters Atkinson lacks (F54: ⅓ ⅔ ⅛ …) are drawn from the bundled "Themi
Fractions", named on each one here, after the SVG is written. It runs in a thread with a
time limit; anything going wrong gives None (logged once a day), and the caller sends words
without the picture.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import date

from themi import clock
from themi.drawing import ASSETS, FALLBACK_CHARS, FALLBACK_FAMILY, FONT_FAMILY

log = logging.getLogger(__name__)

TIMEOUT = 5.0  # seconds; a card takes well under one on a Pi
FONT_FILES = sorted(str(p) for p in (ASSETS / "fonts").glob("*.ttf"))

Convert = Callable[[str, int | None], bytes]

_TEXT = re.compile(r">([^<]+)<")  # the words between tags (attributes are never touched)
_FALLBACK = re.compile("[" + "".join(sorted(FALLBACK_CHARS)) + "]")
_SPAN = f'<tspan font-family="{FALLBACK_FAMILY}">\\g<0></tspan>'


def with_fallback(svg: str) -> str:
    """`svg` with each character Atkinson lacks in a tspan naming the fallback font, so it
    keeps the text's weight (resvg's own fallback takes whichever weight it finds first)."""
    if not any(ch in svg for ch in FALLBACK_CHARS):
        return svg
    return _TEXT.sub(lambda m: ">" + _FALLBACK.sub(_SPAN, m.group(1)) + "<", svg)


def to_png(svg: str, width: int | None = None) -> bytes:
    """The PNG, at `width` px wide (the SVG's own size when None). Raises on a bad SVG."""
    import resvg_py  # here, so a machine without it still starts (and draws nothing)

    return bytes(
        resvg_py.svg_to_bytes(
            svg_string=with_fallback(svg),
            width=width,
            skip_system_fonts=True,
            font_files=FONT_FILES,
            font_family=FONT_FAMILY,
            sans_serif_family=FONT_FAMILY,
        )
    )


class Renderer:
    def __init__(self, convert: Convert = to_png, timeout: float = TIMEOUT) -> None:
        self.convert = convert
        self.timeout = timeout
        self._logged: date | None = None

    async def png(self, svg: str, width: int | None = None) -> bytes | None:
        """The PNG, or None when it can't be made in time."""
        try:
            data = await asyncio.wait_for(asyncio.to_thread(self.convert, svg, width), self.timeout)
        except Exception as exc:
            self._log(exc)
            return None
        if not data:
            self._log(ValueError("an empty picture"))
            return None
        return data

    def _log(self, exc: BaseException) -> None:
        today = clock.now().date()
        if self._logged != today:
            self._logged = today
            log.warning("A drawing couldn't be made, so words go alone: %r", exc)
