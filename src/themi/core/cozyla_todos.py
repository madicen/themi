"""Themi's one-off tasks and a Cozyla to-do list, kept in step both ways (C1b, a trial).

Each sync (the `cozyla.sync` job, every minute) reads the configured list and
compares it with what it saw last time (`cozyla_seen`), so it can tell what
happened on the wall since:

- a new to-do: a Themi task, assigned to the matching member (else by
  matching), and nudged as usual; nobody is named as having added it;
- ticked off: done; deleted: cancelled; a new title or due date: copied over.
  Reopening and reassigning on the wall are only logged in this trial.

Then Themi's own changes go out. Every task change marks the task's link
pending, and the sync makes the to-do match: created, edited (title, due
date, assignee), ticked off or reopened, or deleted when the task is
cancelled. A task still pending wins over a change on the wall. Repeating
chores stay off the list (they're closer to Cozyla's chore chart).

The first sync of a list links open to-dos to open tasks with the same title,
brings the other open ones in without nudging (it's a list the family already
keeps), leaves ticked-off ones alone, and sends Themi's open one-off tasks.

Like the OurGroceries mirror, configuring the list is the go-ahead for
keeping it in step, so these writes don't ask each time. A failed read backs
off from a minute to an hour; a failed write retries the same way.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.connectors.cozyla import CozylaClient, CozylaError, CozylaMember, Todo
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

MAX_BACKOFF = timedelta(hours=1)
# Wall to-dos say nothing about the kind of job, so they come in as a light errand.
WALL_KIND, WALL_EFFORT = "errand", 2


def backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), MAX_BACKOFF)


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


@dataclass(frozen=True)
class Seen:
    title: str
    assignee: str | None
    due_on: date | None
    completed: bool


class CozylaTodos:
    def __init__(self, services: Services, board: TaskBoard, client: CozylaClient) -> None:
        self.services = services
        self.board = board
        self.client = client
        self.db = services.store.db
        self._applying = False  # making the wall's changes in Themi: not to be sent back
        self._read_failures = 0
        self._read_after: datetime | None = None
        self._to_member: dict[str, int] = {}  # Cozyla member id -> Themi member id
        self._to_cozyla: dict[int, str] = {}

    def install(self) -> None:
        self.board.change_listeners.append(self.on_task_changed)

    async def on_task_changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        if self._applying:
            return
        if task.repeats and not self._link(task.id):
            return
        self._mark(task.id)

    # ----- the job ----------------------------------------------------------------------

    async def sync(self) -> int:
        """Scheduler job: bring in the wall's changes, then send Themi's. Returns how many
        of Themi's changes now match."""
        if self._read_after is not None and clock.now() < self._read_after:
            return 0
        try:
            list_id = await self._list_id()
            todos = [t for t in await self.client.todos() if t.list_id == list_id]
            members = await self.client.members()
        except CozylaError as exc:
            log.warning("Cozyla sync waits: %s", exc)
            self._read_failures += 1
            self._read_after = clock.now() + backoff(self._read_failures)
            return 0
        self._read_failures, self._read_after = 0, None
        self._to_member = self._member_map(members)
        self._to_cozyla = {mid: uid for uid, mid in self._to_member.items()}
        seen = self._seen(list_id)
        self._applying = True
        try:
            if seen is None:
                await self._import(todos)
            else:
                await self._pull(todos, seen)
        finally:
            self._applying = False
        current = {t.id: t for t in todos}
        done = await self._push(list_id, current)
        self._remember(list_id, current.values())
        return done

    async def _list_id(self) -> str:
        wanted = self.client.config.todo_list
        for todo_list in await self.client.lists():
            if _same(todo_list.title, wanted):
                return todo_list.id
        raise CozylaError(f"Cozyla has no to-do list called {wanted!r}")

    def _member_map(self, members: list[CozylaMember]) -> dict[str, int]:
        """Cozyla member id -> Themi member id, by first name."""
        themi = {m.name.split()[0].casefold(): m.id for m in self.services.store.list_members()}
        found = {}
        for member in members:
            first = member.name.split()[0].casefold() if member.name.split() else ""
            if first in themi:
                found[member.id] = themi[first]
        return found

    # ----- what changed on the wall -------------------------------------------------------

    async def _import(self, todos: list[Todo]) -> None:
        """The first sync of this list."""
        for todo in todos:
            if todo.completed or self._link_for(todo.id):
                continue
            match = self._open_unlinked(todo.title)
            if match is not None:
                self._linked(match.id, todo.id)
            else:
                await self._bring_in(todo, nudge=False)
        # Themi's open one-off tasks that aren't on the wall go onto it.
        for row in self.db.query("SELECT id FROM tasks WHERE status IN ('open', 'snoozed')"):
            task = self.board.get(row["id"])
            link = self._link(task.id)
            if not task.repeats and (link is None or link["todo_id"] is None):
                self._mark(task.id)

    async def _pull(self, todos: list[Todo], seen: dict[str, Seen]) -> None:
        current = {t.id for t in todos}
        for todo in todos:
            before = seen.get(todo.id)
            link = self._link_for(todo.id)
            if link is None:
                if before is None and not todo.completed:
                    await self._bring_in(todo, nudge=True)
                continue
            if link["state"] == "pending":
                continue  # Themi changed it since: its change wins
            task = self.board.get(link["task_id"])
            if task.status in ("done", "cancelled") or before is None:
                continue
            if todo.completed and not before.completed:
                await self.board.complete(task.id, self._doer(task))
                continue
            if before.completed and not todo.completed:
                log.info("Cozyla to-do %s was reopened on the wall; not followed yet", todo.id)
            if todo.assignee != before.assignee:
                log.info("Cozyla to-do %s was reassigned on the wall; not followed yet", todo.id)
            if todo.title.strip() and todo.title != before.title:
                await self.board.update(task.id, self._admin(), title=todo.title)
            due_on = self._due_on(todo)
            if due_on != before.due_on:
                await self.board.reschedule(task.id, due_on)
        for todo_id in seen.keys() - current:
            link = self._link_for(todo_id)
            if link is None or link["state"] == "pending":
                continue
            task = self.board.get(link["task_id"])
            if task.status in ("open", "snoozed"):
                await self.board.cancel(task.id, self._admin())
            self.db.execute("UPDATE cozyla_links SET todo_id = NULL WHERE task_id = ?", (task.id,))

    async def _bring_in(self, todo: Todo, *, nudge: bool) -> None:
        title = todo.title.strip()
        if not title:
            return
        member_id = self._to_member.get(todo.assignee or "")
        assignee = self.services.store.get_member(member_id) if member_id else None
        task = await self.board.create(
            assignee or self._admin(),
            title,
            WALL_KIND,
            WALL_EFFORT,
            self._due_on(todo),
            nudge=False,
            assignee=assignee,
        )
        # Added on the wall: nobody is known to have added it, so the nudge names no one.
        self.db.execute("UPDATE tasks SET created_by = NULL WHERE id = ?", (task.id,))
        self._linked(task.id, todo.id)
        if nudge:
            await self.board.prompt(self.board.get(task.id))

    # ----- what changed in Themi ----------------------------------------------------------

    def _due(self) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM cozyla_links WHERE state = 'pending' "
            "AND (retry_after IS NULL OR retry_after <= ?) ORDER BY task_id",
            (to_utc_iso(clock.now()),),
        )

    async def _push(self, list_id: str, current: dict[str, Todo]) -> int:
        done = 0
        for link in self._due():
            task = self.board.get(link["task_id"])
            todo = current.get(link["todo_id"] or "")
            try:
                todo_id = await self._send(list_id, task, todo, current)
            except CozylaError as exc:
                log.warning("Cozyla sync of task %s waits: %s", task.id, exc)
                self._failed(link, str(exc))
                continue
            if task.repeats:
                self.db.execute(
                    "DELETE FROM cozyla_links WHERE task_id = ? AND version = ?",
                    (task.id, link["version"]),
                )
            else:
                self.db.execute(
                    "UPDATE cozyla_links SET state = 'done', todo_id = ?, attempts = 0, "
                    "retry_after = NULL, error = NULL WHERE task_id = ? AND version = ?",
                    (todo_id, task.id, link["version"]),  # unless it changed meanwhile
                )
            done += 1
        return done

    async def _send(
        self, list_id: str, task: Task, todo: Todo | None, current: dict[str, Todo]
    ) -> str | None:
        """Make the wall match the task; returns its to-do's id, if it still has one."""
        if task.status == "cancelled" or task.repeats:
            if todo is not None:
                await self.client.delete(todo.id)
                del current[todo.id]
            return None
        if task.status == "done":
            if todo is not None and not todo.completed:
                await self.client.set_done(todo.id, True)
                current[todo.id] = replace(todo, completed=True)
            return todo.id if todo else None
        assignee = self._to_cozyla.get(task.assignee) if task.assignee else None
        due = self._due_at(task.due_on)
        if todo is None:
            todo_id = await self.client.create(list_id, task.title, assignee=assignee, due=due)
            current[todo_id] = Todo(todo_id, list_id, task.title, assignee, due, False)
            return todo_id
        if (todo.title, todo.assignee, self._due_on(todo)) != (task.title, assignee, task.due_on):
            await self.client.update(todo, title=task.title, assignee=assignee, due=due)
            todo = current[todo.id] = replace(todo, title=task.title, assignee=assignee, due=due)
        if todo.completed:
            await self.client.set_done(todo.id, False)
            current[todo.id] = replace(todo, completed=False)
        return todo.id

    # ----- links and the snapshot ---------------------------------------------------------

    def _link(self, task_id: int) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM cozyla_links WHERE task_id = ?", (task_id,))

    def _link_for(self, todo_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM cozyla_links WHERE todo_id = ?", (todo_id,))

    def _mark(self, task_id: int) -> None:
        self.db.execute(
            "INSERT INTO cozyla_links (task_id) VALUES (?) ON CONFLICT(task_id) DO UPDATE SET "
            "state = 'pending', version = version + 1, attempts = 0, retry_after = NULL",
            (task_id,),
        )

    def _linked(self, task_id: int, todo_id: str) -> None:
        self.db.execute(
            "INSERT INTO cozyla_links (task_id, todo_id, state) VALUES (?, ?, 'done') "
            "ON CONFLICT(task_id) DO UPDATE SET todo_id = excluded.todo_id, state = 'done'",
            (task_id, todo_id),
        )

    def _open_unlinked(self, title: str) -> Task | None:
        for row in self.db.query(
            "SELECT t.id, t.title FROM tasks t LEFT JOIN cozyla_links l ON l.task_id = t.id "
            "WHERE t.status IN ('open', 'snoozed') AND l.todo_id IS NULL ORDER BY t.id"
        ):
            if _same(row["title"], title):
                task = self.board.get(row["id"])
                if not task.repeats:
                    return task
        return None

    def _failed(self, link: dict[str, Any], error: str) -> None:
        attempts = link["attempts"] + 1
        self.db.execute(
            "UPDATE cozyla_links SET attempts = ?, retry_after = ?, error = ? WHERE task_id = ?",
            (attempts, to_utc_iso(clock.now() + backoff(attempts)), error[:300], link["task_id"]),
        )

    def _seen(self, list_id: str) -> dict[str, Seen] | None:
        if not self.db.one("SELECT 1 FROM cozyla_sync WHERE list_id = ?", (list_id,)):
            return None
        return {
            r["todo_id"]: Seen(
                r["title"],
                r["assignee"],
                date.fromisoformat(r["due_on"]) if r["due_on"] else None,
                bool(r["completed"]),
            )
            for r in self.db.query("SELECT * FROM cozyla_seen WHERE list_id = ?", (list_id,))
        }

    def _remember(self, list_id: str, todos: Iterable[Todo]) -> None:
        self.db.execute("DELETE FROM cozyla_seen WHERE list_id = ?", (list_id,))
        for todo in todos:
            due_on = self._due_on(todo)
            self.db.execute(
                "INSERT INTO cozyla_seen (list_id, todo_id, title, assignee, due_on, completed) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    list_id,
                    todo.id,
                    todo.title,
                    todo.assignee,
                    due_on.isoformat() if due_on else None,
                    int(todo.completed),
                ),
            )
        self.db.execute(
            "INSERT INTO cozyla_sync (list_id, synced_at) VALUES (?, ?) "
            "ON CONFLICT(list_id) DO UPDATE SET synced_at = excluded.synced_at",
            (list_id, to_utc_iso(clock.now())),
        )

    # ----- small things -------------------------------------------------------------------

    @property
    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _due_on(self, todo: Todo) -> date | None:
        return todo.due.astimezone(self._tz).date() if todo.due else None

    def _due_at(self, due_on: date | None) -> datetime | None:
        """Themi keeps a date; the wall a moment: the start of that day, locally."""
        if due_on is None:
            return None
        return datetime(due_on.year, due_on.month, due_on.day, tzinfo=self._tz)

    def _admin(self) -> Member:
        return next(m for m in self.services.store.list_members() if m.is_admin)

    def _doer(self, task: Task) -> Member:
        if task.assignee is not None:
            return self.services.store.get_member(task.assignee)
        return self._admin()
