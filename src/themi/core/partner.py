"""Who a message is about: the person saying it, or their partner (bug #126).

Michael wrote "Erin is absolutely overwhelmed right now", then "What's on her plate?", and
got his own day pared down and his own day listed, three times. A message is about the
partner when it names them (their name, "my wife", "she", "him"...) and the nearest such
word before what it says is theirs, not "I" or "me": "I'm worried she's overwhelmed" is
about her, "I'm overwhelmed with Erin's stuff" is about the speaker.
"""

from __future__ import annotations

import re

from themi.accounts import Member

PARTNER_WORDS = r"wife|husband|partner|she|she's|her|hers|herself|he|he's|him|his|himself"
FIRST_PERSON = re.compile(r"\b(?:i|i'm|im|i've|i'd|i'll|me|myself)\b")
SENTENCE_END = re.compile(r"[.!?\n]")


def _plain(text: str) -> str:
    return text.lower().replace("\u2019", "'")  # phones send a curly apostrophe


def _others(members: list[Member], member: Member) -> list[Member]:
    return [m for m in members if m.id != member.id]


def _partner_pattern(others: list[Member]) -> re.Pattern[str] | None:
    names = [re.escape(m.name.lower()) for m in others if m.name]
    alternatives = names + ([PARTNER_WORDS] if len(others) == 1 else [])
    if not alternatives:
        return None
    return re.compile(rf"\b(?:{'|'.join(alternatives)})(?:'s)?\b")


def named(text: str, member: Member, members: list[Member]) -> Member | None:
    """The other person the message names: by name, or (with only one other person) by
    "she", "my husband"... None when it names nobody else."""
    said, others = _plain(text), _others(members, member)
    for other in others:
        if other.name and re.search(rf"\b{re.escape(other.name.lower())}\b", said):
            return other
    pattern = _partner_pattern(others)
    if len(others) == 1 and pattern is not None and pattern.search(said):
        return others[0]
    return None


def about_partner_at(text: str, at: int, member: Member, members: list[Member]) -> bool:
    """Whether what's said at `at` (a position in `text`) is about the partner: the
    nearest subject before it in its sentence is theirs rather than the speaker's."""
    said = _plain(text)
    pattern = _partner_pattern(_others(members, member))
    if pattern is None:
        return False
    start = max((m.end() for m in SENTENCE_END.finditer(said, 0, at)), default=0)
    before = said[start:at]
    theirs = max((m.start() for m in pattern.finditer(before)), default=-1)
    mine = max((m.start() for m in FIRST_PERSON.finditer(before)), default=-1)
    return theirs > mine


def about_partner(text: str, member: Member, members: list[Member]) -> bool:
    """The whole message is about the partner: it names them and never says I or me
    ("Erin is at zero energy")."""
    return named(text, member, members) is not None and not FIRST_PERSON.search(_plain(text))
