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


# ----- matching what they said to a title (CR10b1: from events, which tasks share) -----


def name_key(text: str) -> str:
    """For comparing names: lowercase words, no punctuation."""
    return " ".join(re.sub(r"[^\w\s&'/-]", " ", text.lower()).split())


STOPWORDS = {"the", "a", "an", "my", "our", "to", "with", "for", "at", "on", "and", "of"}
FILLER = STOPWORDS | {"appointment", "appt", "event", "next", "this", "her", "his", "their"}
ENDINGS = ("ing", "ed", "es", "s")


# Bug #119: "I ran this morning" didn't name "Go for a run". Past forms that share no start.
IRREGULAR = {
    "ran": "run",
    "swam": "swim",
    "ate": "eat",
    "took": "take",
    "taken": "take",
    "fed": "feed",
    "made": "make",
    "did": "do",
    "done": "do",
    "bought": "buy",
    "drove": "drive",
    "driven": "drive",
    "rode": "ride",
    "wrote": "write",
    "gave": "give",
    "got": "get",
    "sent": "send",
    "brought": "bring",
    "paid": "pay",
    "threw": "throw",
    "thrown": "throw",
    "hung": "hang",
    "swept": "sweep",
    "sold": "sell",
    "told": "tell",
    "spoke": "speak",
    "met": "meet",
    "found": "find",
    "caught": "catch",
    "built": "build",
    "won": "win",
}


def _stem(word: str) -> str:
    """ "running" → "run", "walked" → "walk", "baking" → "bak" (with "bake" → "bak" too)."""
    if word in IRREGULAR:
        return _stem(IRREGULAR[word])
    for ending in ENDINGS:
        if ending == "s" and word.endswith("ss"):
            break  # "kiss", "glass"
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            word = word[: -len(ending)]
            if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "lsz":
                word = word[:-1]  # "running", "mopped"
            return word
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def _same_word(a: str, b: str) -> bool:
    """The same word, or one a form of the other ("tutoring" and "tutor", "pediatrics" and
    "pediatrician"): a shared start of five letters or more, most of the shorter word; or
    the same word under a regular ending or an irregular past ("walked", "ran") (bug #119)."""
    if a == b or _stem(a) == _stem(b):
        return True
    shared = next(
        (i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b))
    )
    return shared >= 5 and shared >= 0.6 * min(len(a), len(b))


def title_matches(words: str, title: str) -> bool:
    """Every word they used (bar fillers like "the" or "appointment") is in the title, give
    or take its ending (bug #20)."""
    wanted = [w for w in name_key(words).split() if w not in FILLER]
    have = name_key(title).split()
    return bool(wanted) and all(any(_same_word(w, h) for h in have) for w in wanted)


def near_twin(words: str, title: str) -> bool:
    """Most likely the same job under other words ("Refill cat feeders" and "Refill auto
    feeders", bug #132): two or more words in common, and every word of the longer title
    but one."""
    wanted = [w for w in name_key(words).split() if len(w) > 2 and w not in FILLER]
    have = [w for w in name_key(title).split() if len(w) > 2 and w not in FILLER]
    shared = sum(any(_same_word(w, h) for h in have) for w in wanted)
    return shared >= 2 and shared >= max(len(wanted), len(have)) - 1


def words_in_common(said: str, title: str) -> int:
    """How many of the title's words (bar fillers and scraps like "s") they used, give or
    take endings ("contacted" and "contact")."""
    heard = name_key(said).split()
    words = {w for w in name_key(title).split() if len(w) > 2 and w not in FILLER}
    return sum(any(_same_word(w, h) for h in heard) for w in words)
