"""SVG to PNG with resvg (DC1).

resvg is given only the bundled fonts, never the system's, so the Pi and CI draw the same
pixels. It runs in a thread with a time limit; anything going wrong gives None (logged
once a day), and the caller sends words without the picture.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date

from themi import clock
from themi.drawing import ASSETS, FONT_FAMILY

log = logging.getLogger(__name__)

TIMEOUT = 5.0  # seconds; a card takes well under one on a Pi
FONT_FILES = sorted(str(p) for p in (ASSETS / "fonts").glob("*.ttf"))

Convert = Callable[[str, int | None], bytes]


def to_png(svg: str, width: int | None = None) -> bytes:
    """The PNG, at `width` px wide (the SVG's own size when None). Raises on a bad SVG."""
    import resvg_py  # here, so a machine without it still starts (and draws nothing)

    return bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg,
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
