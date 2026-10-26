"""Household tasks: created in conversation, matched to whoever has room, nudged gently.

A new task is assigned by the matcher and announced to its assignee as a
two-option message ("done already, or later?") that waits for their good
window, or goes by the due date's morning at the latest. "Later" snoozes it
for a few hours, after which it's offered again. The model gets the reason
for the assignment in words, so it can say who's taking what and why.

Every change (created, rescheduled, done, cancelled) goes to
`change_listeners`; the family calendar follows tasks that way.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Outbox, Priority
from themi.core.prompts import OpenItem
from themi.core.repeat import (
    Repeat,
    next_occurrences,
    parse,
    previous_occurrence,
    read_back,
)
from themi.core.services import Services
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.energy.matching import Assignment, Matcher
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

SNOOZE_FOR = timedelta(hours=4)
# A task someone just added for themselves in chat isn't asked about straight away.
FIRST_NUDGE_AFTER = timedelta(hours=4)
TASK_KINDS = ["text", "call", "physical", "errand"]
# Every nudge opens with a label: when it's due, "To do" without a date, or "Check-in"
# (Erin's rules 6-8, bug #9). Titles are often commands ("Call the vet"), so they never
# open a sentence; the label comes first.
NUDGE_LEAD = "{label}: {title}{who}{whenever}"
WHENEVER = ", whenever it suits"
# When someone else added it, the nudge says who, so it doesn't arrive out of nowhere.
ADDED_BY = " ({who} added this for you)"
# Repeating chores (F6b).
OVERDUE_TEXT = "Overdue: {title} (last done {ago})"
SHARED_OVERDUE_TEXT = "Overdue for both of you: {title} (last done {ago})"
NEXT_ROUND_TEXT = " Next round: {when}."
STEP_UP_CATEGORY = "chore_step_up"
STEP_UP_EXECUTOR = "tasks.step_up"
STEP_UP_AFTER = 6  # on-time runs in a row before offering to go more often
DONE_TEXT = "Marked done: {title}. Thank you."
LAST_ROUND_TEXT = " That was the last one."
LATER_TEXT = "No rush on that one ({title}). It'll come back around in a few hours."
SETTLED_TEXT = "That one's already settled."
CANCELLED_TEXT = "Taken off the list: {title}."
RESCHEDULED_TEXT = "{title} is now due {due}."
UNSCHEDULED_TEXT = "{title} no longer has a date."


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    kind: str
    effort: int
    assignee: int | None
    default_owner: int | None
    assign_reason: str
    status: str
    due_on: date | None
    created_by: int | None = None
    steps: tuple[str, ...] = ()  # in the person's words; tags like "(Optional/Bonus)" included
    # A repeating chore's schedule (F6b); None when it doesn't repeat.
    times_per_week: float | None = None
    minimum_days: float | None = None  # overdue after this many days
    escalate_days: float | None = None  # escalated after this many days
    escalate_to: str | None = None  # "owner" or "both"
    shared: bool = False  # escalated to both: on everyone's list, anyone can do it
    # Anchored schedules (F7): fixed dates. Floating ones stay in times_per_week.
    repeat: Repeat | None = None
    missed: str = "roll"  # a missed anchored round: "roll" on, or "catch_up"
    due_before_task: int | None = None  # due the day before that chore's round
    check_in: bool = False  # "did you...?": the nudge is labelled "Check-in:"
    either: bool = False  # a chore either of you can do, every round (on both lists)
    importance: str = "normal"  # low, normal or high: how often an overdue one is raised (C2c)
    due_time: time | None = None  # a time of day on the due date ("today around 2")

    @property
    def repeats(self) -> bool:
        return bool(self.times_per_week or self.repeat or self.due_before_task)


@dataclass(frozen=True)
class Run:
    done_by: int | None
    done_at: datetime
    due_on: date | None
    on_time: bool
    missed: bool = False  # a round that passed without anyone doing it


# "created", "rescheduled", "done", "cancelled", "reassigned" or "reopened"
TaskChange = str
# (task as it is now, what changed, whether whoever caused it is in the conversation)
TaskListener = Callable[[Task, TaskChange, bool], Awaitable[None]]
# Extra text to send with a task's nudge (a call script, say), or None.
TaskDetails = Callable[[Task], str | None]


def _task_from_row(row: dict[str, Any]) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        kind=row["kind"],
        effort=row["effort"],
        assignee=row["assignee"],
        default_owner=row["default_owner"],
        assign_reason=row["assign_reason"],
        status=row["status"],
        due_on=date.fromisoformat(row["due_on"]) if row["due_on"] else None,
        created_by=row["created_by"],
        steps=tuple(json.loads(row["steps"])),
        times_per_week=row["times_per_week"],
        minimum_days=row["minimum_days"],
        escalate_days=row["escalate_days"],
        escalate_to=row["escalate_to"],
        shared=bool(row["shared"]),
        repeat=Repeat.from_json(json.loads(row["repeat"])) if row["repeat"] else None,
        missed=row["missed"],
        due_before_task=row["due_before_task"],
        check_in=bool(row["check_in"]),
        either=bool(row["either"]),
        importance=row["importance"],
        due_time=time.fromisoformat(row["due_time"]) if row["due_time"] else None,
    )


MAX_STEPS = 30
MAX_STEP_LENGTH = 200


def clean_steps(steps: Sequence[str]) -> list[str]:
    """Steps as given, trimmed, blanks dropped. The wording is the person's: never rewritten."""
    cleaned = [" ".join(str(s).split()) for s in steps]
    cleaned = [s.lstrip("-• ").strip() for s in cleaned]
    cleaned = [s for s in cleaned if s]
    if len(cleaned) > MAX_STEPS:
        raise ValueError(f"a task can have at most {MAX_STEPS} steps")
    if any(len(s) > MAX_STEP_LENGTH for s in cleaned):
        raise ValueError(f"each step can be at most {MAX_STEP_LENGTH} characters")
    return cleaned


