"""An emoji that fits a wall item, in the wall's own format (Michael's idea #25).

The wall shows chores and routines with a named emoji: `czl_chores_emoji#_#paw_prints#_#🐾`
for a chore, `czl_routine_emoji#_#pill#_#💊` for a routine (Unicode's short name, snake
case). Themi picks one from the words of the title, from the household list in
`themi.drawing.emoji` (the first that fits, so more specific ones come first), with no
model call. It only ever replaces Themi's own plain defaults or no icon at all: an icon
the family chose stays.
"""

from __future__ import annotations

from themi.drawing.emoji import CHORE_ICON, ROUTINE_ICON
from themi.drawing.emoji import fit as _fit


def chore_icon(title: str) -> str:
    found = _fit(title)
    return f"czl_chores_emoji#_#{found[0]}#_#{found[1]}" if found else CHORE_ICON


def routine_icon(title: str) -> str:
    found = _fit(title)
    return f"czl_routine_emoji#_#{found[0]}#_#{found[1]}" if found else ROUTINE_ICON


def needs_icon(icon: str) -> bool:
    """None yet, or Themi's own plain default: one that fits can go in its place."""
    return icon in ("", CHORE_ICON, ROUTINE_ICON)


def better_icon(icon: str, fitting: str) -> bool:
    """Worth changing: the current one is none or Themi's default, and a real fit exists
    (not just the default again)."""
    return needs_icon(icon) and fitting != icon and fitting not in (CHORE_ICON, ROUTINE_ICON)
