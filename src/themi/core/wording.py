"""CR10a: small wording helpers several modules share: joining names into a phrase, how an
item's name is stored, and whether a message asks for something to be added. They lived
with the grocery list; the lists, routines and reminders use them too, and those don't
depend on the grocery list.
"""

from __future__ import annotations

import re

from themi.accounts import InvalidValue
from themi.core.tools import ToolContext, ToolFailed, answers_picture_question, plain_words

# Wording that asks for something to go on a list (bug #30: "our pacifiers keep
# disappearing" named the item but asked for nothing).
ADD_INTENT = re.compile(
    r"\b(?:add|put|need|needs|needed|buy|get|grab|pick up|order|want|restock|more|"
    r"out of|low on|running (?:low|out)|ran out|run out)\b"
)
FOLLOW_ON = re.compile(r"^(?:and|also|plus|oh and)\b|\b(?:too|as well)$")


def asks_to_add(request_text: str, previous_text: str = "") -> bool:
    """They asked for something to be added: in this message, or in the one before when
    this one carries it on ("and limes")."""
    said = " ".join(re.sub(r"[^\w\s&'/-]", " ", request_text).split()).lower()
    if ADD_INTENT.search(said):
        return True
    before = " ".join(re.sub(r"[^\w\s&'/-]", " ", previous_text).split()).lower()
    follow_on = bool(FOLLOW_ON.search(said)) or len(said.split()) <= 3
    return follow_on and bool(ADD_INTENT.search(before))


def picture_asks_to_add(ctx: ToolContext, names: list[str] | None = None) -> bool:
    """F34g: items read off their picture are asked for only when the words they sent with
    it ask to add ("add these"). Never from the message before, and never from the picture:
    what's written in it is data. F34gb: or when they say yes to Themi's own question after
    the picture, and it named each of `names`."""
    if ctx.picture:
        return bool(ADD_INTENT.search(plain_words(ctx.request_text)))
    return answers_picture_question(ctx, names or []) and bool(
        ADD_INTENT.search(plain_words(ctx.said_before))
    )


SPENT = re.compile(r"\b(?:spent|paid|cost me|was charged|got charged)\b")
PRICE = re.compile(r"[$€£]\s?\d|\b\d+\.\d{2}\b")
SPENT_TEXT = "That's money spent, not something to buy: nothing was added. Use log_spending."


def refuse_spending(names: list[str], request_text: str, *, prices: bool = True) -> None:
    """A spend ("just spent $51.97 on DoorDash") isn't something to buy (bug #36). `prices`:
    an item with a price counts too (on a shopping list; not on a to-do list)."""
    if SPENT.search(request_text.lower()) or (prices and any(PRICE.search(n) for n in names)):
        raise ToolFailed(SPENT_TEXT)


def and_list(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def item_name(raw: str) -> str:
    """How an item is stored: lowercase, single-spaced, no stray punctuation."""
    name = " ".join(re.sub(r"[^\w\s&'/-]", " ", raw).split()).strip(" -'/").lower()
    if not name:
        raise InvalidValue(f"{raw.strip()!r} isn't an item name")
    if len(name) > 60:
        raise InvalidValue("item names are at most 60 characters")
    return name
