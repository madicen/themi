"""Clear energy remarks, caught in code when the model didn't record them.

The model records energy remarks with `log_energy_note` and `log_energy_level`,
but not reliably (prompt 28's evals; the Shadow Calendar review found none of
Erin's "medium energy day" remarks). This is the backstop: a few unmistakable,
first-person patterns only, so a stray "I feel good about that plan" isn't read
as energy. It runs after a turn that recorded nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DAY_LEVEL = re.compile(r"\b(low|medium|mid|middling|moderate|high)[- ]energy\b", re.IGNORECASE)
_LEVELS = {"low": -1.0, "medium": 0.0, "mid": 0.0, "middling": 0.0, "moderate": 0.0, "high": 1.0}
_DRAIN = re.compile(
    r"\b(?:i'?m|i am|i feel|feeling|i'?ve got|i have)\b[^.!?]{0,25}?\b(?:exhausted|drained|"
    r"wiped(?: out)?|knackered|spent|burn(?:ed|t) out|running on empty|nothing left|fried)\b"
    r"|\btook (?:a lot|so much|everything) out of me\b",
    re.IGNORECASE,
)
_BOOST = re.compile(
    r"\b(?:i feel|i'?m feeling|feeling|i feel like)\s+(?:really |so |much |a lot )?(?:great|"
    r"refreshed|energi[sz]ed|human again|rested|good|recharged)\b(?!\s+about)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Remark:
    source: str  # "day_level" or "text_note"
    value: float
    words: str  # what was said, for the note


def energy_remark(text: str) -> Remark | None:
    """The clearest energy remark in `text`, if there is one."""
    if m := _DAY_LEVEL.search(text):
        return Remark("day_level", _LEVELS[m.group(1).lower()], m.group(0))
    if m := _DRAIN.search(text):
        return Remark("text_note", -2.0, m.group(0))
    if m := _BOOST.search(text):
        return Remark("text_note", 2.0, m.group(0))
    return None
