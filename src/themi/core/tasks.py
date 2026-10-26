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
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Outbox, Priority
from themi.core.prompts import OpenItem
from themi.core.services import Services
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.energy.matching import Assignment, Matcher
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

SNOOZE_FOR = timedelta(hours=4)
# A task someone just added for themselves in chat isn't asked about straight away.
FIRST_NUDGE_AFTER = timedelta(hours=4)
TASK_KINDS = ["text", "call", "physical", "errand"]
# Titles are often commands ("Call the vet"), so they never open a sentence here.
PROMPT_TEXT = "On the list for you, whenever it suits: {title}. Done already, or later?"
PROMPT_WITH_DETAILS = (
    "On the list for you, whenever it suits: {title}.\n\n{details}\n\nDone already, or later?"
)
# When someone else added it, the nudge says who, so it doesn't arrive out of nowhere.
ADDED_BY_TEXT = "{who} added this for you, whenever it suits: {title}. Done already, or later?"
ADDED_BY_WITH_DETAILS = (
    "{who} added this for you, whenever it suits: {title}.\n\n{details}\n\nDone already, or later?"
)
# A task due on the day the nudge goes out says so first (asked for by Erin's rule 6).
DUE_TODAY_TEXT = "Due today: {title}. Done already, or later?"
DUE_TODAY_WITH_DETAILS = "Due today: {title}.\n\n{details}\n\nDone already, or later?"
# Repeating chores (F6b).
OVERDUE_TEXT = "Overdue: {title} (last done {ago})"
SHARED_OVERDUE_TEXT = "Overdue for both of you: {title} (last done {ago})"
NEXT_ROUND_TEXT = " Next round: {when}."
STEP_UP_CATEGORY = "chore_step_up"
STEP_UP_EXECUTOR = "tasks.step_up"
STEP_UP_AFTER = 6  # on-time runs in a row before offering to go more often
DONE_TEXT = "Marked done: {title}. Thank you."
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


@dataclass(frozen=True)
class Run:
    done_by: int | None
    done_at: datetime
    due_on: date | None
    on_time: bool


