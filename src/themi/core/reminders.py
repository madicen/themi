"""Reminders that follow how much a task matters (C2c; the family's decision, 2026-10-26).

- End of day: two hours before a person's quiet hours start, one message lists
  what's due today and still open, low-importance ones left out. Nothing open,
  nothing sent.
- Overdue: a task whose due date has passed is raised again on a rhythm set by
  its importance (high every day, normal every other day, low every week), and
  each time more specifically:
    1. "Overdue: Clean the kitchen, due Wednesday."
    2. ...and the smallest version of it (its lightest step).
    3. ...and a moment that looks lighter, and an offer to move it or hand it on.
  Never more demanding, only more concrete (the plan's PDA rules). Chores whose
  missed rounds roll on or move to the next day, and deadline chores, move by
  themselves instead.

Importance is set with `set_task_importance`; medicine-like chores from the
wall start as high.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound
from themi.channels.outbox import Priority
from themi.core.groceries import and_list
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard
from themi.core.tools import ToolContext, ToolFailed, tool

log = logging.getLogger(__name__)

IMPORTANCE = ("low", "normal", "high")
CADENCE = {"high": 1, "normal": 2, "low": 7}  # days between overdue reminders
DAY_END_BEFORE_QUIET = timedelta(hours=2)
DAY_END_TEXT = "Still open today: {items}. Done any of them already? Tomorrow's fine too."
MEDICINE = re.compile(
    r"\b(?:pills?|meds?|medicine|medication|drops|cream|tabs?|insulin|dose)\b", re.IGNORECASE
)
_TAG = re.compile(r"^\((?:low|medium|high|optional[^)]*)\)\s*", re.IGNORECASE)


def _day_words(due: date, today: date) -> str:
    days = (today - due).days
    if days == 1:
        return "yesterday"
    return f"{due:%A}" if days < 7 else f"{due.day} {due:%b}"


def _part_of_day(moment: datetime) -> str:
    return "morning" if moment.hour < 12 else "afternoon" if moment.hour < 17 else "evening"


class Reminders:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.tools.register(set_task_importance)

    # ----- the end of the day ---------------------------------------------------------------

    async def end_of_day(self) -> int:
        """Scheduler job (every 15 minutes): the end-of-day list, once per person per day."""
        sent = 0
        tz = self._tz()
        now = clock.now().astimezone(tz)
        for member in self.store.list_members():
            if member.telegram_user_id is None:
                continue
            quiet = self._quiet_starts(member, now)
            if not quiet - DAY_END_BEFORE_QUIET <= now < quiet:
                continue
            today = now.date()
            if self.db.one(
                "SELECT 1 FROM day_end_sent WHERE member_id = ? AND day = ?",
                (member.id, today.isoformat()),
            ):
                continue
            self.db.execute(
                "INSERT INTO day_end_sent (member_id, day) VALUES (?, ?)",
                (member.id, today.isoformat()),
            )
            left = [
                t.title
                for t in self.board.open_for(member)
                if today in self.board.round_days(t)  # Sunday, for a Saturday-or-Sunday round
                and t.importance != "low"
                and not self.board.held(t, member)
            ]
            if not left:
                continue
            await self.services.outbox.send(
                member,
                DAY_END_TEXT.format(items=and_list(left)),
                priority=Priority.NORMAL,
                kind="task_summary",  # not a nudge, so it doesn't wait its turn (idea #11)
                deadline=quiet - timedelta(minutes=15),
                dedupe_key=f"day-end-{today}",
            )
            sent += 1
        return sent

    def _quiet_starts(self, member: Member, now: datetime) -> datetime:
        at = member.quiet_start
        start = datetime(now.year, now.month, now.day, at.hour, at.minute, tzinfo=now.tzinfo)
        # Quiet hours that start after midnight belong to tonight, not this morning.
        return start + timedelta(days=1) if member.quiet_start < time(12) else start

    # ----- overdue --------------------------------------------------------------------------

    async def overdue(self) -> int:
        """Scheduler job (hourly): overdue tasks raised again, by importance, more specific
        each time. Returns how many were raised."""
        today = clock.now().astimezone(self._tz()).date()
        raised = 0
        for row in self.db.query(
            "SELECT * FROM tasks WHERE status = 'open' AND due_on IS NOT NULL AND due_on < ?",
            (today.isoformat(),),
        ):
            task = self.board.get(row["id"])
            if task.due_on is None or self._moves_by_itself(task):
                continue
            if (self.board.round_end(task) or task.due_on) >= today:
                continue  # an either-day round's second day is still on time
            last = row["overdue_reminded_on"]
            if last and (today - date.fromisoformat(last)).days < CADENCE[task.importance]:
                continue
            if self._nudged_today(row, today):
                continue  # a chore's own "overdue after N days" nudge went today
            stage = row["overdue_reminders"] + 1
            lead = self._lead(task, stage, today)
            people: list[Member | None] = (
                [m for m in self.store.list_members() if m.telegram_user_id is not None]
                if task.shared
                else [self._doer(task)]
            )
            people = [p for p in people if p is None or not self.board.held(task, p)]
            if not people:
                continue  # waiting its turn for the chart (C2d): raised once it comes up
            for person in people:
                await self.board.prompt(task, member=person, lead=lead)
            self.db.execute(
                "UPDATE tasks SET overdue_reminders = ?, overdue_reminded_on = ? WHERE id = ?",
                (stage, today.isoformat(), task.id),
            )
            raised += 1
        return raised

    def _doer(self, task: Task) -> Member | None:
        return self.store.get_member(task.assignee) if task.assignee is not None else None

    @staticmethod
    def _moves_by_itself(task: Task) -> bool:
        """Missed rounds that roll on or move to the next day, and deadline chores, aren't
        overdue: they move."""
        if task.due_before_task is not None:
            return True
        return task.repeat is not None and task.missed in ("roll", "next_day")

    def _nudged_today(self, row: dict[str, Any], today: date) -> bool:
        stamp = row["overdue_notified_at"]
        return bool(stamp) and datetime.fromisoformat(stamp).astimezone(self._tz()).date() == today

    def _lead(self, task: Task, stage: int, today: date) -> str:
        assert task.due_on is not None
        lead = f"Overdue: {task.title}, due {_day_words(task.due_on, today)}"
        if stage == 1:
            return lead
        smallest = self._smallest(task)
        lead += f". The smallest version: {smallest}" if smallest else ". Even a few minutes counts"
        if stage == 2:
            return lead
        member = self.store.get_member(task.assignee) if task.assignee else None
        if member is not None:
            lead += f". {self._lighter_moment(member)}"
        other = next(
            (
                m.name
                for m in self.store.list_members()
                if m.telegram_user_id is not None and m.id != task.assignee
            ),
            None,
        )
        offer = f"I can move it, or ask {other} to take it" if other else "I can move it"
        return f"{lead}. {offer}"

    @staticmethod
    def _smallest(task: Task) -> str | None:
        """The lightest step: a (Low) one if the steps have levels, else the first that
        isn't optional."""
        steps = [s for s in task.steps if not s.casefold().startswith("(optional")]
        low = [s for s in steps if s.casefold().startswith("(low)")]
        chosen = (low or steps or [None])[0]
        return _TAG.sub("", chosen).rstrip(".") if chosen else None

    def _lighter_moment(self, member: Member) -> str:
        now = clock.now()
        moment = self.services.outbox.receptivity.not_before(member, Priority.LOW, now)
        moment = moment.astimezone(self._tz())
        if moment - now < timedelta(hours=1):
            return "Now looks like a good moment, if that helps"
        today = now.astimezone(self._tz()).date()
        day = (
            "This"
            if moment.date() == today
            else "Tomorrow"
            if moment.date() == today + timedelta(days=1)
            else f"{moment:%A}"
        )
        return f"{day} {_part_of_day(moment)} looks lighter, if that helps"

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


@tool(
    "set_task_importance",
    "How much a task matters, when someone says so ('the cat's meds really matter', 'the "
    "transfer can slide'): high, normal or low. Once overdue, high ones come up every day, "
    "normal every other day, low weekly; low ones stay off the end-of-day list.",
    {
        "task_id": {"type": "integer"},
        "importance": {"type": "string", "enum": list(IMPORTANCE)},
    },
)
async def set_task_importance(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = ctx.services.taskboard
    assert board is not None
    try:
        task = board.get(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if not board.can_edit(task, ctx.member):
        raise ToolFailed("That task isn't theirs to change.")
    ctx.services.store.db.execute(
        "UPDATE tasks SET importance = ? WHERE id = ?", (args["importance"], task.id)
    )
    log.info("Task %s importance: %s", task.id, args["importance"])
    return f"Task {task.id} ({task.title}) is now {args['importance']} importance."
