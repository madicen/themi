"""Themi's one-off tasks and the to-do lists on a Cozyla wall, kept in step both ways
(C1b, a trial; C1c: every list, reassigning, and naming a list).

Each sync (the `cozyla.sync` job, every minute) reads every list on the wall and
compares it with what it saw last time (`cozyla_seen`), so it can tell what
happened on the wall since:

- a new to-do on the configured list, or on any list if it's assigned to
  someone: a Themi task for that person, nudged as usual; nobody is named as
  having added it. Assigned to the family member (Cozyla's "Madicen Family"),
  it's shared: on both lists, nudged to both. Unassigned items on other lists
  ("Things to Cook") are lists, not jobs: Themi's lists keep them (L1b,
  `themi.core.cozyla_lists`, handed the same read);
- ticked off: done; ticked back: open again; deleted: cancelled; reassigned:
  the task goes to that person (or to both); moved to another list: the task
  stays on it; a new title or due date: copied over.

Then Themi's own changes go out. Every task change marks the task's link
pending, and the sync makes the to-do match: created, edited (title, due
date, assignee), ticked off or reopened, moved to the list it belongs on, or
deleted when the task is cancelled. A task goes on the configured list unless
someone put it on another (`put_task_on_wall_list`). A task still pending wins
over a change on the wall. Repeating chores stay off the lists (they're closer
to Cozyla's chore chart).

Last, Themi's own to-dos on the configured list are put in order (F18d, Erin's
idea #75): due or overdue first, important before the rest, then by due date. The
wall goes by each to-do's `profileDisplayOrder`, highest at the top. Themi's own
swap places among the positions they already have, so to-dos added on the wall
(their tasks have no creator) stay exactly where they are. Dates never change.

The first sync of a list links open to-dos to open tasks with the same title
and brings the rest in. Assigned ones are nudged at low priority, so a list the
family already keeps trickles out within daily limits; unassigned ones come in
quietly. The configured list's first sync also sends Themi's open one-off
tasks. Ticked-off to-dos are left alone.

Like the OurGroceries mirror, configuring the list is the go-ahead for
keeping tasks in step, so those writes don't ask each time. A failed read
backs off from a minute to an hour; a failed write retries the same way.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound
from themi.channels.outbox import Priority
from themi.connectors.cozyla import CozylaClient, CozylaError, CozylaMember, Todo, TodoList
from themi.core.cozyla_lists import WallLists
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

MAX_BACKOFF = timedelta(hours=1)
# Wall to-dos say nothing about the kind of job, so they come in as a light errand.
WALL_KIND, WALL_EFFORT = "errand", 2
END_OF_DAY = time(23, 59)


def backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), MAX_BACKOFF)


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def member_map(members: list[CozylaMember], themi: list[Member]) -> dict[str, int]:
    """Cozyla member id -> Themi member id, by first name."""
    firsts = {m.name.split()[0].casefold(): m.id for m in themi}
    found = {}
    for member in members:
        first = member.name.split()[0].casefold() if member.name.split() else ""
        if first in firsts:
            found[member.id] = firsts[first]
    return found


def family_member(members: list[CozylaMember], mapped: dict[str, int]) -> str | None:
    """The member that isn't a person: "Madicen Family". Assigned to it means both."""
    for member in members:
        if member.id not in mapped and "family" in member.name.casefold():
            return member.id
    return None


