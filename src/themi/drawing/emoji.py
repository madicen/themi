"""An emoji for a household item, from the words of its title (Michael's idea #25), and
the emoji in a wall icon (F43b, idea #208: pictures show the emoji the wall shows).

The household list was the Cozyla pack's; it moved here so pictures can use it without
the pack. The wall keeps an icon as `czl_chores_emoji#_#paw_prints#_#🐾` (a chore) or
`czl_routine_emoji#_#pill#_#💊` (a routine); `routine_property_*` is one of its own
pictures, with no emoji.
"""

from __future__ import annotations

import re

CHORE_ICON = "czl_chores_emoji#_#broom#_#🧹"  # Themi's default for a chore
ROUTINE_ICON = "routine_property_bed"  # and for a routine
SEPARATOR = "#_#"

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


def fit(title: str) -> tuple[str, str] | None:
    words = set(re.findall(r"[a-z]+", title.lower()))
    return next(((name, emoji) for keys, name, emoji in EMOJI if keys & words), None)


def icon_emoji(icon: str) -> str:
    """The emoji in a wall icon, or "" when it has none."""
    parts = icon.split(SEPARATOR)
    return parts[2] if len(parts) == 3 and parts[0].endswith("_emoji") else ""


def item_emoji(title: str, icon: str = "") -> str:
    """The emoji a picture shows beside an item: the wall's icon when the family chose it,
    else one picked from the title, else none. Themi's own default stands only when nothing
    fits better (idea #25's rule)."""
    found = fit(title)
    if icon and icon not in (CHORE_ICON, ROUTINE_ICON) and (chosen := icon_emoji(icon)):
        return chosen
    if found:
        return found[1]
    return icon_emoji(icon) if icon == CHORE_ICON else ""
