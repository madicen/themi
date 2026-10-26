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

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound
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
    )


class TaskBoard:
    def __init__(self, services: Services, matcher: Matcher) -> None:
        self.services = services
        self.matcher = matcher
        self.store = services.store
        self.db = services.store.db
        self.change_listeners: list[TaskListener] = []
        self.details: list[TaskDetails] = []

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
        s.button_handlers["task"] = self.on_button
        s.open_item_sources.append(self.open_items)

    # ----- reading ------------------------------------------------------------

    def get(self, task_id: int) -> Task:
        row = self.db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise NotFound(f"no task with id {task_id}")
        return _task_from_row(row)

    def open_for(self, member: Member) -> list[Task]:
        rows = self.db.query(
            "SELECT * FROM tasks WHERE assignee = ? AND status IN ('open', 'snoozed') "
            "ORDER BY due_on IS NULL, due_on, id",
            (member.id,),
        )
        return [_task_from_row(r) for r in rows]

    def open_items(self, member: Member) -> list[OpenItem]:
        items = []
        for t in self.open_for(member):
            due = f", due {t.due_on.isoformat()}" if t.due_on else ""
            items.append(OpenItem(f"Task {t.id} (theirs{due}): {t.title}"))
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
    ) -> Task:
        """Add and assign a task. With `nudge=False` the caller sends `prompt()` itself
        (after attaching details, like a call script). An `assignee` (someone took it on,
        or was named) skips matching; without one, matching decides."""
        title = title.strip().rstrip(".")
        if not title:
            raise ValueError("a task needs a title")
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
            "assign_reason, due_on, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    async def prompt(self, task: Task, *, not_before: datetime | None = None) -> None:
        if task.assignee is None:
            return
        deadline = self._deadline(task)
        if not_before is not None and deadline is not None:
            not_before = min(not_before, deadline)  # a due date still wins
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
        if task.due_on is not None and task.due_on == local_day:
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

    async def complete(self, task_id: int, by: Member, *, interactive: bool = False) -> str:
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        self.db.execute(
            "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task_id),
        )
        self._withdraw_prompt(task)
        await self._changed(self.get(task_id), "done", interactive)
        return DONE_TEXT.format(title=task.title)

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
        row = self.db.one("SELECT prompt_outbox_id FROM tasks WHERE id = ?", (task.id,))
        if row and row["prompt_outbox_id"]:
            self.outbox.cancel(row["prompt_outbox_id"])  # if it hasn't gone out yet

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