@dataclass(frozen=True)
class Seen:
    list_id: str
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
        self._family: str | None = None  # the Cozyla member that stands for everyone
        self._default: str | None = None  # the configured list's id
        self.wall_lists: WallLists | None = None  # Themi's lists on the wall (L1b)

    def install(self) -> None:
        self.board.change_listeners.append(self.on_task_changed)
        self.services.wall = self
        self.services.tools.register(put_task_on_wall_list)
        self.board.wall_notes.append(self.where)
        if self.services.lists is not None:
            self.wall_lists = WallLists(self.services, self.services.lists, self.client)
            self.wall_lists.install()

    def where(self, task: Task) -> str | None:
        """Which wall list a task is on, for the model."""
        link = self._link(task.id)
        if link is None or _off_the_lists(task) or task.status not in ("open", "snoozed"):
            return None
        lists = self.lists()
        name = lists.get(link["list_id"] or "") or self.client.config.todo_list
        if link["todo_id"] is None:
            return f"On the wall's {name} list (being added now)."
        return f"On the wall's {name} list."

    async def on_task_changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        if self._applying:
            return
        if _not_a_todo(task) and not self._link(task.id):
            return
        self._mark(task.id)

    # ----- the job ----------------------------------------------------------------------

    async def sync(self) -> int:
        """Scheduler job: bring in the wall's changes, then send Themi's. Returns how many
        of Themi's changes now match."""
        if self._read_after is not None and clock.now() < self._read_after:
            return 0
        try:
            lists = await self.client.lists()
            default = self._find(lists, self.client.config.todo_list)
            if default is None:
                raise CozylaError(
                    f"Cozyla has no to-do list called {self.client.config.todo_list!r}"
                )
            todos = await self.client.todos()
            members = await self.client.members()
        except CozylaError as exc:
            log.warning("Cozyla sync waits: %s", exc)
            self._read_failures += 1
            self._read_after = clock.now() + backoff(self._read_failures)
            return 0
        self._read_failures, self._read_after = 0, None
        self._default = default.id
        self._to_member = member_map(members, self.services.store.list_members())
        self._to_cozyla = {mid: uid for uid, mid in self._to_member.items()}
        self._family = family_member(members, self._to_member)
        titles = {t.id: t.title for t in lists}
        todos = [t for t in todos if t.list_id in titles]
        synced = {r["list_id"] for r in self.db.query("SELECT list_id FROM cozyla_sync")}
        self._applying = True
        try:
            await self._pull(todos, self._seen(), synced)
        finally:
            self._applying = False
        current = {t.id: t for t in todos}
        done = await self._push(current)
        try:
            await self._order(current, default.id)
        except CozylaError as exc:
            log.warning("Cozyla to-do order waits: %s", exc)
        if self.wall_lists is not None:
            tasks = {
                r["todo_id"]
                for r in self.db.query("SELECT todo_id FROM cozyla_links WHERE todo_id IS NOT NULL")
            }
            await self.wall_lists.sync(lists, list(current.values()), {default.id}, tasks)
        self._remember(titles, current.values())
        return done

    @staticmethod
    def _find(lists: Iterable[TodoList], name: str) -> TodoList | None:
        return next((t for t in lists if _same(t.title, name)), None)

    def _assigned(self, assignee: str | None) -> bool:
        return assignee is not None and (assignee in self._to_member or assignee == self._family)

    def _wanted(self, list_id: str, assignee: str | None) -> bool:
        """A to-do that's a Themi task: anything on the configured list, and anything
        assigned to someone on the others."""
        return list_id == self._default or self._assigned(assignee)

    # ----- the tools' side ----------------------------------------------------------------

    def lists(self) -> dict[str, str]:
        """The wall's lists as of the last sync: id -> name."""
        return {r["list_id"]: r["title"] for r in self.db.query("SELECT * FROM cozyla_sync")}

    def find_list(self, name: str) -> tuple[str, str] | None:
        return next(((i, t) for i, t in self.lists().items() if _same(t, name)), None)

    def default_list(self) -> str | None:
        found = self.find_list(self.client.config.todo_list)
        return found[0] if found else None

    def put_on(self, task_id: int, list_id: str) -> None:
        self.db.execute("UPDATE tasks SET on_chart = 0 WHERE id = ?", (task_id,))  # off the chart
        self.db.execute(
            "INSERT INTO cozyla_links (task_id, list_id) VALUES (?, ?) ON CONFLICT(task_id) "
            "DO UPDATE SET list_id = excluded.list_id, state = 'pending', "
            "version = version + 1, attempts = 0, retry_after = NULL",
            (task_id, list_id),
        )

    # ----- what changed on the wall -------------------------------------------------------

    async def _pull(self, todos: list[Todo], seen: dict[str, Seen], synced: set[str]) -> None:
        for todo in todos:
            link = self._link_for(todo.id)
            before = seen.get(todo.id)
            if link is None:
                await self._maybe_bring_in(todo, before, first=todo.list_id not in synced)
            else:
                await self._follow(todo, before, link)
        for todo_id in seen.keys() - {t.id for t in todos}:
            link = self._link_for(todo_id)
            if link is None or link["state"] == "pending":
                continue
            task = self.board.get(link["task_id"])
            if task.status in ("open", "snoozed"):
                await self.board.cancel(task.id, self._admin())
            self.db.execute("UPDATE cozyla_links SET todo_id = NULL WHERE task_id = ?", (task.id,))
        if self._default not in synced:
            # The configured list's first sync: Themi's open one-off tasks go onto it.
            for row in self.db.query("SELECT id FROM tasks WHERE status IN ('open', 'snoozed')"):
                task = self.board.get(row["id"])
                link = self._link(task.id)
                if not _not_a_todo(task) and (link is None or link["todo_id"] is None):
                    self._mark(task.id)

    async def _maybe_bring_in(self, todo: Todo, before: Seen | None, *, first: bool) -> None:
        if todo.completed or not self._wanted(todo.list_id, todo.assignee):
            return
        if first:  # the first sync of this list
            match = self._open_unlinked(todo.title)
            if match is not None:
                self._linked(match.id, todo.id, todo.list_id)
                return
            nudge = Priority.LOW if self._assigned(todo.assignee) else None
            await self._bring_in(todo, nudge)
        elif before is None or not self._wanted(before.list_id, before.assignee):
            await self._bring_in(todo, Priority.NORMAL)  # new, or newly someone's

    async def _follow(self, todo: Todo, before: Seen | None, link: dict[str, Any]) -> None:
        if link["state"] == "pending":
            return  # Themi changed it since: its change wins
        task = self.board.get(link["task_id"])
        if link["list_id"] != todo.list_id:  # moved on the wall: it stays where it went
            self.db.execute(
                "UPDATE cozyla_links SET list_id = ? WHERE task_id = ?", (todo.list_id, task.id)
            )
        if before is None or task.status == "cancelled":
            return
        if todo.completed and not before.completed:
            if task.status in ("open", "snoozed"):
                await self.board.complete(task.id, self._doer(task))
            return
        if before.completed and not todo.completed and task.status == "done":
            task = await self.board.reopen(task.id)
        if task.status not in ("open", "snoozed"):
            return
        if todo.assignee != before.assignee:
            await self._reassigned(task, todo)
        if todo.title.strip() and todo.title != before.title:
            await self.board.update(task.id, self._admin(), title=todo.title)
        due_on = self._due_on(todo)
        if due_on != before.due_on:
            await self.board.reschedule(task.id, due_on)

    async def _reassigned(self, task: Task, todo: Todo) -> None:
        if todo.assignee is not None and todo.assignee == self._family:
            await self.board.reassign(task.id, None, shared=True)
            return
        member_id = self._to_member.get(todo.assignee or "")
        if member_id is None:
            log.info(
                "Cozyla to-do %s was unassigned on the wall; task %s keeps its person",
                todo.id,
                task.id,
            )
            return
        await self.board.reassign(task.id, self.services.store.get_member(member_id))

    async def _bring_in(self, todo: Todo, nudge: Priority | None) -> None:
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
        shared = todo.assignee is not None and todo.assignee == self._family
        # Added on the wall: nobody is known to have added it, so the nudge names no one.
        self.db.execute(
            "UPDATE tasks SET created_by = NULL, shared = ? WHERE id = ?", (int(shared), task.id)
        )
        self._linked(task.id, todo.id, todo.list_id)
        if nudge is None:
            return
        task = self.board.get(task.id)
        people: list[Member | None] = [*self._everyone()] if shared else [None]
        for person in people:
            await self.board.prompt(task, member=person, priority=nudge)

    # ----- what changed in Themi ----------------------------------------------------------

    def _due(self) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM cozyla_links WHERE state = 'pending' "
            "AND (retry_after IS NULL OR retry_after <= ?) ORDER BY task_id",
            (to_utc_iso(clock.now()),),
        )

    async def _push(self, current: dict[str, Todo]) -> int:
        done = 0
        for link in self._due():
            task = self.board.get(link["task_id"])
            todo = current.get(link["todo_id"] or "")
            try:
                todo_id = await self._send(link, task, todo, current)
            except CozylaError as exc:
                log.warning("Cozyla sync of task %s waits: %s", task.id, exc)
                self._failed(link, str(exc))
                continue
            if _off_the_lists(task):
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
        self, link: dict[str, Any], task: Task, todo: Todo | None, current: dict[str, Todo]
    ) -> str | None:
        """Make the wall match the task; returns its to-do's id, if it still has one."""
        if task.status == "cancelled" or _off_the_lists(task):
            if todo is not None:  # gone, or a chore, on the chart, or Themi's own: off the lists
                await self.client.delete(todo.id)
                del current[todo.id]
            return None
        if task.status == "done":
            if todo is not None and not todo.completed:
                await self.client.set_done(todo.id, True)
                current[todo.id] = replace(todo, completed=True)
            return todo.id if todo else None
        target = link["list_id"] or (todo.list_id if todo else self._default)
        assert target is not None
        if todo is not None and todo.list_id != target:  # put on another list in Themi
            await self.client.delete(todo.id)
            del current[todo.id]
            todo = None
        assignee = self._assignee_for(task)
        due = self._due_at(task)
        if todo is None:
            todo_id = await self.client.create(target, task.title, assignee=assignee, due=due)
            current[todo_id] = Todo(todo_id, target, task.title, assignee, due, False)
            return todo_id
        if (todo.title, todo.assignee, todo.due) != (task.title, assignee, due):
            await self.client.update(todo, title=task.title, assignee=assignee, due=due)
            todo = current[todo.id] = replace(todo, title=task.title, assignee=assignee, due=due)
        if todo.completed:
            await self.client.set_done(todo.id, False)
            current[todo.id] = replace(todo, completed=False)
        return todo.id

    async def _order(self, current: dict[str, Todo], list_id: str) -> None:
        """Themi's own open to-dos on the list in order, in the places they already hold."""
        today = clock.now().astimezone(self._tz).date()
        mine: list[tuple[Task, Todo]] = []
        for row in self.db.query(
            "SELECT l.task_id, l.todo_id FROM cozyla_links l JOIN tasks t ON t.id = l.task_id "
            "WHERE l.todo_id IS NOT NULL AND t.created_by IS NOT NULL "
            "AND t.status IN ('open', 'snoozed')"
        ):
            todo = current.get(row["todo_id"])
            if todo is None or todo.list_id != list_id or todo.completed:
                continue
            if not isinstance(todo.raw.get("profileDisplayOrder"), int | float):
                continue  # just made: placed from the next read
            mine.append((self.board.get(row["task_id"]), todo))
        ranked = sorted(mine, key=lambda pair: _rank(pair[0], today))
        profiles = sorted((float(t.raw["profileDisplayOrder"]) for _, t in mine), reverse=True)
        displays = sorted((float(t.raw.get("displayOrder") or 0) for _, t in mine), reverse=True)
        for (_, todo), profile, display in zip(ranked, profiles, displays, strict=True):
            if float(todo.raw["profileDisplayOrder"]) != profile:
                await self.client.place(todo, display, profile)

    def _assignee_for(self, task: Task) -> str | None:
        if task.shared and self._family is not None:
            return self._family
        return self._to_cozyla.get(task.assignee) if task.assignee else None

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

    def _linked(self, task_id: int, todo_id: str, list_id: str) -> None:
        self.db.execute(
            "INSERT INTO cozyla_links (task_id, todo_id, state, list_id) VALUES (?, ?, 'done', ?) "
            "ON CONFLICT(task_id) DO UPDATE SET todo_id = excluded.todo_id, state = 'done', "
            "list_id = excluded.list_id",
            (task_id, todo_id, list_id),
        )

    def _open_unlinked(self, title: str) -> Task | None:
        for row in self.db.query(
            "SELECT t.id, t.title FROM tasks t LEFT JOIN cozyla_links l ON l.task_id = t.id "
            "WHERE t.status IN ('open', 'snoozed') AND l.todo_id IS NULL ORDER BY t.id"
        ):
            if _same(row["title"], title):
                task = self.board.get(row["id"])
                if not _not_a_todo(task):
                    return task
        return None

    def _failed(self, link: dict[str, Any], error: str) -> None:
        attempts = link["attempts"] + 1
        self.db.execute(
            "UPDATE cozyla_links SET attempts = ?, retry_after = ?, error = ? WHERE task_id = ?",
            (attempts, to_utc_iso(clock.now() + backoff(attempts)), error[:300], link["task_id"]),
        )

    def _seen(self) -> dict[str, Seen]:
        return {
            r["todo_id"]: Seen(
                r["list_id"],
                r["title"],
                r["assignee"],
                date.fromisoformat(r["due_on"]) if r["due_on"] else None,
                bool(r["completed"]),
            )
            for r in self.db.query("SELECT * FROM cozyla_seen")
        }

    def _remember(self, titles: dict[str, str], todos: Iterable[Todo]) -> None:
        self.db.execute("DELETE FROM cozyla_seen")
        for todo in todos:
            due_on = self._due_on(todo)
            self.db.execute(
                "INSERT INTO cozyla_seen (list_id, todo_id, title, assignee, due_on, completed) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    todo.list_id,
                    todo.id,
                    todo.title,
                    todo.assignee,
                    due_on.isoformat() if due_on else None,
                    int(todo.completed),
                ),
            )
        now = to_utc_iso(clock.now())
        for list_id, title in titles.items():
            self.db.execute(
                "INSERT INTO cozyla_sync (list_id, synced_at, title) VALUES (?, ?, ?) "
                "ON CONFLICT(list_id) DO UPDATE SET synced_at = excluded.synced_at, "
                "title = excluded.title",
                (list_id, now, title),
            )

    # ----- small things -------------------------------------------------------------------

    @property
    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _due_on(self, todo: Todo) -> date | None:
        return todo.due.astimezone(self._tz).date() if todo.due else None

    def _due_at(self, task: Task) -> datetime | None:
        """The wall keeps a moment: the task's time on its day, else the end of the day
        (23:59, the wall's own "no time"). Midnight showed as overdue all day."""
        if task.due_on is None:
            return None
        at = task.due_time or END_OF_DAY
        day = task.due_on
        return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=self._tz)

    def _admin(self) -> Member:
        return next(m for m in self.services.store.list_members() if m.is_admin)

    def _everyone(self) -> list[Member]:
        return [m for m in self.services.store.list_members() if m.telegram_user_id is not None]

    def _doer(self, task: Task) -> Member:
        if task.assignee is not None:
            return self.services.store.get_member(task.assignee)
        return self._admin()


