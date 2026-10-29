"""Time blocked on someone's calendar for a task (K5).

- "Block Saturday morning for the bathroom": an event on their calendar for the task
  (`block_time_for_task`; made at once when asked for in their words). "Find me time for
  the bathroom": Themi picks the first good window long enough (their calendar's busy
  times, busy times, quiet hours and the energy model's windows) and offers it as a card
  (`find_time_for_task`).
- While a block is coming, the task is held (`TaskBoard.holds`): no nudge, no end-of-day
  or overdue reminder. Its nudge comes as the block begins (`blocks.tick`, every 5 minutes).
- The block follows its event: moved on the calendar, the block and its nudge move; deleted,
  the block ends and nudging is as before.
- When a block ends with the task still open: one message, done or move the block? Not if
  the nudge that came as it began is still unanswered: that already asks.
- Blocks carry "task-block:<task>" (K1), so they're never busy time and never hold back
  Themi's own messages, including the task's nudge.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound
from themi.autonomy import ExecutionContext
from themi.channels.events import Button
from themi.channels.outbox import Priority
from themi.connectors.gcal.busy import TASK_BLOCK
from themi.core.events import OWN, When, parse_when, when_words
from themi.core.lists import name_key
from themi.core.tasks import Task, TaskBoard
from themi.core.tools import Proposal, ToolContext, ToolFailed, staged_tool
from themi.energy.model import EnergyModel
from themi.energy.windows import windows
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

EXECUTOR = "blocks.add"
ENDED_TEXT = "The time for {title} is over. Done, or move the block?"
INTENT = re.compile(r"\b(?:block|calendar|schedule|time for)\b")
# "Prompt me to run at 2" asks for a nudge then, not time on the calendar (bug #39).
NUDGE = re.compile(r"\b(?:prompt|remind|nudge|ping|check in with)\b")
MAX_DAYS = 14


class TaskBlocks:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.task_blocks = self
        s.autonomy.executors.register(EXECUTOR)(self._execute)
        s.tools.register(block_time_for_task)
        s.tools.register(find_time_for_task)
        self.board.holds.append(self.held)
        self.board.wall_notes.append(self.note)

    # ----- the hold -------------------------------------------------------------------------

    def held(self, task: Task, member: Member) -> bool:
        """A block for this task is coming: its nudges wait for it."""
        return self._coming(task.id, member.id) is not None

    def _coming(self, task_id: int, member_id: int) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM task_blocks WHERE task_id = ? AND member_id = ? AND removed_at IS NULL "
            "AND nudged = 0 AND starts_at > ? ORDER BY starts_at LIMIT 1",
            (task_id, member_id, to_utc_iso(clock.now())),
        )

    def note(self, task: Task) -> str | None:
        """For the model: when the task's time is blocked."""
        if task.assignee is None:
            return None
        row = self._coming(task.id, task.assignee)
        if row is None:
            return None
        when = When(
            datetime.fromisoformat(row["starts_at"]), datetime.fromisoformat(row["ends_at"]), False
        )
        return f"Time blocked for it on their calendar: {when_words(when, self._tz())}."

    # ----- making a block -------------------------------------------------------------------

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        events = self.services.events
        if events is None:
            return "Calendars aren't set up."
        task = self.board.get(int(payload["task_id"]))
        themi_id, text = await events.make(ctx.member, payload, ctx.idempotency_key)
        if not self.db.one("SELECT 1 FROM task_blocks WHERE themi_event_id = ?", (themi_id,)):
            self.db.execute(
                "INSERT INTO task_blocks (task_id, member_id, themi_event_id, starts_at, ends_at, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    task.id, ctx.member.id, themi_id,
                    to_utc_iso(datetime.fromisoformat(payload["starts"])),
                    to_utc_iso(datetime.fromisoformat(payload["ends"])),
                    to_utc_iso(clock.now()),
                ),
            )  # fmt: skip
        self.board.withdraw_prompt(task)  # its nudge comes with the block now
        return f"{text} Its nudge waits until then."

    def payload(self, task: Task, when: When) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "title": task.title,
            "location": "",
            "starts": when.starts.isoformat(),
            "ends": when.ends.isoformat(),
            "all_day": False,
            "calendar": "mine",
            "source": f"{TASK_BLOCK}{task.id}",
        }

    def find_slot(self, member: Member, minutes: int, days: int) -> When | None:
        """The first good window that fits: outside their busy times, quiet hours and
        calendar, at a time the energy model expects them to have room (if it can say)."""
        length = timedelta(minutes=minutes)
        start = _round_up(clock.now() + timedelta(minutes=30))
        energy = self.services.energy
        if not isinstance(energy, EnergyModel):
            return None
        for window in windows(energy, member, start, horizon=timedelta(days=days)):
            begins = _round_up(window.start)
            if begins + length <= window.end:
                return When(begins, begins + length, False)
        return None

    # ----- the job --------------------------------------------------------------------------

    async def tick(self) -> int:
        """Scheduler job: follow blocks moved or deleted on the calendar, nudge as blocks
        begin, and ask once when one ends with the task open. Returns how many nudged."""
        now = clock.now()
        nudged = 0
        for row in self.db.query(
            "SELECT b.*, e.event_id AS gcal_id FROM task_blocks b JOIN themi_events e "
            "ON e.id = b.themi_event_id WHERE b.removed_at IS NULL AND b.asked = 0"
        ):
            try:
                task = self.board.get(row["task_id"])
            except NotFound:
                continue
            member = self.services.store.get_member(row["member_id"])
            row = self._follow(row, member)
            if row is None:
                if task.status in ("open", "snoozed"):
                    await self.board.prompt(task, member=member)  # back to its usual nudge
                continue
            if task.status not in ("open", "snoozed"):
                self.db.execute("UPDATE task_blocks SET asked = 1 WHERE id = ?", (row["id"],))
                continue
            if not row["nudged"] and datetime.fromisoformat(row["starts_at"]) <= now:
                self.db.execute("UPDATE task_blocks SET nudged = 1 WHERE id = ?", (row["id"],))
                await self.board.prompt(task, member=member)
                nudged += 1
            elif row["nudged"] and datetime.fromisoformat(row["ends_at"]) <= now:
                self.db.execute("UPDATE task_blocks SET asked = 1 WHERE id = ?", (row["id"],))
                if self._unanswered(task, row):
                    continue  # its nudge already asks "done, or later?": not a second question
                await self.services.outbox.send(
                    member,
                    ENDED_TEXT.format(title=task.title),
                    priority=Priority.NORMAL,
                    kind="task",
                    buttons=[Button("Done", "task", {"task": task.id, "action": "done"})],
                    dedupe_key=f"block-ended-{row['id']}",
                )
        return nudged

    def _unanswered(self, task: Task, row: dict[str, Any]) -> bool:
        """The nudge that went as the block began is still waiting for an answer."""
        return task.status == "open" and bool(
            self.db.one(
                "SELECT 1 FROM tasks t JOIN outbox o ON o.id = t.prompt_outbox_id "
                "WHERE t.id = ? AND o.status = 'sent' AND o.sent_at >= ?",
                (task.id, row["starts_at"]),
            )
        )

    def _follow(self, row: dict[str, Any], member: Member) -> dict[str, Any] | None:
        """The block as its event now stands: moved, or gone (None) once a read of the
        calendar since the block was made no longer has it."""
        entry = self.db.one(
            "SELECT starts_at, ends_at FROM calendar_entries WHERE event_id = ?", (row["gcal_id"],)
        )
        if entry is None:
            read = self.db.scalar(
                "SELECT MAX(read_at) FROM calendar_reads WHERE member_id = ?", (member.id,)
            )
            # Gone only from a read that would have had it: made since the block, and before
            # the block ended (reads start from "now", so a block that's over drops out).
            if read and row["created_at"] < read < row["ends_at"] and member.tracks("calendar"):
                self.db.execute(
                    "UPDATE task_blocks SET removed_at = ? WHERE id = ?",
                    (to_utc_iso(clock.now()), row["id"]),
                )
                return None
            return row
        if (entry["starts_at"], entry["ends_at"]) != (row["starts_at"], row["ends_at"]):
            later = entry["starts_at"] > to_utc_iso(clock.now())
            self.db.execute(
                "UPDATE task_blocks SET starts_at = ?, ends_at = ?, nudged = ? WHERE id = ?",
                (entry["starts_at"], entry["ends_at"], 0 if later else row["nudged"], row["id"]),
            )
            return {**row, **dict(entry), "nudged": 0 if later else row["nudged"]}
        return row

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _round_up(moment: datetime) -> datetime:
    """To the next quarter hour."""
    extra = (-moment.minute) % 15
    return (moment + timedelta(minutes=extra)).replace(second=0, microsecond=0)