TaskChange = str  # "created", "rescheduled", "done" or "cancelled"
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
        self.details: list[TaskDetails] = [_steps_text]

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
            schedule = f" {schedule_summary(t)}." if t.times_per_week else ""
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
            "assign_reason, due_on, created_at, steps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ),
        )
        if nudge:
            # They just said it themselves: an instant "done already, or later?" is noise.
            own = interactive and assignment.assignee.id == requester.id
            await self.prompt(
                self.get(task_id), not_before=clock.now() + FIRST_NUDGE_AFTER if own else None
            )
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
    ) -> None:
        """Nudge whoever does the task (or `member`). `overdue`: "own" or "shared" wording."""
        if task.assignee is None and member is None:
            return
        deadline = self._deadline(task)
        if not_before is not None and deadline is not None:
            not_before = min(not_before, deadline)  # a due date still wins
        if member is None:
            assert task.assignee is not None
            member = self.store.get_member(task.assignee)
        details = "\n\n".join(d for source in self.details if (d := source(task)))
        added_by = (
            self.store.get_member(task.created_by)
            if task.created_by is not None and task.created_by != member.id
            else None
        )
        goes_out = self.outbox.send_time(
            member, Priority.NORMAL, deadline=deadline, kind="task", not_before=not_before
        )
        family = self.store.get_family()
        local_day = goes_out.astimezone(ZoneInfo(family.timezone if family else "UTC")).date()
        if overdue is not None:
            template = SHARED_OVERDUE_TEXT if overdue == "shared" else OVERDUE_TEXT
            lead = template.format(title=task.title, ago=self._last_done_words(task))
            text = (
                f"{lead}.\n\n{details}\n\nDone already, or later?"
                if details
                else f"{lead}. Done already, or later?"
            )
        elif task.due_on is not None and task.due_on == local_day:
            who = f" ({added_by.name} added this for you)" if added_by is not None else ""
            text = (
                DUE_TODAY_WITH_DETAILS.format(title=f"{task.title}{who}", details=details)
                if details
                else DUE_TODAY_TEXT.format(title=f"{task.title}{who}")
            )
        elif added_by is not None:
            template = ADDED_BY_WITH_DETAILS if details else ADDED_BY_TEXT
            text = template.format(who=added_by.name, title=task.title, details=details)
        else:
            text = (
                PROMPT_WITH_DETAILS.format(title=task.title, details=details)
                if details
                else PROMPT_TEXT.format(title=task.title)
            )
        result = await self.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
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
        if task.due_on is None:
            return None
        family = self.store.get_family()
        tz = ZoneInfo(family.timezone if family else "UTC")
        due = task.due_on
        return datetime(due.year, due.month, due.day, 9, 0, tzinfo=tz)

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
        if task.times_per_week:
            return await self._complete_round(task, by, interactive)
        self.db.execute(
            "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task_id),
        )
        self._withdraw_prompt(task)
        await self._changed(self.get(task_id), "done", interactive)
        return DONE_TEXT.format(title=task.title)

    # ----- repeating chores (F6b) ------------------------------------------------

    def _today(self) -> date:
        family = self.store.get_family()
        return clock.now().astimezone(ZoneInfo(family.timezone if family else "UTC")).date()

    def _day_start(self, day: date) -> datetime:
        family = self.store.get_family()
        tz = ZoneInfo(family.timezone if family else "UTC")
        return datetime(day.year, day.month, day.day, tzinfo=tz)

    def _last_done(self, task: Task) -> datetime | None:
        value = self.db.scalar("SELECT MAX(done_at) FROM task_runs WHERE task_id = ?", (task.id,))
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
        times_per_week: float,
        minimum_days: float = 0,
        escalate_days: float = 0,
        escalate_to: str = "owner",
    ) -> Task:
        """Make a task repeat (or stop, with times_per_week 0). Zeros mean "no minimum" or
        "no escalation"."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        if times_per_week <= 0:
            self.db.execute(
                "UPDATE tasks SET times_per_week = NULL, minimum_days = NULL, "
                "escalate_days = NULL, escalate_to = NULL, shared = 0 WHERE id = ?",
                (task_id,),
            )
            return self.get(task_id)
        if times_per_week > 14:
            raise ValueError("at most 14 times a week")
        if minimum_days < 0 or escalate_days < 0:
            raise ValueError("days can't be negative")
        if minimum_days and escalate_days and escalate_days < minimum_days:
            raise ValueError("escalation has to come after the minimum, not before it")
        if escalate_to not in ("owner", "both"):
            raise ValueError("escalate_to is 'owner' or 'both'")
        self.db.execute(
            "UPDATE tasks SET times_per_week = ?, minimum_days = ?, escalate_days = ?, "
            "escalate_to = ? WHERE id = ?",
            (
                times_per_week,
                minimum_days or None,
                escalate_days or None,
                escalate_to if escalate_days else None,
                task_id,
            ),
        )
        return self.get(task_id)

    async def _complete_round(self, task: Task, by: Member, interactive: bool) -> str:
        today = self._today()
        on_time = task.due_on is None or today <= task.due_on
        assert task.times_per_week is not None
        interval = max(1, int(7 / task.times_per_week + 0.5))
        next_due = today + timedelta(days=interval)
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO task_runs (task_id, done_by, done_at, due_on, on_time) "
            "VALUES (?, ?, ?, ?, ?)",
            (task.id, by.id, now, task.due_on.isoformat() if task.due_on else None, int(on_time)),
        )
        self.db.execute(  # the next round: back to its owner, nothing overdue
            "UPDATE tasks SET status = 'open', due_on = ?, shared = 0, snoozed_until = NULL, "
            "overdue_notified_at = NULL, escalated_at = NULL WHERE id = ?",
            (next_due.isoformat(), task.id),
        )
        self._withdraw_prompt(task)
        fresh = self.get(task.id)
        await self.prompt(fresh, not_before=self._day_start(next_due))
        await self._changed(fresh, "rescheduled", interactive)
        await self._maybe_offer_step_up(fresh)
        return DONE_TEXT.format(title=task.title) + NEXT_ROUND_TEXT.format(
            when=next_due.strftime("%a %d %b")
        )

    async def check_schedules(self) -> int:
        """Scheduler job: overdue nudges past the minimum, escalation past its point.
        Each happens once per round. Returns how many tasks were nudged."""
        nudged = 0
        now = clock.now()
        rows = self.db.query(
            "SELECT * FROM tasks WHERE times_per_week IS NOT NULL AND status IN ('open', 'snoozed')"
        )
        for row in rows:
            task = _task_from_row(row)
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
        return f"{task.title}: {schedule_summary(task)} from now on."

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
            "UPDATE tasks SET due_on = ? WHERE id = ?",
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

    def _withdraw_prompt(self, task: Task) -> None:
        """Take back any of the task's nudges that haven't gone out yet (shared ones too)."""
        row = self.db.one("SELECT prompt_outbox_id FROM tasks WHERE id = ?", (task.id,))
        if row and row["prompt_outbox_id"]:
            self.outbox.cancel(row["prompt_outbox_id"])
        for queued in self.db.query(
            "SELECT id FROM outbox WHERE status = 'queued' AND dedupe_key LIKE ?",
            (f"task-{task.id}-%",),
        ):
            self.outbox.cancel(queued["id"])

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


def _days(value: float) -> str:
    return f"{value:g} day{'s' if value != 1 else ''}"


def schedule_summary(task: Task) -> str:
    """How a repeating chore reads: "Repeats 2 times a week (at least every 7 days; after 14
    days, both of you)"."""
    times = task.times_per_week
    if not times:
        return "Doesn't repeat"
    if times == 1:
        often = "Repeats once a week"
    elif times < 1:
        often = f"Repeats every {_days(round(7 / times))}"
    else:
        often = f"Repeats {times:g} times a week"
    extra = []
    if task.minimum_days:
        extra.append(f"at least every {_days(task.minimum_days)}")
    if task.escalate_days:
        who = "both of you" if task.escalate_to == "both" else "a reminder to its owner"
        extra.append(f"after {_days(task.escalate_days)}, {who}")
    return f"{often} ({'; '.join(extra)})" if extra else often