# ----- tools (registered only when a wall list is configured) -----------------------------


def _wall(ctx: ToolContext) -> CozylaTodos:
    wall = ctx.services.wall
    assert wall is not None
    return wall


def _named_list(wall: CozylaTodos, name: str) -> tuple[str, str]:
    found = wall.find_list(name)
    if found is None:
        names = ", ".join(sorted(wall.lists().values())) or "none yet"
        raise ToolFailed(
            f"There's no list called {name!r} on the wall. Its lists: {names}. The chore chart "
            "isn't a list: put_task_on_chore_chart puts a task there."
        )
    return found


@tool(
    "put_task_on_wall_list",
    "Put a task on a particular to-do list on the Cozyla wall when someone names one ('add "
    "making lasagna for Erin to Things to Cook'). Use after create_task. Without it, tasks "
    "go on the main to-do list.",
    {
        "task_id": {"type": "integer"},
        "list": {"type": "string", "description": "The list's name, as they said it."},
    },
)
async def put_task_on_wall_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    wall = _wall(ctx)
    list_id, title = _named_list(wall, args["list"])
    try:
        task = wall.board.get(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if not wall.board.can_edit(task, ctx.member):
        raise ToolFailed("That task isn't theirs to change.")
    if task.repeats:
        raise ToolFailed("Repeating chores stay off the wall's to-do lists.")
    wall.put_on(task.id, list_id)
    return f"Task {task.id} ({task.title}) will be on {title} on the wall within a minute."


def _not_a_todo(task: Task) -> bool:
    """Chores live on the chart, and a check-in is Themi's own question (bug #41: an extra
    water check-in went on the to-do list)."""
    return _off_the_lists(task) or task.check_in


def _off_the_lists(task: Task) -> bool:
    """Taken off the wall's to-do lists if it was on one: a chore, on the chart, or Themi's
    own (E2b's email audit)."""
    return task.repeats or task.on_chart or task.off_wall


IMPORTANCE_RANK = {"high": 0, "normal": 1, "low": 2}


def _rank(task: Task, today: date) -> tuple[int, int, date, int]:
    """Top of the list first: due or overdue, then important, then the soonest due date."""
    due = task.due_on or date.max
    return (0 if due <= today else 1, IMPORTANCE_RANK.get(task.importance, 1), due, task.id)