def _blocks(ctx: ToolContext) -> TaskBlocks:
    blocks = ctx.services.task_blocks
    if blocks is None or ctx.services.events is None:
        raise ToolFailed("Calendars aren't set up.")
    return blocks


def _task(blocks: TaskBlocks, ctx: ToolContext, task_id: int) -> Task:
    try:
        task = blocks.board.get(task_id)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if task.status not in ("open", "snoozed"):
        raise ToolFailed(f"{task.title} isn't open.")
    return task


@staged_tool(
    "block_time_for_task",
    "Block time on their own calendar for a task ('block Saturday morning for the "
    "bathroom'). date: YYYY-MM-DD; start and end: HH:MM, 24-hour. The task's nudges wait for "
    "the block. Asked for in their words, it's made at once. A nudge at a time ('prompt me "
    "to run at 2') isn't a block: that's snooze_task.",
    {
        "task_id": {"type": "integer"},
        "date": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
    },
)
async def block_time_for_task(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    blocks = _blocks(ctx)
    task = _task(blocks, ctx, int(args["task_id"]))
    events = ctx.services.events
    assert events is not None
    events.own_account(ctx.member)
    if not str(args["start"]).strip():
        raise ToolFailed("A block needs a start time, like 10:00.")
    said = name_key(ctx.request_text)
    if NUDGE.search(said) and not INTENT.search(said):
        raise ToolFailed(
            "They asked for a nudge at that time, not time on their calendar: use "
            "snooze_task with until (HH:MM) for an existing task."
        )
    when = parse_when(args["date"], args["start"], args["end"], events._today(), events._tz())
    proposal = Proposal(
        OWN,
        f"Time for {task.title}: {when_words(when, events._tz())}, on your calendar",
        EXECUTOR,
        blocks.payload(task, when),
    )
    return replace(proposal, requested=bool(INTENT.search(said)), expires=when.ends)


@staged_tool(
    "find_time_for_task",
    "Find a free, good time on their calendar for a task and offer it as a card ('find me "
    "time for the bathroom'). minutes: how long it takes; days: how far ahead to look (1-14).",
    {
        "task_id": {"type": "integer"},
        "minutes": {"type": "integer"},
        "days": {"type": "integer"},
    },
)
async def find_time_for_task(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    blocks = _blocks(ctx)
    task = _task(blocks, ctx, int(args["task_id"]))
    events = ctx.services.events
    assert events is not None
    events.own_account(ctx.member)
    minutes = int(args["minutes"])
    if not 10 <= minutes <= 8 * 60:
        raise ToolFailed("A block is between 10 minutes and 8 hours.")
    days = min(max(int(args["days"]), 1), MAX_DAYS)
    when = blocks.find_slot(ctx.member, minutes, days)
    if when is None:
        raise ToolFailed(f"There's no free {minutes} minutes in the next {days} days.")
    return Proposal(
        OWN,
        f"Time for {task.title}: {when_words(when, events._tz())}, on your calendar",
        EXECUTOR,
        blocks.payload(task, when),
        expires=when.ends,  # a time that's past is no use (bug #64's stale card)
    )
