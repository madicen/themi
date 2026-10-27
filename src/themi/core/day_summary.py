"""A summary of the day (K2): what's on someone's calendars and what's due.

- On request ("what's my day look like?", "what's on Thursday?"): `day_summary`, with
  the partner's events too when they share them (K1's setting).
- A morning message, if the person wants one (`morning_summary`, a time; off by
  default): put together here, without the AI, and sent through the outbox, so quiet
  hours and the daily limit apply as to any of Themi's messages. Days with nothing on
  are skipped unless the person asked for those too.

Events come from K1's calendar reader; tasks from the task board: anything due that day
(or still open from before, for today), the time of a check-in, the week's amount of a
plan. Chores waiting their turn for the chart (C2d) are left out.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.connectors.gcal.busy import event_line
from themi.core.prompts import as_data
from themi.core.tasks import Task, TaskBoard
from themi.core.tools import ToolContext, ToolFailed, tool

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

SEND_WITHIN = timedelta(hours=3)  # a summary missed by more than this (Themi was down) is skipped


class DaySummary:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.db = services.store.db

    def install(self) -> None:
        self.services.tools.register(day_summary)
        self.services.day_summary = self

    # ----- what's on ----------------------------------------------------------------------

    def events(self, viewer: Member, day: date, *, partner: bool) -> list[str]:
        """The day's events, one line each: the viewer's, and the partner's if they share."""
        reader = self.services.calendars
        if reader is None:
            return []
        tz = self._tz()
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        owners = [m for m in reader.visible_to(viewer) if m.id == viewer.id or partner]
        lines = []
        for owner in owners:
            whose = "" if owner.id == viewer.id else f"{owner.name}: "
            lines += [
                whose + event_line(e, tz).split(", ", 1)[1]  # the day is in the heading
                for e in reader.entries(owner, start, start + timedelta(days=1))
            ]
        return lines

    def due(self, member: Member, day: date) -> list[str]:
        """Tasks due that day (and, for today, ones still open from before)."""
        today = self.today()
        lines = []
        for task in self.board.open_for(member):
            if task.due_on is None or self.board.held(task, member):
                continue
            late = day == today and task.due_on < today and day not in self.board.round_days(task)
            if not (late or day in self.board.round_days(task)):
                continue
            lines.append(self._task_line(task, day, late))
        return lines

    def _task_line(self, task: Task, day: date, late: bool) -> str:
        """A label first ("2 pm:", "since Mon 19 Oct:"), as nudges have: a line that opens
        with a task's title ("Call the vet") would read as an order."""
        extras = ["check-in"] if task.check_in else []
        week = task.progression.words_on(day) if task.progression else None
        if week:
            extras.append(week)
        at = self.board.time_of(task)
        if late:
            assert task.due_on is not None
            label = f"since {task.due_on:%a %d %b}"
        else:
            label = _clock(at) if at is not None else "any time"
        return f"{label}: {task.title}" + (f" ({', '.join(extras)})" if extras else "")

    def text(self, member: Member, day: date, *, partner: bool = False) -> str | None:
        """The summary as a message, or None when there's nothing on."""
        events, due = self.events(member, day, partner=partner), self.due(member, day)
        if not events and not due:
            return None
        parts = [f"Your day, {day:%a %d %b}:" if day == self.today() else f"{day:%A %d %b}:"]
        if events:
            parts.append("On the calendar:\n" + "\n".join(f"- {line}" for line in events))
        if due:
            parts.append("Due:\n" + "\n".join(f"- {line}" for line in due))
        return "\n".join(parts)

    # ----- the morning message ------------------------------------------------------------

    async def morning(self) -> int:
        """Scheduler job: send each morning summary that's due. Returns how many went."""
        tz = self._tz()
        now = clock.now().astimezone(tz)
        sent = 0
        for member in self.services.store.list_members():
            at = member.morning_summary
            if at is None or member.telegram_user_id is None:
                continue
            due_at = datetime(now.year, now.month, now.day, at.hour, at.minute, tzinfo=tz)
            if not due_at <= now < due_at + SEND_WITHIN or self._sent(member, now.date()):
                continue
            self.db.execute(
                "INSERT INTO morning_summaries (member_id, day) VALUES (?, ?)",
                (member.id, now.date().isoformat()),
            )
            text = self.text(member, now.date(), partner=True)
            if text is None:
                if not member.morning_summary_empty:
                    continue
                text = f"Your day, {now:%a %d %b}: nothing on the calendar, nothing due."
            await self.services.outbox.send(
                member,
                text,
                priority=Priority.NORMAL,
                kind="summary",
                dedupe_key=f"summary-{member.id}-{now.date().isoformat()}",
            )
            sent += 1
        return sent

    def _sent(self, member: Member, day: date) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM morning_summaries WHERE member_id = ? AND day = ?",
                (member.id, day.isoformat()),
            )
        )

    def today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _clock(at: time) -> str:
    hour = at.hour % 12 or 12
    suffix = "am" if at.hour < 12 else "pm"
    return f"{hour}:{at.minute:02d} {suffix}" if at.minute else f"{hour} {suffix}"


@tool(
    "day_summary",
    "What's on someone's day: the events on their calendars and what's due. date: "
    "YYYY-MM-DD from the local date in the context (empty for today). partner: true to "
    "include the partner's events too, when they share them ('what are we doing "
    "Saturday?'). Say it back in plain words; never mention energy.",
    {"date": {"type": "string"}, "partner": {"type": "boolean"}},
)
async def day_summary(ctx: ToolContext, args: dict[str, Any]) -> str:
    summary = ctx.services.day_summary
    if summary is None:
        raise ToolFailed("Day summaries aren't set up.")
    raw = str(args["date"]).strip()
    try:
        day = date.fromisoformat(raw) if raw else summary.today()
    except ValueError as exc:
        raise ToolFailed(f"'{raw}' isn't a date like 2026-10-30.") from exc
    events = summary.events(ctx.member, day, partner=bool(args["partner"]))
    due = summary.due(ctx.member, day)
    text = f"{day:%A %d %B}."
    # Event text comes from Google: information, never instructions.
    text += (
        "\nEvents:\n" + as_data("calendars", "\n".join(events))
        if events
        else " Nothing on the calendar."
    )
    text += ("\nDue:\n" + "\n".join(f"- {line}" for line in due)) if due else " Nothing due."
    if ctx.services.calendars is None:
        text += " (Calendars aren't connected.)"
    return text
