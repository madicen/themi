"""Replies sized to the message, and listening before problem-solving (F22e, Erin's ideas
#124 and #125).

- Size: a short, blunt message gets a short, matter-of-fact reply; a few sentences get
  about as many back. A line in the turn's context says which; after a short message, a
  closing "Anything else?" or "Let me know if..." is dropped from the reply.
- Listening: when someone shares how they feel and asks for nothing, the turn says to
  listen and validate, with no advice, plans or tasks; ideas come only after asking once
  ("Want ideas, or just to vent?") and hearing yes. `focus_now` won't run on such a
  message of more than one sentence: paring their day down is problem-solving too. Each
  person can turn this off (`listen_first`, on by default, like PDA shielding).
"""

from __future__ import annotations

import re

from themi.accounts import Member

SENTENCE_END = re.compile(r"[.!?]+(?:\s+|$)|\n+")
SHORT_WORDS = 8
FEELING = re.compile(
    r"\bi(?:'m|\u2019m| am)\s+(?:so\s+|really\s+|just\s+|feeling\s+|kind of\s+|pretty\s+)*"
    r"(?:stressed|sad|anxious|upset|frustrated|exhausted|drained|lonely|angry|hurt|worried|"
    r"scared|down|overwhelmed|struggling|miserable|burnt out|burned out|fed up)\b"
    r"|\bi feel\b|\bi(?:'ve|\u2019ve| have) been feeling\b|\bi just need(?:ed)? to vent\b"
    r"|\bi can(?:'t|\u2019t|not) stop (?:thinking|crying|worrying)\b",
    re.IGNORECASE,
)
ASKS = re.compile(
    r"\bwhat (?:should|can|do|could) (?:i|we) do\b|\bany (?:ideas|advice|tips|suggestions)\b"
    r"|\bhelp me\b|\bhow (?:do|can|should|could) (?:i|we)\b|\b(?:can|could|would) you\b"
    r"|\bplease\b|\bideas?\b|\badvice\b|\bpare\b|\bmove\b|\bsnooze\b|\bremind\b|\badd\b"
    r"|\bput me in\b|\bburnout mode\b",
    re.IGNORECASE,
)
SHORT_SIGNAL = (
    "their message is short and to the point: reply with one short, matter-of-fact line, "
    "nothing added"
)
LONG_SIGNAL = "their message is {n} sentences: reply at about that length, no longer"
LISTEN_SIGNAL = (
    "they're sharing how they feel and asking for nothing: listen. Validate what they said, "
    "at about the length they wrote; no advice, plans, tasks or tools (focus_now included). "
    "If ideas might help, end by asking once whether they'd like some or just want to be "
    "heard ('Want ideas, or just to vent?'); give ideas only once they say yes"
)
# A closing line that asks for more, after a short message (Erin, #124).
FILLER = re.compile(
    r"\s*(?:is there )?anything else[^.!?\n]*[.!?]+\s*$"
    r"|\s*let me know if[^.!?\n]*[.!?]+\s*$"
    r"|\s*(?:i'm |i am )?(?:always )?happy to help[^.!?\n]*[.!?]+\s*$",
    re.IGNORECASE,
)


def sentences(text: str) -> int:
    return len([s for s in SENTENCE_END.split(text.strip()) if s.strip()])


def short(text: str) -> bool:
    return len(text.split()) <= SHORT_WORDS and sentences(text) <= 1


def listening(text: str, member: Member) -> bool:
    """They're sharing a feeling and asking for nothing, and want to be heard first."""
    return member.listen_first and bool(FEELING.search(text)) and not ASKS.search(text)


def holds_off_solving(text: str, member: Member) -> bool:
    """Problem-solving (focus_now) waits to be asked about: a feeling shared at some length.
    "I'm so overwhelmed today" alone still gets a few things for now (O1a)."""
    return listening(text, member) and sentences(text) > 1


def signals(text: str, member: Member) -> list[str]:
    """The size line, and the listening one when it applies."""
    found = [LISTEN_SIGNAL] if holds_off_solving(text, member) else []
    n = sentences(text)
    if short(text):
        found.append(SHORT_SIGNAL)
    elif n >= 3:
        found.append(LONG_SIGNAL.format(n=n))
    return found


def trimmed(reply: str, said: str) -> str:
    """After a short message, the reply loses a closing "Anything else?" line."""
    if not short(said):
        return reply
    cut = FILLER.sub("", reply).rstrip()
    return cut or reply
