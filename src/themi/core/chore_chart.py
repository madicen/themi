"""Only so many chores on someone's chart at a time (C2d, Erin's ideas #16 and #17).

A long chore chart is overwhelming, so a person can choose how many of their chores
the wall shows at once (`chart_limit`; Erin's is 1). The rest wait in Themi, off the
wall, without nudges, until one comes up:

- High-importance chores (medicines, or anything set high) always show and don't count.
  A chore for either of you counts for the person with the limit; it stays on the wall
  for the other person.
- Which one comes up: chores due today or earlier (or due whenever), the most overdue
  first, then the more important, then the oldest. Nothing comes up before it's due
  (#14), except when asked for.
- A chore that's up stays up until its round is done or moves, even across days. Done
  (ticked on the wall or in Themi, or deleted on the wall), the next sync brings up the
  next one.
- In chat, `change_chore_chart`: "a different one" puts the current chore back for the
  day and brings up another; "another one" adds one on top of the limit.

The chore sync (`themi.core.cozyla_chores`) asks this module what each chore's wall
people are; holds keep waiting chores' nudges back (`TaskBoard.holds`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import InvalidValue, Member, NotFound
from themi.connectors.cozyla.schedule import wall_can_say
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

RANK = {"low": 0, "normal": 1, "high": 2}


def on_chart(task: Task) -> bool:
    """A chore, or a one-off someone put on the chart."""
    return task.repeats or task.on_chart


def is_routine(task: Task) -> bool:
    """A check-in on fixed days: it lives on the wall as a routine (C3), not a chore."""
    return task.check_in and wall_can_say(task.repeat)


@dataclass(frozen=True)
class Pick:
    member_id: int
    task_id: int
    due_on: str | None
    extra: bool
    prompted: bool


class ChartQueue:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.chart_queue = self
        self.board.holds.append(self.held)
        self.services.tools.register(set_chore_chart_limit)
        self.services.tools.register(change_chore_chart)

    # ----- what counts, and what's up ------------------------------------------------------

    @staticmethod
    def counts(task: Task, member: Member) -> bool:
        """One of this person's chores that their limit applies to."""
        return (
            task.status in ("open", "snoozed")
            and on_chart(task)
            and not is_routine(task)
            and task.importance != "high"
            and (task.assignee == member.id or task.either or task.shared)
        )

    def picks(self, member: Member) -> list[Pick]:
        """The chores up on this person's chart, still for the round they were picked for."""
        found = []
        for row in self.db.query(
            "SELECT * FROM cozyla_chart_picks WHERE member_id = ? ORDER BY picked_at, task_id",
            (member.id,),
        ):
            pick = Pick(
                row["member_id"],
                row["task_id"],
                row["due_on"],
                bool(row["extra"]),
                bool(row["prompted"]),
            )
            if self._still_up(pick, member):
                found.append(pick)
        return found

    def _still_up(self, pick: Pick, member: Member) -> bool:
        try:
            task = self.board.get(pick.task_id)
        except NotFound:
            return False
        return self.counts(task, member) and pick.due_on == _iso(task.due_on)

    def is_up(self, task: Task, member: Member) -> bool:
        return any(p.task_id == task.id for p in self.picks(member))

    def held(self, task: Task, member: Member) -> bool:
        """Waiting its turn: this person has a limit, it counts, and it isn't up."""
        return member.chart_limit > 0 and self.counts(task, member) and not self.is_up(task, member)

    def limited(self) -> list[Member]:
        return [m for m in self.store.list_members() if m.chart_limit > 0]

    # ----- bringing chores up -------------------------------------------------------------

    def refresh(self) -> list[tuple[Member, Task]]:
        """Drop picks whose round is over, fill each limited chart up to its limit, and keep
        waiting chores' nudges back. Returns the chores up that haven't had their nudge."""
        unprompted = []
        today = self._today()
        for member in self.limited():
            self._forget_finished(member)
            up = self.picks(member)
            for _ in range(member.chart_limit - sum(not p.extra for p in up)):
                task = self._next(member, today)
                if task is None:
                    break
                self._pick(member, task)
            for pick in self.picks(member):
                if not pick.prompted:
                    unprompted.append((member, self.board.get(pick.task_id)))
            self._quiet_waiting(member)
        return unprompted

    def prompted(self, member: Member, task: Task) -> None:
        self.db.execute(
            "UPDATE cozyla_chart_picks SET prompted = 1 WHERE member_id = ? AND task_id = ?",
            (member.id, task.id),
        )

    def done_on_wall(self, task: Task) -> Member | None:
        """Who had this chore up, so a delete on the wall completes it as them."""
        for member in self.limited():
            if self.is_up(task, member):
                return member
        return None

    def _next(self, member: Member, today: date, *, ahead: bool = False) -> Task | None:
        """The next chore to come up: due ones first; `ahead` lets one not yet due come up
        when nothing else is waiting (asked for in chat)."""
        waiting = self.waiting(member, today)
        due = [t for t in waiting if (t.due_on or today) <= today]
        if due:
            return min(due, key=lambda t: _due_key(t, today))
        if not ahead or not waiting:
            return None
        return min(waiting, key=lambda t: (t.due_on or today, -RANK[t.importance], t.id))

    def waiting(self, member: Member, today: date) -> list[Task]:
        """This person's chores that could come up: open, not up, not passed over today."""
        up = {p.task_id for p in self.picks(member)}
        skipped = {
            r["task_id"]
            for r in self.db.query(
                "SELECT task_id FROM cozyla_chart_skips WHERE member_id = ? AND day = ?",
                (member.id, today.isoformat()),
            )
        }
        return [
            t
            for t in self.board.open_for(member) + self._either_for(member)
            if t.status == "open" and self.counts(t, member) and t.id not in up | skipped
        ]

    def _either_for(self, member: Member) -> list[Task]:
        """Chores for either of you whose turn-keeper is the other person."""
        rows = self.db.query(
            "SELECT id FROM tasks WHERE either = 1 AND shared = 0 AND assignee IS NOT ? "
            "AND status IN ('open', 'snoozed')",
            (member.id,),
        )
        return [self.board.get(r["id"]) for r in rows]

    def _pick(self, member: Member, task: Task, *, extra: bool = False, prompted: bool = False):
        self.db.execute(
            "INSERT INTO cozyla_chart_picks (member_id, task_id, due_on, extra, prompted, "
            "picked_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(member_id, task_id) DO UPDATE SET "
            "due_on = excluded.due_on, extra = excluded.extra, prompted = excluded.prompted, "
            "picked_at = excluded.picked_at",
            (
                member.id,
                task.id,
                _iso(task.due_on),
                int(extra),
                int(prompted),
                to_utc_iso(clock.now()),
            ),
        )
        log.info("Chore %s is up on member %s's chart", task.id, member.id)

    def _drop(self, member: Member, task_id: int) -> None:
        self.db.execute(
            "DELETE FROM cozyla_chart_picks WHERE member_id = ? AND task_id = ?",
            (member.id, task_id),
        )

    def _forget_finished(self, member: Member) -> None:
        up = {p.task_id for p in self.picks(member)}
        for row in self.db.query(
            "SELECT task_id FROM cozyla_chart_picks WHERE member_id = ?", (member.id,)
        ):
            if row["task_id"] not in up:
                self._drop(member, row["task_id"])

    def _quiet_waiting(self, member: Member) -> None:
        """Take back nudges to this person queued for chores now waiting their turn."""
        for row in self.db.query(
            "SELECT o.id, t.id AS task_id FROM outbox o JOIN tasks t "
            "ON o.dedupe_key LIKE 'task-' || t.id || '-%' "
            "WHERE o.status = 'queued' AND o.member_id = ?",
            (member.id,),
        ):
            if self.held(self.board.get(row["task_id"]), member):
                self.services.outbox.cancel(row["id"])

    # ----- asked for in chat --------------------------------------------------------------

    def change(self, member: Member, action: str, task_id: int) -> str:
        if member.chart_limit == 0:
            raise ToolFailed(
                "They have no limit on the chart, so all their chores show already. "
                "set_chore_chart_limit sets one."
            )
        today = self._today()
        wanted = self._wanted(member, task_id) if task_id else None
        up = self.picks(member)
        if wanted is not None and any(p.task_id == wanted.id for p in up):
            return f"{wanted.title} is already up on their chart."
        if action == "another":
            task = wanted or self._next(member, today, ahead=True)
            if task is None:
                return "Nothing else is waiting: every chore of theirs is up or done."
            self._pick(member, task, extra=True, prompted=True)
            return self._up_words(task, today, "also up")
        current = next((p for p in up if not p.extra), up[0] if up else None)
        if current is not None:  # passed over for today, so it isn't picked straight back
            self.db.execute(
                "INSERT OR IGNORE INTO cozyla_chart_skips (member_id, task_id, day) "
                "VALUES (?, ?, ?)",
                (member.id, current.task_id, today.isoformat()),
            )
        task = wanted or self._next(member, today, ahead=True)
        if task is None:
            if current is not None:
                self.db.execute(
                    "DELETE FROM cozyla_chart_skips WHERE member_id = ? AND task_id = ? AND "
                    "day = ?",
                    (member.id, current.task_id, today.isoformat()),
                )
            return "That's the only chore waiting, so it stays up."
        words = self._up_words(task, today, "up now")
        if current is not None:
            self._drop(member, current.task_id)
            words += f" {self.board.get(current.task_id).title} waits until tomorrow."
        self._pick(member, task, extra=current.extra if current else False, prompted=True)
        return words

    def _wanted(self, member: Member, task_id: int) -> Task:
        try:
            task = self.board.get(task_id)
        except NotFound as exc:
            raise ToolFailed("There's no task with that number.") from exc
        if not self.counts(task, member):
            if task.importance == "high" and on_chart(task):
                raise ToolFailed(f"{task.title} always shows on their chart (it's important).")
            raise ToolFailed(f"{task.title} isn't one of their chores for the chart.")
        return task

    @staticmethod
    def _up_words(task: Task, today: date, how: str) -> str:
        due = task.due_on or today
        when = "" if due <= today else f" (not due until {due:%A}; done now, it counts)"
        return (
            f"{task.title} is {how} on their chore chart{when}; the wall has it within a few "
            "minutes."
        )

    def _today(self) -> date:
        family = self.store.get_family()
        return clock.now().astimezone(ZoneInfo(family.timezone if family else "UTC")).date()


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _due_key(task: Task, today: date) -> tuple[Any, ...]:
    due = task.due_on or today
    return (due >= today, due, -RANK[task.importance], task.id)