def _steps_text(task: Task) -> str | None:
    """The task's steps for its nudge, one per line, as written. Each is a `> ` quote, so the
    PDA shield keeps them word for word (steps are usually commands: "Wipe the counters")."""
    return "\n".join(f"> - {step}" for step in task.steps) or None


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
    },
)
async def create_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    due = None
    if args["due_date"]:
        try:
            due = date.fromisoformat(args["due_date"])
        except ValueError:
            return "Not created: the due date should look like 2026-11-03."
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
    "Make a chore repeat, or change or stop its schedule (times_per_week 0 stops it). "
    "at_least_every_days: overdue after that many days (0 for none). escalate_after_days: "
    "past that, escalate (0 for none); escalate_to 'both' when they want it on both partners' "
    "lists (it becomes shared until done), else 'owner'. Use it after create_task for "
    "chores like 'twice a week, at least weekly, over two weeks it's on both our lists', and "
    "for repeating reminders like 'always remind me about the bins on Tuesdays' (once a week).",
    {
        "task_id": {"type": "integer"},
        "times_per_week": {"type": "number"},
        "at_least_every_days": {"type": "number"},
        "escalate_after_days": {"type": "number"},
        "escalate_to": {"type": "string", "enum": ["owner", "both"]},
    },
)
async def set_task_schedule(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        task = await _board(ctx).set_schedule(
            args["task_id"],
            ctx.member,
            times_per_week=float(args["times_per_week"]),
            minimum_days=float(args["at_least_every_days"]),
            escalate_days=float(args["escalate_after_days"]),
            escalate_to=args["escalate_to"],
        )
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    except ValueError as exc:
        raise ToolFailed(str(exc)) from exc
    return f"Task {task.id} ({task.title}): {schedule_summary(task)}."


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
