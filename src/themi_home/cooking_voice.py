"""Push-to-talk on the cook screen (CK8).

A large mic button, only where the browser has speech recognition and only once the person
has turned on "Voice on the cook screen" in Settings (Chrome sends the audio to Google to
recognise it, and the setting says so). One phrase per press; no always-listening voice.

The words heard go to the same handlers as a typed line (RC3's): "next", "back", "repeat",
"go to step 4", "add two minutes", "how long left", "cancel the timer". Anything else goes to
Ask Themi, as a question typed in the drawer would. Telegram voice notes work as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from themi import clock
from themi.accounts import Member
from themi.channels.events import InboundEvent

if TYPE_CHECKING:
    from themi_home.cooking import Cooking, Session

NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "twenty": 20, "thirty": 30, "a": 1, "an": 1,
}  # fmt: skip
NUMBER_WORDS = re.compile(
    r"\b(" + "|".join(k for k in NUMBERS if len(k) > 2) + r"|an?(?= (?:more )?minutes?\b))\b"
)
MAX_HEARD = 200


def plain(heard: str) -> str:
    """The words as a typed line: lower case, no end punctuation, numbers as digits
    ("Add two minutes." is "add 2 minutes"; "go to step four" is "go to step 4")."""
    said = " ".join(heard.lower().replace("\u2019", "'").strip().rstrip("!?.").split())
    said = NUMBER_WORDS.sub(lambda m: str(NUMBERS[m.group(1)]), said)
    return re.sub(r"\b(\d+) more minutes?\b", r"\1 minutes", said)


@dataclass(frozen=True)
class Heard:
    words: str  # what was heard, shown briefly under the button
    said: str = ""  # an answer the screen shows ("4 min left on step 3.")
    ask: bool = False  # not a cooking phrase: it goes to Ask Themi


async def say(cooking: Cooking, member: Member, session: Session, heard: str) -> Heard:
    """One phrase from the mic, into RC3's text handlers, else Ask Themi."""
    words = " ".join(heard.split())[:MAX_HEARD]
    phrase = plain(words)
    if not phrase:
        return Heard(words)
    event = InboundEvent(
        "text", member, member.telegram_user_id or 0, None, clock.now(), 0, text=phrase,
        in_group=session.in_group and session.member_id != member.id, from_page=True,
    )  # fmt: skip
    timers = cooking.timers
    said = ""
    if timers is not None:
        from themi_home.cooking_timers import LEFT

        if LEFT.match(phrase) and timers.running(cooking._owner(session)):
            said = timers.left_text(cooking._owner(session))
    if await cooking.on_text(event, member, phrase):
        return Heard(words, said)
    if timers is not None and await timers.on_text(event, member, phrase):
        return Heard(words, said)
    return Heard(words, ask=True)
