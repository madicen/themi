"""F59g (Michael's idea #257): talk to Themi from the wall, typed or said.

The frame is shared, so the sheet first asks who's talking ("Who's this?", each person's
chip); the choice is kept for TALK_KEEP of use on that frame. A typed line goes in as that
person's own message to Themi (`InboundEvent` with `from_page=True`, as the cook screen's Ask
Themi, CK5), so it does everything a Telegram message does: the same agent, trust tiers and
outbox. A said one goes in as a voice note, which the agent transcribes as it does Telegram's
(through `router.transcribe`) and logs as what was heard. The answers go to Telegram as usual,
and the sheet shows the last few lines of that person's exchange today, from the message log.
Approval cards are answered in Telegram; the sheet says the card went there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from themi import clock
from themi.channels.events import InboundEvent, VoiceNote
from themi.localtime import member_day, member_day_start

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from themi.accounts import Member
    from themi.core.services import Services

TALK_KEEP = timedelta(minutes=5)  # who's talking, kept this long after the last use
LINES_SHOWN = 10
MAX_TEXT = 4000
MAX_AUDIO = 2_000_000  # about 30 s of compressed speech, with room to spare
LINE_SHOWN = 400  # a long message (the morning one), shortened in the sheet


@dataclass(frozen=True)
class TalkLine:
    mine: bool  # what they said (or Themi heard), else Themi's
    text: str
    card: bool = False  # an approval card: answered in Telegram


class Talking:
    """Who's talking on each frame (or phone), by its CSRF token: kept TALK_KEEP after its
    last use."""

    def __init__(self) -> None:
        self._who: dict[str, tuple[int, datetime]] = {}

    def who(self, viewer: str) -> int | None:
        found = self._who.get(viewer)
        if found is None or clock.now() - found[1] > TALK_KEEP:
            self._who.pop(viewer, None)
            return None
        return found[0]

    def keep(self, viewer: str, member_id: int) -> None:
        self._who[viewer] = (member_id, clock.now())

    def forget(self, viewer: str) -> None:
        self._who.pop(viewer, None)


def lines(services: Services, member: Member, tz: ZoneInfo) -> tuple[TalkLine, ...]:
    """The last LINES_SHOWN lines of their exchange with Themi today (their day: F34j)."""
    since = member_day_start(member, member_day(member, clock.now(), tz), tz)
    found = [
        m
        for m in services.store.recent_messages(member.id, LINES_SHOWN * 3)
        if m.created_at >= since and m.text.strip()
    ]
    out = []
    for m in found[-LINES_SHOWN:]:
        text = m.text if len(m.text) <= LINE_SHOWN else m.text[: LINE_SHOWN - 1].rstrip() + "…"
        out.append(TalkLine(m.direction == "in", text, card=m.kind == "approval"))
    return tuple(out)


def typed(services: Services, member: Member, text: str) -> InboundEvent | None:
    """A typed line, as their own message to Themi; None for nothing typed or someone Themi
    can't answer."""
    text = " ".join(text.split())[:MAX_TEXT]
    if not text or not member.reachable:
        return None
    services.store.log_message(member.id, "in", text, "wall", None)
    return InboundEvent(
        "text", member, member.telegram_user_id or 0, None, clock.now(), 0, text=text,
        from_page=True,
    )  # fmt: skip


def said(member: Member, audio: bytes, mime_type: str) -> InboundEvent | None:
    """A clip from the wall's mic, as a voice note: the agent transcribes it."""
    if not audio or len(audio) > MAX_AUDIO or not member.reachable:
        return None
    note = VoiceNote(audio, mime_type.split(";")[0].strip() or "audio/webm", 0)
    return InboundEvent(
        "voice", member, member.telegram_user_id or 0, None, clock.now(), 0, voice=note,
        from_page=True,
    )  # fmt: skip