class TaskBoard:
    def __init__(self, services: Services, matcher: Matcher) -> None:
        self.services = services
        self.matcher = matcher
        self.store = services.store
        self.db = services.store.db
        self.change_listeners: list[TaskListener] = []
        self.details: list[TaskDetails] = []  # steps come first, from _steps_for
        self._pending_prompts: list[int] = []

    @property
    def outbox(self) -> Outbox:
        return self.services.outbox

    def install(self) -> None:
        s = self.services
        s.taskboard = self
        s.tools.register(create_task)
        s.tools.register(complete_task)
        s.tools.register(cancel_task)
        s.tools.register(reschedule_task)
        s.tools.register(snooze_task)
        s.tools.register(update_task)
        s.tools.register(set_task_schedule)
        s.button_handlers["task"] = self.on_button
        s.open_item_sources.append(self.open_items)
        s.autonomy.executors.register(STEP_UP_EXECUTOR)(self._step_up)

    # ----- reading ------------------------------------------------------------

    def get(self, task_id: int) -> Task:
        row = self.db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise NotFound(f"no task with id {task_id}")
        return _task_from_row(row)

    def open_for(self, member: Member) -> list[Task]:
        rows = self.db.query(  # shared (escalated to both) chores come first, for everyone
            "SELECT * FROM tasks WHERE (assignee = ? OR shared = 1) "
            "AND status IN ('open', 'snoozed') ORDER BY shared DESC, due_on IS NULL, due_on, id",
            (member.id,),
        )
        return [_task_from_row(r) for r in rows]

    def runs(self, task_id: int) -> list[Run]:
        rows = self.db.query(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY done_at, id", (task_id,)
        )
        return [
            Run(
                r["done_by"],
                datetime.fromisoformat(r["done_at"]),
                date.fromisoformat(r["due_on"]) if r["due_on"] else None,
                bool(r["on_time"]),
                bool(r["missed"]),
            )
            for r in rows
        ]

    def added_by(self, member: Member) -> list[Task]:
        """Open tasks this member added, whoever is doing them."""
        rows = self.db.query(
            "SELECT * FROM tasks WHERE created_by = ? AND status IN ('open', 'snoozed') "
            "ORDER BY due_on IS NULL, due_on, id",
            (member.id,),
        )
        return [_task_from_row(r) for r in rows]

    def open_items(self, member: Member) -> list[OpenItem]:
        items = []
        for t in self.open_for(member):
            due = f", due {t.due_on.isoformat()}" if t.due_on else ""
            whose = "shared, overdue: either of you" if t.shared else "theirs"
            steps = f" Steps: {'; '.join(t.steps)}" if t.steps else ""
            if any(_step_level(step) for step in t.steps):
                level = self.services.energy.suggested_level(member)
                if level is not None:
                    steps += (
                        f" Suggested today: the {_LEVEL_WORD[level]} ({level.title()}) version."
                    )
            schedule = f" {self.summary(t)}." if t.repeats else ""
            items.append(OpenItem(f"Task {t.id} ({whose}{due}): {t.title}.{schedule}{steps}"))
        return items

    # ----- changing -----------------------------------------------------------

    async def create(
        self,
        requester: Member,
        title: str,
        kind: str,
        effort: int,
        due_on: date | None = None,
        *,
        interactive: bool = False,
        nudge: bool = True,
        assignee: Member | None = None,
        steps: Sequence[str] = (),
        check_in: bool = False,
        due_time: time | None = None,
    ) -> Task:
        """Add and assign a task. With `nudge=False` the caller sends `prompt()` itself
        (after attaching details, like a call script). An `assignee` (someone took it on,
        or was named) skips matching; without one, matching decides."""
        title = title.strip().rstrip(".")
        if not title:
            raise ValueError("a task needs a title")
        cleaned_steps = clean_steps(steps)
        if assignee is None:
            assignment = self.matcher.assign(kind, effort, requester)
        elif assignee.id == requester.id:
            assignment = Assignment(assignee, assignee, f"{requester.name} said they'd do it.")
        else:
            assignment = Assignment(
                assignee, assignee, f"{requester.name} asked for {assignee.name} to do it."
            )
        task_id = self.db.execute(
            "INSERT INTO tasks (title, kind, effort, created_by, default_owner, assignee, "
            "assign_reason, due_on, created_at, steps, check_in, due_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                kind,
                effort,
                requester.id,
                assignment.default_owner.id,
                assignment.assignee.id,
                assignment.reason,
                due_on.isoformat() if due_on else None,
                to_utc_iso(clock.now()),
                json.dumps(cleaned_steps),
                int(check_in),
                due_time.strftime("%H:%M") if due_on and due_time else None,
            ),
        )
        if nudge:
            task = self.get(task_id)
            if task.due_on is not None:
                # Nothing is asked about before it's due (bug #14): its day, or its time.
                not_before = self._round_starts(task)
            elif interactive and assignment.assignee.id == requester.id:
                # They just said it themselves: an instant "done already, or later?" is noise.
                not_before = clock.now() + FIRST_NUDGE_AFTER
            else:
                not_before = None
            await self.prompt(task, not_before=not_before)
        task = self.get(task_id)
        await self._changed(task, "created", interactive)
        return task

    async def _changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        for listener in self.change_listeners:
            try:
                await listener(task, change, interactive)
            except Exception:
                log.exception("A task listener failed for task %s (%s)", task.id, change)

    async def prompt(
        self,
        task: Task,
        *,
        not_before: datetime | None = None,
        member: Member | None = None,
        overdue: str | None = None,
        priority: Priority = Priority.NORMAL,
        lead: str | None = None,
    ) -> None:
        """Nudge whoever does the task (or `member`). `overdue`: "own" or "shared" wording.
        `priority` LOW lets a batch of nudges trickle out in good moments. `lead` replaces
        the opening line (an overdue reminder's, C2c)."""
        if task.assignee is None and member is None:
            return
        if not_before is None and overdue is None and lead is None:
            starts = self._round_starts(task)  # nothing is asked about before it's due (#14)
            if starts is not None and starts > clock.now():
                not_before = starts
        deadline = self._deadline(task)
        if not_before is not None and deadline is not None:
            not_before = min(not_before, deadline)  # a due date still wins
        if member is None:
            assert task.assignee is not None
            member = self.store.get_member(task.assignee)
        parts = [self._steps_for(task, member), *(source(task) for source in self.details)]
        details = "\n\n".join(d for d in parts if d)
        added_by = (
            self.store.get_member(task.created_by)
            if task.created_by is not None and task.created_by != member.id
            else None
        )
        goes_out = self.outbox.send_time(
            member, priority, deadline=deadline, kind="task", not_before=not_before
        )
        family = self.store.get_family()
        local_day = goes_out.astimezone(ZoneInfo(family.timezone if family else "UTC")).date()
        if lead is None and overdue is not None:
            template = SHARED_OVERDUE_TEXT if overdue == "shared" else OVERDUE_TEXT
            lead = template.format(title=task.title, ago=self._last_done_words(task))
        elif lead is None:
            lead = NUDGE_LEAD.format(
                label=_label(task, local_day),
                title=task.title,
                who=ADDED_BY.format(who=added_by.name) if added_by is not None else "",
                whenever=WHENEVER if task.due_on is None and not task.check_in else "",
            )
        text = (
            f"{lead}.\n\n{details}\n\nDone already, or later?"
            if details
            else f"{lead}. Done already, or later?"
        )
        result = await self.outbox.send(
            member,
            text,
            priority=priority,
            kind="task",
            buttons=[
                Button("Done", "task", {"task": task.id, "action": "done"}),
                Button("Later", "task", {"task": task.id, "action": "later"}),
            ],
            deadline=deadline,
            not_before=not_before,
            dedupe_key=f"task-{task.id}-{secrets.token_hex(4)}",  # tags it, for withdrawing
        )
        if result.outbox_id is not None:
            self.db.execute(
                "UPDATE tasks SET prompt_outbox_id = ? WHERE id = ?", (result.outbox_id, task.id)
            )

    def _deadline(self, task: Task) -> datetime | None:
        """By when a nudge should go out: its time on the due date (the task's, or the
        chore's), else 9 am."""
        if task.due_on is None:
            return None
        return _on(task.due_on, self._time_of(task) or time(9), self._tz())

    @staticmethod
    def _time_of(task: Task) -> time | None:
        return task.due_time or (task.repeat.at if task.repeat else None)

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _round_starts(self, task: Task) -> datetime | None:
        """When this round's nudge may go: the chore's time on its due date, or that morning."""
        if task.due_on is None:
            return None
        at = self._time_of(task)
        return _on(task.due_on, at, self._tz()) if at else self._day_start(task.due_on)

    def _steps_for(self, task: Task, member: Member) -> str | None:
        """The steps for a nudge. With (Low)/(Medium)/(High) tags, only the level that suits
        the person today (each level takes in the ones below it), in words (S4)."""
        if not task.steps:
            return None
        levels = [_step_level(step) for step in task.steps]
        if not any(levels):
            return _quoted(task.steps)
        level = self.services.energy.suggested_level(member)
        if level is None:
            return _quoted(task.steps)
        keep = [
            step
            for step, tag in zip(task.steps, levels, strict=True)
            if tag is None or _LEVEL_ORDER[tag] <= _LEVEL_ORDER[level]
        ]
        lines = [_LEVEL_LEAD[level], _quoted(keep)]
        if any(tag and _LEVEL_ORDER[tag] > _LEVEL_ORDER[level] for tag in levels):
            lines.append("The rest is there too if you feel like more.")
        return "\n".join(lines)

    def can_edit(self, task: Task, member: Member) -> bool:
        return member.is_admin or member.id in (task.assignee, task.created_by)

    async def update(
        self,
        task_id: int,
        by: Member,
        *,
        title: str | None = None,
        steps: Sequence[str] | None = None,
        interactive: bool = False,
    ) -> Task:
        """Rename a task or replace its steps. The assignee, whoever added it, or an admin."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        changes: dict[str, Any] = {}
        if title is not None and title.strip().rstrip("."):
            changes["title"] = title.strip().rstrip(".")
        if steps is not None:
            changes["steps"] = json.dumps(clean_steps(steps))
        if changes:
            assignments = ", ".join(f"{c} = :{c}" for c in changes)
            self.db.execute(
                f"UPDATE tasks SET {assignments} WHERE id = :id", {**changes, "id": task_id}
            )
            await self._changed(self.get(task_id), "edited", interactive)
        return self.get(task_id)

    async def complete(self, task_id: int, by: Member, *, interactive: bool = False) -> str:
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        if task.repeats:
            return await self._complete_round(task, by, interactive)
        self.db.execute(
            "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task_id),
        )
        self._withdraw_prompt(task)
        await self._changed(self.get(task_id), "done", interactive)
        return DONE_TEXT.format(title=task.title)

    async def reassign(self, task_id: int, member: Member | None, *, shared: bool = False) -> Task:
        """Give a one-off task to someone else, or to both of you (`shared`: on everyone's
        list, either can do it). The nudge goes to whoever has it now."""
        task = self.get(task_id)
        if task.status not in ("open", "snoozed"):
            return task
        assignee = member.id if member is not None else task.assignee
        if (assignee, shared) == (task.assignee, task.shared):
            return task
        self.db.execute(
            "UPDATE tasks SET assignee = ?, shared = ? WHERE id = ?",
            (assignee, int(shared), task_id),
        )
        self._withdraw_prompt(task)
        task = self.get(task_id)
        people = (
            [m for m in self.store.list_members() if m.telegram_user_id is not None]
            if shared
            else [self.store.get_member(assignee)]
            if assignee is not None
            else []
        )
        for person in people:
            await self.prompt(task, member=person)
        await self._changed(task, "reassigned", False)
        return task

    async def reopen(self, task_id: int) -> Task:
        """A one-off task marked done that turns out not to be: open again, and nudged."""
        task = self.get(task_id)
        if task.status != "done" or task.repeats:
            return task
        self.db.execute(
            "UPDATE tasks SET status = 'open', completed_at = NULL WHERE id = ?", (task_id,)
        )
        task = self.get(task_id)
        await self.prompt(task)
        await self._changed(task, "reopened", False)
        return task

    # ----- repeating chores (F6b) ------------------------------------------------

    def _today(self) -> date:
        family = self.store.get_family()
        return clock.now().astimezone(ZoneInfo(family.timezone if family else "UTC")).date()

    def _day_start(self, day: date) -> datetime:
        family = self.store.get_family()
        tz = ZoneInfo(family.timezone if family else "UTC")
        return datetime(day.year, day.month, day.day, tzinfo=tz)

    def _last_done(self, task: Task) -> datetime | None:
        value = self.db.scalar(
            "SELECT MAX(done_at) FROM task_runs WHERE task_id = ? AND missed = 0", (task.id,)
        )
        return datetime.fromisoformat(value) if value else None

    def _last_done_words(self, task: Task) -> str:
        last = self._last_done(task)
        if last is None:
            return "not yet"
        days = int((clock.now() - last) / timedelta(days=1))
        return "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"

    async def set_schedule(
        self,
        task_id: int,
        by: Member,
        *,
        repeat: Repeat | None,
        minimum_days: float = 0,
        escalate_days: float = 0,
        escalate_to: str = "owner",
        missed: str = "roll",
        due_before_task: int | None = None,
        either: bool = False,
    ) -> Task:
        """Give a task a schedule, or take it away (no `repeat` and no `due_before_task`).
        Zeros mean "no minimum" or "no escalation". Anchored and deadline schedules get their
        first due date and a nudge for it."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        if repeat is None and due_before_task is None:
            self.db.execute(
                "UPDATE tasks SET times_per_week = NULL, repeat = NULL, due_before_task = NULL, "
                "minimum_days = NULL, escalate_days = NULL, escalate_to = NULL, shared = 0, "
                "either = 0 WHERE id = ?",
                (task_id,),
            )
            return self.get(task_id)
        if minimum_days < 0 or escalate_days < 0:
            raise ValueError("days can't be negative")
        if minimum_days and escalate_days and escalate_days < minimum_days:
            raise ValueError("escalation has to come after the minimum, not before it")
        if escalate_to not in ("owner", "both"):
            raise ValueError("escalate_to is 'owner' or 'both'")
        if missed not in ("roll", "catch_up"):
            raise ValueError("missed is 'roll' or 'catch_up'")
        if due_before_task is not None:
            if due_before_task == task_id:
                raise ValueError("a chore can't be due before itself")
            target = self.get(due_before_task)  # NotFound if there's no such task
            if target.repeat is None and target.due_on is None:
                raise ValueError(f"'{target.title}' has no dates to be due before")
        floating = repeat is not None and not repeat.anchored
        self.db.execute(
            "UPDATE tasks SET times_per_week = ?, repeat = ?, due_before_task = ?, missed = ?, "
            "minimum_days = ?, escalate_days = ?, escalate_to = ?, either = ?, shared = ? "
            "WHERE id = ?",
            (
                repeat.times_per_week if floating and repeat else None,
                json.dumps(repeat.to_json()) if repeat and repeat.anchored else None,
                due_before_task,
                missed,
                minimum_days or None,
                escalate_days or None,
                escalate_to if escalate_days else None,
                int(either),
                int(either),
                task_id,
            ),
        )
        task = self.get(task_id)
        first = self._first_due(task)
        if first is not None and first != task.due_on:
            self.db.execute(
                "UPDATE tasks SET due_on = ? WHERE id = ?", (first.isoformat(), task_id)
            )
            task = self.get(task_id)
            self._withdraw_prompt(task)
            await self.prompt(task, not_before=self._round_starts(task))
            await self._changed(task, "rescheduled", True)
        elif task.due_on is not None and self._withdraw_prompt(task):
            # The nudge queued when the task was made waits for the chore's own day (bug #10).
            await self.prompt(task, not_before=self._round_starts(task))
        return task

    def summary(self, task: Task) -> str:
        """The schedule in plain words, from what's stored (the read-back)."""
        parts = []
        if task.due_before_task is not None:
            try:
                target = self.get(task.due_before_task)
                parts.append(f"Due the day before {target.title} ({self.summary(target)})")
            except NotFound:
                parts.append("Due the day before another chore that's gone")
        elif task.repeat is not None:
            parts.append(read_back(task.repeat))
        elif task.times_per_week:
            parts.append(read_back(Repeat("floating", times_per_week=task.times_per_week)))
        else:
            return "Doesn't repeat"
        if task.either:
            parts.append("either of you")
        if task.minimum_days:
            parts.append(f"overdue after {_days(task.minimum_days)}")
        if task.escalate_days:
            who = "both of you" if task.escalate_to == "both" else "a reminder to its owner"
            verb = "it goes to" if task.escalate_to == "both" else "comes"
            parts.append(f"after {_days(task.escalate_days)} {verb} {who}")
        if task.repeat is not None and task.missed == "catch_up":
            parts.append("a missed round stays owed")
        return "; ".join(parts)

    def next_dates(self, task: Task, count: int = 3) -> list[datetime]:
        """The coming rounds of an anchored chore, for the website."""
        if task.repeat is None:
            return []
        start = self._round_starts(task)
        upcoming = [start] if start else []
        after = start or clock.now()
        upcoming += next_occurrences(task.repeat, after, self._tz(), count)
        return upcoming[:count]

    def _first_due(self, task: Task) -> date | None:
        """An anchored chore's next date (today counts if its time hasn't passed), or a
        deadline chore's day-before date."""
        if task.due_before_task is not None:
            return self._deadline_due(task)
        if task.repeat is None:
            return None
        now = clock.now()
        if task.repeat.at is None:  # a date-only round today is still today's
            now = self._day_start(self._today()) - timedelta(microseconds=1)
        found = next_occurrences(task.repeat, now, self._tz())
        return found[0].date() if found else None

    def _deadline_due(self, task: Task) -> date | None:
        """The day before the other chore's round, unless this chore was already done for
        that round, in which case the day before its next one."""
        assert task.due_before_task is not None
        try:
            target = self.get(task.due_before_task)
        except NotFound:
            return task.due_on
        if target.due_on is None:
            return task.due_on
        tz = self._tz()
        round_day = target.due_on
        last = self._last_done(task)
        if last is not None and target.repeat is not None:
            previous = previous_occurrence(target.repeat, self._day_start(round_day), tz)
            if last.astimezone(tz).date() > (previous.date() if previous else date.min):
                end_of_round = self._day_start(round_day + timedelta(days=1))
                following = next_occurrences(target.repeat, end_of_round, tz)
                if following:
                    round_day = following[0].date()
        return round_day - timedelta(days=1)

    def _next_due_after_done(self, task: Task, today: date) -> date | None:
        """The next round's day; None when a course with an end date is over."""
        if task.due_before_task is not None:
            return self._deadline_due(task) or today + timedelta(days=7)
        if task.repeat is not None:
            # This round counts as done, early or late: the next one is after it.
            last_day = max(today, task.due_on or today)
            after = self._day_start(last_day + timedelta(days=1)) - timedelta(microseconds=1)
            found = next_occurrences(task.repeat, after, self._tz())
            if found:
                return found[0].date()
            return None if task.repeat.until else today + timedelta(days=7)
        assert task.times_per_week is not None
        return today + timedelta(days=max(1, int(7 / task.times_per_week + 0.5)))

    async def _complete_round(self, task: Task, by: Member, interactive: bool) -> str:
        today = self._today()
        on_time = task.due_on is None or today <= task.due_on
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO task_runs (task_id, done_by, done_at, due_on, on_time) "
            "VALUES (?, ?, ?, ?, ?)",
            (task.id, by.id, now, task.due_on.isoformat() if task.due_on else None, int(on_time)),
        )
        next_due = self._next_due_after_done(task, today)
        if next_due is None:
            await self._finish_course(task, interactive)
            return DONE_TEXT.format(title=task.title) + LAST_ROUND_TEXT
        self.db.execute(  # the next round: back to its owner, nothing overdue
            "UPDATE tasks SET status = 'open', due_on = ?, shared = either, snoozed_until = NULL, "
            "overdue_notified_at = NULL, escalated_at = NULL, overdue_reminders = 0, "
            "overdue_reminded_on = NULL WHERE id = ?",
            (next_due.isoformat(), task.id),
        )
        self._withdraw_prompt(task)
        fresh = self.get(task.id)
        await self.prompt(fresh, not_before=self._round_starts(fresh))
        await self._changed(fresh, "rescheduled", interactive)
        await self._maybe_offer_step_up(fresh)
        return DONE_TEXT.format(title=task.title) + NEXT_ROUND_TEXT.format(
            when=next_due.strftime("%a %d %b")
        )

    async def _finish_course(self, task: Task, interactive: bool) -> None:
        """A chore with an end date has had its last round."""
        self.db.execute(
            "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task.id),
        )
        self._withdraw_prompt(task)
        await self._changed(self.get(task.id), "done", interactive)

    async def _settle_missed_round(self, task: Task) -> Task:
        """An anchored round whose day has passed: roll on to the next date (recording a missed
        run), or, for catch-up chores, leave it owed. Deadline chores follow their target."""
        today = self._today()
        if task.due_before_task is not None:
            due = self._deadline_due(task)
            if due is not None and task.due_on is not None and due > task.due_on and due > today:
                # The other chore's round moved on; if this one wasn't done for it, it's missed.
                last = self._last_done(task)
                if last is None or last.astimezone(self._tz()).date() < task.due_on:
                    self._record_missed(task)
                self._move_round(task, due)
            return self.get(task.id)
        if task.repeat is None or task.due_on is None or task.due_on >= today:
            return task
        if task.missed == "catch_up":
            return task
        self._record_missed(task)
        found = next_occurrences(task.repeat, clock.now(), self._tz())
        if found:
            self._move_round(task, found[0].date())
        elif task.repeat.until is not None:
            await self._finish_course(task, False)
        return self.get(task.id)

    def _record_missed(self, task: Task) -> None:
        self.db.execute(
            "INSERT INTO task_runs (task_id, done_by, done_at, due_on, on_time, missed) "
            "VALUES (?, NULL, ?, ?, 0, 1)",
            (task.id, to_utc_iso(clock.now()), task.due_on.isoformat() if task.due_on else None),
        )

    def _move_round(self, task: Task, due: date) -> None:
        self.db.execute(
            "UPDATE tasks SET due_on = ?, status = 'open', snoozed_until = NULL, "
            "overdue_reminders = 0, overdue_reminded_on = NULL WHERE id = ?",
            (due.isoformat(), task.id),
        )
        self._withdraw_prompt(task)
        self._pending_prompts.append(task.id)

    async def check_schedules(self) -> int:
        """Scheduler job: settle missed anchored rounds, then overdue nudges past the minimum
        and escalation past its point (each once per round). Returns how many were nudged."""
        nudged = 0
        now = clock.now()
        self._pending_prompts = []
        rows = self.db.query(
            "SELECT * FROM tasks WHERE (times_per_week IS NOT NULL OR repeat IS NOT NULL "
            "OR due_before_task IS NOT NULL) AND status IN ('open', 'snoozed')"
        )
        for row in rows:
            task = await self._settle_missed_round(_task_from_row(row))
            if task.status == "done":  # a course that's over
                continue
            row = self.db.one("SELECT * FROM tasks WHERE id = ?", (task.id,)) or row
            since = self._last_done(task) or datetime.fromisoformat(row["created_at"])
            days = (now - since) / timedelta(days=1)
            stamp = to_utc_iso(now)
            if task.escalate_days and days >= task.escalate_days and not row["escalated_at"]:
                both = task.escalate_to == "both"
                self.db.execute(
                    "UPDATE tasks SET escalated_at = ?, overdue_notified_at = ?, shared = ? "
                    "WHERE id = ?",
                    (stamp, row["overdue_notified_at"] or stamp, int(both), task.id),
                )
                task = self.get(task.id)
                if both:
                    for member in self.store.list_members():
                        if member.telegram_user_id is not None:
                            await self.prompt(task, member=member, overdue="shared")
                else:
                    await self.prompt(task, overdue="own")
                nudged += 1
            elif task.minimum_days and days >= task.minimum_days and not row["overdue_notified_at"]:
                self.db.execute(
                    "UPDATE tasks SET overdue_notified_at = ? WHERE id = ?", (stamp, task.id)
                )
                await self.prompt(task, overdue="own")
                nudged += 1
        for task_id in self._pending_prompts:  # rounds that moved on get their nudge
            fresh = self.get(task_id)
            await self.prompt(fresh, not_before=self._round_starts(fresh))
        self._pending_prompts = []
        return nudged

    async def _maybe_offer_step_up(self, task: Task) -> None:
        """After STEP_UP_AFTER on-time runs in a row, offer one more time a week, as an
        approval. Nothing changes without a yes, and the next offer needs a new stretch."""
        times = task.times_per_week
        if times is None or times != int(times) or times >= 7 or task.assignee is None:
            return
        offered = self.db.scalar("SELECT step_up_offered_at FROM tasks WHERE id = ?", (task.id,))
        rows = self.db.query(
            "SELECT on_time FROM task_runs WHERE task_id = ? AND (? IS NULL OR done_at > ?) "
            "ORDER BY done_at DESC, id DESC LIMIT ?",
            (task.id, offered, offered, STEP_UP_AFTER),
        )
        if len(rows) < STEP_UP_AFTER or not all(r["on_time"] for r in rows):
            return
        current, more = int(times), int(times) + 1
        self.db.execute(
            "UPDATE tasks SET step_up_offered_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task.id),
        )
        await self.services.autonomy.stage(
            STEP_UP_CATEGORY,
            self.store.get_member(task.assignee),
            f"Step up: {task.title}, {more} times a week instead of {current}",
            {"task": task.id, "times": more},
            STEP_UP_EXECUTOR,
        )

    async def _step_up(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        task_id, times = int(payload["task"]), float(payload["times"])
        self.db.execute("UPDATE tasks SET times_per_week = ? WHERE id = ?", (times, task_id))
        task = self.get(task_id)
        return f"{task.title}: {self.summary(task)}, from now on."

    async def cancel(self, task_id: int, by: Member, *, interactive: bool = False) -> str:
        """Nobody needs to do it after all (deleting a task keeps its record)."""
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        self.db.execute(
            "UPDATE tasks SET status = 'cancelled', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task_id),
        )
        self._withdraw_prompt(task)
        await self._changed(self.get(task_id), "cancelled", interactive)
        return CANCELLED_TEXT.format(title=task.title)

    async def reschedule(
        self, task_id: int, due_on: date | None, *, interactive: bool = False
    ) -> str:
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        self.db.execute(
            "UPDATE tasks SET due_on = ?, overdue_reminders = 0, overdue_reminded_on = NULL "
            "WHERE id = ?",
            (due_on.isoformat() if due_on else None, task_id),
        )
        await self._changed(self.get(task_id), "rescheduled", interactive)
        if due_on is None:
            return UNSCHEDULED_TEXT.format(title=task.title)
        return RESCHEDULED_TEXT.format(title=task.title, due=due_on.isoformat())

    def snooze(self, task_id: int, for_: timedelta = SNOOZE_FOR) -> str:
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        self.db.execute(
            "UPDATE tasks SET status = 'snoozed', snoozed_until = ? WHERE id = ?",
            (to_utc_iso(clock.now() + for_), task_id),
        )
        self._withdraw_prompt(task)
        return LATER_TEXT.format(title=task.title)

    def _withdraw_prompt(self, task: Task) -> bool:
        """Take back any of the task's nudges that haven't gone out yet (shared ones too).
        True if there was one."""
        withdrawn = False
        row = self.db.one("SELECT prompt_outbox_id FROM tasks WHERE id = ?", (task.id,))
        if row and row["prompt_outbox_id"]:
            withdrawn = self.outbox.cancel(row["prompt_outbox_id"])
        for queued in self.db.query(
            "SELECT id FROM outbox WHERE status = 'queued' AND dedupe_key LIKE ?",
            (f"task-{task.id}-%",),
        ):
            withdrawn = self.outbox.cancel(queued["id"]) or withdrawn
        return withdrawn

    async def resurface(self) -> int:
        """Snoozed tasks whose time has come are offered again."""
        rows = self.db.query(
            "SELECT * FROM tasks WHERE status = 'snoozed' AND snoozed_until <= ?",
            (to_utc_iso(clock.now()),),
        )
        for row in rows:
            self.db.execute(
                "UPDATE tasks SET status = 'open', snoozed_until = NULL WHERE id = ?", (row["id"],)
            )
            await self.prompt(self.get(row["id"]))
        return len(rows)

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        task_id = int(event.button.payload["task"])
        action = event.button.payload.get("action")
        if action == "done":
            reply = await self.complete(task_id, event.member, interactive=True)
        else:
            reply = self.snooze(task_id)
        if event.button.message_id is not None:
            await self.outbox.edit(event.member, event.button.message_id, reply)


def _label(task: Task, today: date) -> str:
    """What a nudge opens with, for the day it goes out. At most three words, so the
    phrasing check reads it as a label rather than an order."""
    if task.check_in:
        return "Check-in"
    if task.due_on is None:
        return "To do"
    days = (task.due_on - today).days
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    if days == -1:
        return "Was due yesterday"
    named = f"{task.due_on:%A}" if abs(days) < 7 else f"{task.due_on.day} {task.due_on:%b}"
    return f"Due {named}" if days > 0 else f"Was due {named}"


def _on(day: date, at: time, tz: ZoneInfo) -> datetime:
    """That wall-clock time on that day, in the family's timezone."""
    return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=tz)


