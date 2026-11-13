"""Write the drawings' font width table (DC1): `src/themi/drawing/assets/widths.json`.

Drawings fit their words to boxes before the SVG is written (SVG doesn't wrap or measure
text), so the width of each character of the bundled font is kept in a small table. This
reads it from the font files once, at dev time; the app only reads the table, so fontTools
isn't a run-time dependency.

Usage: python -m tools.dev.font_widths   (needs fontTools: pip install -e '.[dev]')
"""

from __future__ import annotations

import json
from pathlib import Path

from fontTools.ttLib import TTFont

ASSETS = Path(__file__).resolve().parents[2] / "src" / "themi" / "drawing" / "assets"
FONTS = {
    "regular": "AtkinsonHyperlegible-Regular.ttf",
    "bold": "AtkinsonHyperlegible-Bold.ttf",
}
EMOJI = "TwemojiMozilla.ttf"  # DC12: what resvg falls back to for emoji
# Basic Latin, Latin-1, and the punctuation Themi writes: ellipsis, bullet, middle dot,
# degree, en and em dash, curly quotes, times, arrow.
EXTRA = [
    chr(c)
    for c in (
        0x2026,
        0x2022,
        0xB7,
        0xB0,
        0x2013,
        0x2014,
        0x2018,
        0x2019,
        0x201C,
        0x201D,
        0xD7,
        0x2192,
    )
]
CHARS = [chr(c) for c in range(0x20, 0x7F)] + [chr(c) for c in range(0xA0, 0x100)] + EXTRA


def widths(path: Path) -> dict[str, object]:
    font = TTFont(path)
    units = font["head"].unitsPerEm  # type: ignore[attr-defined]
    cmap = font.getBestCmap() or {}
    metrics = font["hmtx"].metrics  # type: ignore[attr-defined]
    table = {ch: metrics[cmap[ord(ch)]][0] for ch in CHARS if ord(ch) in cmap}
    lower = [table[c] for c in "abcdefghijklmnopqrstuvwxyz"]
    return {
        "units": units,
        "fallback": round(sum(lower) / len(lower)),  # a character the table doesn't have
        "chars": table,
    }


def emoji_ranges(path: Path) -> list[list[int]]:
    """The emoji font's characters, as runs [first, last] (each one em wide; DC12)."""
    points = sorted((TTFont(path).getBestCmap() or {}).keys())
    runs: list[list[int]] = []
    for point in points:
        if point < 0x2000:
            continue  # letters and punctuation: Atkinson's
        if runs and point == runs[-1][1] + 1:
            runs[-1][1] = point
        else:
            runs.append([point, point])
    return runs


def main() -> None:
    table: dict[str, object] = {
        weight: widths(ASSETS / "fonts" / name) for weight, name in FONTS.items()
    }
    table["emoji"] = emoji_ranges(ASSETS / "fonts" / EMOJI)
    out = ASSETS / "widths.json"
    out.write_text(json.dumps(table, ensure_ascii=False, sort_keys=True, indent=0) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
