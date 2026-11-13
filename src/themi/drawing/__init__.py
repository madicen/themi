"""Pictures drawn by code (DC1; the Themi Day Card Plan).

A drawing is data made into SVG by a Jinja2 template (`svg.py`), then into a PNG by resvg
(`render.py`), with the bundled font (Atkinson Hyperlegible) and weather icons (Meteocons)
in `assets/`. No picture model and no network: the same data always gives the same
picture, and the SVG is text that tests keep as golden files.

- Words in a drawing come from calendars, email and recipes: external text. Templates are
  autoescaped and their output is cleaned of characters XML can't hold, so a title is only
  ever words; no template takes an `href` from data (icons are the bundled files, as data
  URIs).
- SVG doesn't measure or wrap text, so words are fitted to their space first (`text.py`),
  from a width table of the bundled font (`assets/widths.json`, made by
  `tools/dev/font_widths.py`).
- Rendering runs off the event loop with a time limit; a failure gives None and the
  message goes as text.
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
TEMPLATES = Path(__file__).parent / "templates"
FONT_FAMILY = "Atkinson Hyperlegible"
