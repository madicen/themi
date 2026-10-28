"""The family calendar (for Cozyla): tasks with due dates become all-day events.

- A task that gets a date is staged as `calendar_write` ("Put ... on the
  family calendar?"), so it waits for a yes unless a locked rule made the
  category automatic. Approving records the event and queues it. Not a task
  someone made for themselves: that's their own reminder (idea #23). Not when
  the Cozyla wall's to-do lists are synced either: the wall shows the task
  there, so an event would be the same thing twice (bug #52).
- The write itself is the queued `calendar.sync` job, so a Google error is
  retried by the job queue with its back-off, and never blocks the task.
- Once an event is on the calendar, it follows its task: a new date moves
  it, done marks it "Done: ...", and cancelling or dropping the date removes
  it. That yes covered keeping the event true, so these don't ask again.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from themi import clock
from themi.autonomy import ExecutionContext
from themi.connectors.gcal import CalendarSync, event_id
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange
from themi.localtime import to_utc_iso
from themi.scheduler import Scheduler

log = logging.getLogger(__name__)

CATEGORY = "calendar_write"
EXECUTOR = "calendar.write_task"
JOB = "calendar.sync"
OPEN = ("pending", "snoozed", "failed")


def event_body(task: Task, assignee_name: str | None) -> dict[str, Any]:
    assert task.due_on is not None
    title = f"Done: {task.title}" if task.status == "done" else task.title
    who = f"For {assignee_name}. " if assignee_name else ""
    return {
        "summary": title,
        "description": f"{who}From Themi's task list.",
        "start": {"date": task.due_on.isoformat()},
        "end": {"date": (task.due_on + timedelta(days=1)).isoformat()},
        "transparency": "transparent",  # a reminder, not a busy block
        "extendedProperties": {"private": {"themi": f"task:{task.id}"}},
    }


def _personal(task: Task) -> bool:
    """A task someone made for themselves (or that came from the wall with nobody named),
    not shared or for either of them: a reminder of theirs, not the family's business."""
    if task.shared or task.either:
        return False
    return task.created_by is None or task.created_by == task.assignee


def approval_summary(task: Task) -> str:
    """An offer, not an order, so the PDA shield never has to rewrite it."""
    assert task.due_on is not None
    return f"For the family calendar: {task.title}, {task.due_on.strftime('%a %b %-d')}"


class TaskCalendar:
    def __init__(
        self, services: Services, board: TaskBoard, sync: CalendarSync, jobs: Scheduler
    ) -> None:
        self.services = services
        self.board = board
        self.sync = sync
        self.jobs = jobs
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.board.change_listeners.append(self.on_task_changed)
        self.services.autonomy.executors.register(EXECUTOR)(self._execute)
        self.jobs.handler(JOB)(self.run_job)

    # ----- following tasks ------------------------------------------------------

    def _event(self, task_id: int) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM calendar_events WHERE source = 'task' AND source_id = ?", (task_id,)
        )

    def _waiting(self, task_id: int) -> bool:
        rows = self.db.query(
            f"SELECT payload FROM pending_actions WHERE category = ? AND executor = ? "
            f"AND status IN ({', '.join('?' for _ in OPEN)})",
            (CATEGORY, EXECUTOR, *OPEN),
        )
        return any(f'"task_id": {task_id}' in r["payload"] for r in rows)

    async def on_task_changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        if self._event(task.id) is not None:
            self.queue(task.id)  # already on the calendar: keep it true
            return
        if change not in ("created", "rescheduled") or task.due_on is None:
            return
        if task.status not in ("open", "snoozed") or self._waiting(task.id):
            return
        if _personal(task):
            return  # theirs alone: not for the family calendar (Erin's idea #23)
        if self.services.wall is not None:
            return  # the wall's own lists show tasks: not an event as well (bug #52)
        if self.sync.account() is None:
            log.info("Task %s has a date, but there's no calendar to put it on yet", task.id)
            return
        member_id = task.created_by or task.assignee
        if member_id is None:
            return
        member = self.store.get_member(member_id)
        await self.services.autonomy.stage(
            CATEGORY,
            member,
            approval_summary(task),
            {"task_id": task.id},
            EXECUTOR,
            interactive=interactive,
        )

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        task = self.board.get(int(payload["task_id"]))
        family = self.store.get_family()
        seed = family.created_at.isoformat() if family else "themi"
        self.db.execute(
            "INSERT INTO calendar_events (source, source_id, event_id, created_at) "
            "VALUES ('task', ?, ?, ?) ON CONFLICT (source, source_id) DO NOTHING",
            (task.id, event_id("task", task.id, seed), to_utc_iso(clock.now())),
        )
        self.queue(task.id)
        return "It'll show on the family calendar in a few minutes."

    def queue(self, task_id: int) -> None:
        self.jobs.enqueue(
            JOB, {"source": "task", "id": task_id}, dedupe_key=f"{JOB}:task:{task_id}"
        )

    # ----- writing ----------------------------------------------------------------

    async def run_job(self, payload: dict[str, Any]) -> str:
        """Queued job: make the calendar match the task. Raises (and is retried) on errors."""
        task_id = int(payload["id"])
        row = self._event(task_id)
        if row is None:
            return "not approved"
        task = self.board.get(task_id)
        if task.status == "cancelled" or task.due_on is None:
            if row["state"] != "deleted" and row["calendar_id"] and row["account_id"]:
                await self.sync.delete(row["account_id"], row["calendar_id"], row["event_id"])
            self._mark(row["id"], "deleted")
            return "removed"
        account_id, calendar_id = row["account_id"], row["calendar_id"]
        if account_id is None or calendar_id is None:
            target = await self.sync.target()
            account_id, calendar_id = target.account.id, target.calendar_id
            self.db.execute(
                "UPDATE calendar_events SET account_id = ?, calendar_id = ? WHERE id = ?",
                (account_id, calendar_id, row["id"]),
            )
        assignee = self.store.get_member(task.assignee).name if task.assignee else None
        await self.sync.upsert(account_id, calendar_id, row["event_id"], event_body(task, assignee))
        self._mark(row["id"], "synced")
        return "written"

    def _mark(self, row_id: int, state: str) -> None:
        self.db.execute(
            "UPDATE calendar_events SET state = ?, synced_at = ? WHERE id = ?",
            (state, to_utc_iso(clock.now()), row_id),
        )
