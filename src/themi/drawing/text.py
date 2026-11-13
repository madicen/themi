"""Measuring and fitting words for a drawing (DC1), from the bundled font's width table."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from themi.drawing import ASSETS

ELLIPSIS = "\u2026"
TRAILING = " ,.;:-\u2013\u2014"  # not left before an ellipsis (en and em dash too)


@cache
def _table() -> dict[str, Any]:
    return json.loads((ASSETS / "widths.json").read_text())


def text_width(text: str, size: float, bold: bool = False) -> float:
    """The width of `text` at `size` px in the bundled font (no kerning: a slight
    overestimate, which keeps fitted words inside their space)."""
    table = _table()["bold" if bold else "regular"]
    chars, fallback = table["chars"], table["fallback"]
    return sum(chars.get(ch, fallback) for ch in text) * size / table["units"]


def fit(text: str, size: float, width: float, bold: bool = False) -> str:
    """`text` as it fits in `width` px: whole, or cut at a word where it can be, with "…".
    Nothing fits: ""."""
    text = " ".join(text.split())
    if text_width(text, size, bold) <= width:
        return text
    room = width - text_width(ELLIPSIS, size, bold)
    if room <= 0:
        return ""
    cut = ""
    for ch in text:
        if text_width(cut + ch, size, bold) > room:
            break
        cut += ch
    word = cut.rsplit(" ", 1)[0] if " " in cut else cut
    if len(word) >= len(cut) * 0.6:  # don't lose more than 40% to end at a word
        cut = word
    cut = cut.rstrip(TRAILING)
    return cut + ELLIPSIS if cut else ""


def wrap(text: str, size: float, width: float, lines: int, bold: bool = False) -> list[str]:
    """`text` broken into at most `lines` lines that each fit in `width` px; the last one
    shortened with "…" when there's more."""
    words = text.split()
    out: list[str] = []
    while words and len(out) < lines:
        line = words.pop(0)
        while words and text_width(f"{line} {words[0]}", size, bold) <= width:
            line = f"{line} {words.pop(0)}"
        out.append(line)
    if out and words:
        out[-1] = f"{out[-1]} {' '.join(words)}"  # cut below, with "…"
    return [line for line in (fit(x, size, width, bold) for x in out) if line]