def _days(value: float) -> str:
    return f"{value:g} day{'s' if value != 1 else ''}"


_LEVEL_TAG = re.compile(r"^\((low|medium|high)\)", re.IGNORECASE)
_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
_LEVEL_LEAD = {
    "low": "A lighter version for today:",
    "medium": "A middle version for today:",
    "high": "The full version for today:",
}
_LEVEL_WORD = {"low": "lighter", "medium": "middle", "high": "full"}


def _step_level(step: str) -> str | None:
    m = _LEVEL_TAG.match(step)
    return m.group(1).lower() if m else None


def _quoted(steps: Sequence[str]) -> str:
    """Steps as `> ` quotes, so the PDA shield keeps them word for word (steps are usually
    commands: "Wipe the counters")."""
    return "\n".join(f"> - {step}" for step in steps)


def _board(ctx: ToolContext) -> TaskBoard:
    board = ctx.services.taskboard
    assert board is not None
    return board


@tool(
    "create_task",
    "Add a household task and nudge whoever does it at a good moment. assign_to says who: "
    "'me' when the person asking will do it ('I want to...', 'I'll...', 'remind me to...'), "
    "a family member's name when they name someone, or 'anyone' when it just needs doing "
    "('can someone...', 'remind us...'); then Themi works out who has room for it.",
    {
        "title": {"type": "string", "description": "What needs doing, e.g. 'Call the vet'."},
        "kind": {"type": "string", "enum": TASK_KINDS},
        "effort": {
            "type": "integer",
            "enum": [1, 2, 3, 4, 5],
            "description": "1 = a quick thing, 5 = a big draining job.",
        },
        "due_date": {
            "type": "string",
            "description": "YYYY-MM-DD if it has a date, else an empty string.",
        },
        "due_time": {
            "type": "string",
            "description": "HH:MM (24-hour) if they gave a time of day ('around 2' is 14:00), "
            "else an empty string. Nothing is asked about before it's due.",
        },
        "assign_to": {
            "type": "string",
            "description": "'me', a family member's name, or 'anyone'.",
        },
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The steps of the job, in their words and order (tags like "
            "'(Optional/Bonus)' included), or an empty list.",
        },
        "check_in": {
            "type": "boolean",
            "description": "True when they want Themi to check in on whether they did it "
            "('check in with me about running'), rather than to remind them of a job.",
        },
    },
)
async def create_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    due = None
    if args["due_date"]:
        try:
            due = date.fromisoformat(args["due_date"])
        except ValueError:
            return "Not created: the due date should look like 2026-11-03."
    due_time = None
    if args["due_time"]:
        try:
            due_time = time.fromisoformat(args["due_time"])
        except ValueError:
            return "Not created: the time should look like 14:30."
        if due is None:
            due = _board(ctx)._today()  # a time with no date means today
    target = args["assign_to"].strip()
    chosen: Member | None = None
    if target.lower() in ("me", "myself", "the person asking"):
        chosen = ctx.member
    elif target.lower() not in ("anyone", "someone", ""):
        members = ctx.services.store.list_members()
        chosen = next((m for m in members if m.name.lower() == target.lower()), None)
        if chosen is None:
            names = ", ".join(m.name for m in members)
            return f"Not created: there's nobody called {target} in the family ({names})."
    try:
        task = await _board(ctx).create(
            ctx.member,
            args["title"],
            args["kind"],
            args["effort"],
            due,
            interactive=True,
            assignee=chosen,
            steps=args["steps"],
            check_in=bool(args["check_in"]),
            due_time=due_time,
        )
    except ValueError as exc:
        return f"Not created: {exc}"
    assignee = ctx.services.store.get_member(task.assignee) if task.assignee else ctx.member
    if assignee.id == ctx.member.id:
        who, tell = f"{assignee.name} (the person asking)", ""
    else:
        who, tell = assignee.name, f" Let {ctx.member.name} know it went to {assignee.name}."
    return (
        f"Task {task.id} created and assigned to {who}. Why: {task.assign_reason} "
        f"{assignee.name} gets a gentle nudge at a good moment.{tell}"
    )