def _queue(ctx: ToolContext) -> ChartQueue:
    queue = ctx.services.chart_queue
    if queue is None:
        raise ToolFailed("The wall's chore chart isn't connected.")
    return queue


@tool(
    "set_chore_chart_limit",
    "How many of this person's chores the wall's chore chart shows at a time ('just one chore "
    "at a time'); the rest wait their turn in Themi, without nudges. 0 shows them all. "
    "High-importance chores (medicines) always show and don't count. This is a setting, "
    "never a rule.",
    {"limit": {"type": "integer"}},
)
async def set_chore_chart_limit(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        member = ctx.services.store.update_settings(
            ctx.member, ctx.member.id, chart_limit=args["limit"]
        )
    except InvalidValue as exc:
        raise ToolFailed(str(exc)) from exc
    if member.chart_limit == 0:
        return "All their chores show on the wall's chart again, within a few minutes."
    return (
        f"Their chart shows {member.chart_limit} chore(s) at a time from the next sync (a few "
        "minutes); important ones always show. Ticking or deleting one there brings up the next."
    )


@tool(
    "change_chore_chart",
    "For someone who sees a few chores at a time on the wall's chart: 'a different one' "
    "(action different: the current one waits until tomorrow, another comes up) or 'another "
    "one' (action another: one more on top of their limit). task_id: the chore they asked "
    "for, or 0 for Themi's pick (the most overdue, then the most important).",
    {
        "action": {"type": "string", "enum": ["different", "another"]},
        "task_id": {"type": "integer"},
    },
)
async def change_chore_chart(ctx: ToolContext, args: dict[str, Any]) -> str:
    member = ctx.services.store.get_member(ctx.member.id)
    return _queue(ctx).change(member, args["action"], args["task_id"])
