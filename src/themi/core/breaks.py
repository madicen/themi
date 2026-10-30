"""Breaks (B1, Erin's idea #42): a rest mode that ends with a question.

"I'm taking a break", "rest for 30 minutes" or /break 30: until it's over, no task nudges
or check-ins (a "break" pause, so they wait in the outbox; nothing is dropped). What they
ask for still comes: replies, approvals and urgent alerts are never held. When the time is
up, one message: "Break's up" with [End break] and [Extend by N min], N being their own
setting (My settings, 15 by default); nudges wait for the answer, ten minutes at most.
"I'm back" ends it early.

Themi suggesting a break on its own (when the Shadow Calendar sees a long run of effort),
and breaks that bring a chosen set of prompts, are follow-ups.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

TOPIC = "break"
DEFAULT_MINUTES = 30
GRACE = timedelta(minutes=10)  # after "break's up", nudges wait this long for their answer
MAX_MINUTES = 8 * 60
STARTED_TEXT = "Enjoy the break. No task nudges or check-ins until {until}; I'll check in then."
UP_TEXT = "Break's up. Ready to carry on, or a little longer?"
ENDED_TEXT = "Welcome back."
EXTENDED_TEXT = "Longer it is: no task nudges or check-ins until {until}."
NO_BREAK_TEXT = "There's no break going on."


class Breaks:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.pauses = services.outbox.pauses

    def install(self) -> None:
        s = self.services
        s.breaks = self
        s.button_handlers["break"] = self.on_button
        s.add_command("/break", self.on_command, "Take a break: /break 30 (minutes)")
        for t in (start_break, end_break):
            s.tools.register(t)

    def current(self, member: Member) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM breaks WHERE member_id = ? AND ended_at IS NULL AND until > ? "
            "ORDER BY id DESC",
            (member.id, to_utc_iso(clock.now())),
        )

    async def start(self, member: Member, minutes: int) -> str:
        """Start a break, or move the end of the one going on."""
        if not 1 <= minutes <= MAX_MINUTES:
            raise ValueError(f"a break is between 1 minute and {MAX_MINUTES // 60} hours")
        until = await self._begin(member, minutes)
        return STARTED_TEXT.format(until=self._clock(until))

    async def _begin(self, member: Member, minutes: int) -> datetime:
        self._finish(member)
        now = clock.now()
        until = now + timedelta(minutes=minutes)
        pause = self.pauses.pause(member, TOPIC, until + GRACE)
        break_id = self.db.execute(
            "INSERT INTO breaks (member_id, pause_id, started_at, until) VALUES (?, ?, ?, ?)",
            (member.id, pause.id, to_utc_iso(now), to_utc_iso(until)),
        )
        extend = member.break_extend_minutes
        result = await self.services.outbox.send(
            member,
            UP_TEXT,
            priority=Priority.NORMAL,
            kind="break",
            not_before=until,
            deadline=until + timedelta(minutes=5),  # they asked for it: on time
            buttons=[
                Button("End break", "break", {"break": break_id, "action": "end"}),
                Button(f"Extend by {extend} min", "break", {"break": break_id, "action": "extend"}),
            ],
        )
        self.db.execute(
            "UPDATE breaks SET end_outbox_id = ? WHERE id = ?", (result.outbox_id, break_id)
        )
        return until

    def _finish(self, member: Member) -> bool:
        """End any break going on now: its pause, and its "break's up" if not sent yet."""
        rows = self.db.query(
            "SELECT * FROM breaks WHERE member_id = ? AND ended_at IS NULL", (member.id,)
        )
        now = to_utc_iso(clock.now())
        for row in rows:
            self.db.execute("UPDATE breaks SET ended_at = ? WHERE id = ?", (now, row["id"]))
            if row["end_outbox_id"]:
                self.services.outbox.cancel(row["end_outbox_id"])
        if self.pauses.resume(member, TOPIC):
            self.services.outbox.release_held(member)  # flush re-checks quiet hours, limits
        return any(datetime.fromisoformat(r["until"]) + GRACE > clock.now() for r in rows)

    def end(self, member: Member) -> str:
        return ENDED_TEXT if self._finish(member) else NO_BREAK_TEXT

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        member = self.store.get_member(event.member.id)
        row = self.db.one(
            "SELECT * FROM breaks WHERE id = ? AND member_id = ?",
            (int(event.button.payload["break"]), member.id),
        )
        if row is None:
            return
        if event.button.payload.get("action") == "extend":
            until = await self._begin(member, member.break_extend_minutes)
            text = EXTENDED_TEXT.format(until=self._clock(until))
        else:
            self._finish(member)
            text = ENDED_TEXT
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, text)

    async def on_command(self, member: Member, argument: str) -> None:
        try:
            minutes = int(argument) if argument.strip() else DEFAULT_MINUTES
            text = await self.start(member, minutes)
        except ValueError:
            text = "Try /break 30, for half an hour (up to 8 hours)."
        await self.services.outbox.send(member, text, priority=Priority.REPLY)

    def _clock(self, moment: datetime) -> str:
        family = self.store.get_family()
        local = moment.astimezone(ZoneInfo(family.timezone if family else "UTC"))
        hour = local.hour % 12 or 12
        suffix = "am" if local.hour < 12 else "pm"
        return f"{hour}:{local.minute:02d} {suffix}" if local.minute else f"{hour} {suffix}"


def _breaks(ctx: ToolContext) -> Breaks:
    breaks = ctx.services.breaks
    if breaks is None:
        raise ToolFailed("Breaks aren't set up.")
    return breaks


# P6: "don't send me anything tonight" is about Themi's messages (pause_messages), unless
# they also say they're resting (evals task-pause, twin-pause-tonight).
HOLD_MESSAGES = re.compile(
    r"\bdon'?t send me\b|\bstop (?:sending|messaging)\b|\bhold (?:my|the|off|all)\b"
)
RESTING = re.compile(r"\bbreak\b|\brest\b|\blie down\b|\bnap\b")


@tool(
    "start_break",
    "Start a break when they say they're taking one ('I'm taking a break', 'rest for 30 "
    "minutes', 'I need 20 minutes'): no task nudges or check-ins until it's over, then one "
    "message asks whether to end it or extend it. minutes: what they said, or 0 for the "
    "usual half hour. A break going on already gets the new end.",
    {"minutes": {"type": "integer"}},
)
async def start_break(ctx: ToolContext, args: dict[str, Any]) -> str:
    said = ctx.request_text.lower()
    if HOLD_MESSAGES.search(said) and not RESTING.search(said):
        raise ToolFailed(
            "Not started: they asked Themi to hold its messages, which is pause_messages, "
            "not a break."
        )
    minutes = int(args["minutes"]) or DEFAULT_MINUTES
    try:
        return await _breaks(ctx).start(ctx.member, minutes)
    except ValueError as exc:
        raise ToolFailed(f"Not started: {exc}.") from exc


@tool(
    "end_break",
    "End their break early when they say they're back ('I'm back', 'break's over').",
    {},
)
async def end_break(ctx: ToolContext, args: dict[str, Any]) -> str:
    text = _breaks(ctx).end(ctx.member)
    if text == NO_BREAK_TEXT:
        raise ToolDeclined(text)
    return text