@tool(
    "update_task",
    "Rename a task or replace its steps (the full new list, in their words), e.g. when someone "
    "adds, removes or reorders steps of a chore. Empty title or steps keep what's there; "
    "clear_steps removes them all.",
    {
        "task_id": {"type": "integer"},
        "title": {"type": "string", "description": "A new title, or an empty string."},
        "steps": {"type": "array", "items": {"type": "string"}},
        "clear_steps": {"type": "boolean"},
    },
)
async def update_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    steps = [] if args["clear_steps"] else (args["steps"] or None)
    try:
        task = await _board(ctx).update(
            args["task_id"], ctx.member, title=args["title"], steps=steps, interactive=True
        )
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    except ValueError as exc:
        raise ToolFailed(str(exc)) from exc
    steps_now = "; ".join(task.steps) if task.steps else "none"
    return f"Task {task.id} is now: {task.title}. Steps: {steps_now}"


@tool(
    "set_task_schedule",
    "Make a chore repeat, change its schedule, or stop it. repeat is a short phrase in plain "
    "words: 'every Tuesday at 6pm', 'every other Monday', 'every Tue and Fri', 'first Monday "
    "of the month', 'the 1st of every month', 'every 3 days', or 'twice a week' (counted from "
    "the last time it was done); empty to stop. Keep any time of day they gave ('Tuesday "
    "evenings' is 'every Tuesday evening'), and any end ('every 2 days until 30 Oct' for a "
    "course of medicine). due_before_task: the id of another chore this "
    "one is due the day before ('cardboard before garbage day'), else 0; repeat can then be "
    "empty. at_least_every_days: overdue after that many days (0 for none). "
    "escalate_after_days: past that, escalate (0 for none); escalate_to 'both' when they want "
    "it on both partners' lists (shared until done), else 'owner'. missed: 'roll' on to the "
    "next date if a round passes undone (usual), or 'catch_up' to keep it owed. either: true "
    "when either of them can do it each time (it's on both lists). Use it after "
    "create_task, also for repeating reminders ('always remind me about the bins on "
    "Tuesdays'). Themi reads the saved schedule back to them itself.",
    {
        "task_id": {"type": "integer"},
        "repeat": {"type": "string"},
        "at_least_every_days": {"type": "number"},
        "escalate_after_days": {"type": "number"},
        "escalate_to": {"type": "string", "enum": ["owner", "both"]},
        "missed": {"type": "string", "enum": ["roll", "catch_up"]},
        "due_before_task": {"type": "integer"},
        "either": {"type": "boolean"},
    },
)
async def set_task_schedule(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    phrase = args["repeat"].strip()
    try:
        repeat = parse(phrase, board._today()) if phrase else None
        task = await board.set_schedule(
            args["task_id"],
            ctx.member,
            repeat=repeat,
            minimum_days=float(args["at_least_every_days"]),
            escalate_days=float(args["escalate_after_days"]),
            escalate_to=args["escalate_to"],
            missed=args["missed"],
            due_before_task=args["due_before_task"] or None,
            either=bool(args["either"]),
        )
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    except ValueError as exc:  # RepeatError included: its message lists phrases that work
        raise ToolFailed(str(exc)) from exc
    if not task.repeats:
        return f"Task {task.id} ({task.title}) doesn't repeat any more."
    # The read-back is built here from what was stored, and sent as it is.
    text = f"Saved: {board.summary(task)}."
    upcoming = board.next_dates(task, 1) if task.repeat else []
    if upcoming:
        when = upcoming[0]
        clock_time = f", {_clock_words(when)}" if task.repeat and task.repeat.at else ""
        text += f" Next: {when:%a %d %b}{clock_time}."
    elif task.due_on is not None and task.due_before_task is not None:
        text += f" Next: {task.due_on:%a %d %b}."
    await ctx.services.outbox.send(ctx.member, text, priority=Priority.REPLY)
    return (
        f"Task {task.id} ({task.title}) is scheduled, and it was read back to them already, "
        f'word for word: "{text}". Don\'t restate the schedule; a short acknowledgement is '
        "enough, or ask if anything sounds wrong."
    )


def _clock_words(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d} {suffix}" if moment.minute else f"{hour} {suffix}"


@tool(
    "complete_task",
    "Mark a task done when someone says it's been taken care of.",
    {"task_id": {"type": "integer"}},
)
async def complete_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        return await _board(ctx).complete(args["task_id"], ctx.member, interactive=True)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc


@tool(
    "cancel_task",
    "Take a task off the list when it no longer needs doing (not when it's done).",
    {"task_id": {"type": "integer"}},
)
async def cancel_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        return await _board(ctx).cancel(args["task_id"], ctx.member, interactive=True)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc


@tool(
    "reschedule_task",
    "Change when a task is due, or take its date away.",
    {
        "task_id": {"type": "integer"},
        "due_date": {"type": "string", "description": "YYYY-MM-DD, or '' for no date."},
    },
)
async def reschedule_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    due = None
    if args["due_date"]:
        try:
            due = date.fromisoformat(args["due_date"])
        except ValueError:
            return "Not changed: the due date should look like 2026-11-03."
    try:
        return await _board(ctx).reschedule(args["task_id"], due, interactive=True)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc


@tool(
    "snooze_task",
    "Put a task off for a few hours when someone wants it later.",
    {"task_id": {"type": "integer"}},
)
async def snooze_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        return _board(ctx).snooze(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
