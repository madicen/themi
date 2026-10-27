"""An emoji that fits a wall item, in the wall's own format (Michael's idea #25).

The wall shows chores and routines with a named emoji: `czl_chores_emoji#_#paw_prints#_#🐾`
for a chore, `czl_routine_emoji#_#pill#_#💊` for a routine (Unicode's short name, snake
case). Themi picks one from the words of the title, from a household list below (the
first that fits, so more specific ones come first), with no model call. It only ever
replaces Themi's own plain defaults or no icon at all: an icon the family chose stays.
"""

from __future__ import annotations

import re

CHORE_ICON = "czl_chores_emoji#_#broom#_#🧹"  # Themi's default for a chore
ROUTINE_ICON = "routine_property_bed"  # and for a routine

# (words in the title, Unicode short name, emoji): the first that fits wins.
EMOJI: tuple[tuple[frozenset[str], str, str], ...] = tuple(
    (frozenset(words.split()), name, emoji)
    for words, name, emoji in (
        ("bird birds parrot cage", "parrot", "🦜"),
        ("cat cats litter kitty", "cat", "🐈"),
        ("dog dogs puppy", "dog", "🐕"),
        ("feeder feeders", "bowl_with_spoon", "🥣"),
        ("pill pills meds medicine medication vitamin vitamins dose", "pill", "💊"),
        ("bin bins trash garbage recycling rubbish compost", "wastebasket", "🗑️"),
        ("dishes dish dishwasher", "fork_and_knife_with_plate", "🍽️"),
        ("laundry washer dryer clothes fold folding", "basket", "🧺"),
        ("sheets bed beds pillow pillows", "bed", "🛏️"),
        ("bathroom toilet shower bath tub", "toilet", "🚽"),
        ("plant plants garden weeds lawn mow", "potted_plant", "🪴"),
        ("water", "droplet", "💧"),
        ("run running jog jogging", "person_running", "🏃"),
        ("exercise workout gym yoga stretch stretching", "person_lifting_weights", "🏋️"),
        ("tea coffee", "hot_beverage", "☕"),
        ("cook cooking dinner lunch breakfast meal bake baking", "cooking", "🍳"),
        ("grocery groceries shopping", "shopping_cart", "🛒"),
        ("car drive gas", "automobile", "🚗"),
        ("call phone", "telephone_receiver", "📞"),
        ("mail email letter package", "envelope", "✉️"),
        ("bill bills pay rent bank money tax taxes", "dollar_banknote", "💵"),
        ("teeth floss", "tooth", "🦷"),
        ("read reading book books library", "books", "📚"),
        ("clean cleaning vacuum sweep mop tidy dust", "broom", "🧹"),
    )
)


def _fit(title: str) -> tuple[str, str] | None:
    words = set(re.findall(r"[a-z]+", title.lower()))
    return next(((name, emoji) for keys, name, emoji in EMOJI if keys & words), None)


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
