"""Themi's lists and the wall's, kept in step (L1b).

The to-do sync (`themi.core.cozyla_todos`) reads every list on the wall each minute and
hands what it read to `WallLists.sync`, so nothing is read twice:

- Every wall list except the to-do list (Things to Cook, Shopping List...) is one of
  Themi's household lists: linked to one with the same name, or made. Renamed on the wall,
  renamed here; deleted on the wall, the list stays in Themi, no longer linked.
- Its items that aren't anyone's job (unassigned, and not a task) are the list's items,
  both ways: added, ticked, unticked, renamed or deleted on either side. A change made in
  Themi since the last sync wins. An item that becomes someone's on the wall is a task now
  (C1c) and leaves the list. Ticked-off to-dos Themi never saw are history, left behind.
- A list goes on the wall when someone asks (`put_list_on_wall`): a wall list is made with
  its name and kept in step from then on. Deleting a list in Themi deletes the wall's too.

As with tasks, configuring the wall is the go-ahead for keeping lists in step; adding items
and putting a list on the wall are staged by their tools. A write that fails is tried again
next minute.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.autonomy import ExecutionContext
from themi.connectors.cozyla import CozylaClient, CozylaError, Todo, TodoList
from themi.core.lists import Lists, list_key, name_key, named_in
from themi.core.services import Services
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)

PUT_CATEGORY, PUT_EXECUTOR = "wall_list_add", "cozyla.put_list"


class WallLists:
    def __init__(self, services: Services, lists: Lists, client: CozylaClient) -> None:
        self.services = services
        self.lists = lists
        self.client = client
        self.db = services.store.db

    def install(self) -> None:
        self.services.autonomy.executors.register(PUT_EXECUTOR)(self._execute_put)
        self.services.tools.register(put_list_on_wall)

    async def sync(
        self, wall_lists: Iterable[TodoList], todos: Iterable[Todo], skip: set[str], tasks: set[str]
    ) -> None:
        """`skip`: wall lists that hold tasks (the to-do list). `tasks`: to-dos that are
        Themi tasks."""
        wall = {w.id: w for w in wall_lists if w.id not in skip}
        current = {t.id: t for t in todos}
        await self._removals(wall, current)
        first = self._link_lists(wall)
        for row in self.db.query("SELECT * FROM lists WHERE cozyla_list_id IS NOT NULL"):
            list_id = row["cozyla_list_id"]
            here = [
                t
                for t in current.values()
                if t.list_id == list_id and t.assignee is None and t.id not in tasks
            ]
            await self._items(row["id"], list_id, here, first=list_id in first)

    # ----- lists ------------------------------------------------------------------------

    async def _removals(self, wall: dict[str, TodoList], current: dict[str, Todo]) -> None:
        """Lists and items removed in Themi go from the wall; gone already, forgotten."""
        for row in self.db.query("SELECT * FROM list_wall_removals ORDER BY kind DESC"):
            kind, wall_id = row["kind"], row["wall_id"]
            try:
                if kind == "list" and wall_id in wall:
                    await self.client.delete_list(wall_id)
                    del wall[wall_id]
                    for todo_id in [t.id for t in current.values() if t.list_id == wall_id]:
                        del current[todo_id]
                elif kind == "todo" and wall_id in current:
                    await self.client.delete(wall_id)
                    del current[wall_id]
            except CozylaError as exc:
                log.warning("Removing Cozyla %s %s waits: %s", kind, wall_id, exc)
                continue
            self.db.execute(
                "DELETE FROM list_wall_removals WHERE kind = ? AND wall_id = ?", (kind, wall_id)
            )

    def _link_lists(self, wall: dict[str, TodoList]) -> set[str]:
        """Follow renames and deletions on the wall, and link or make a list for each new
        wall list. Returns the wall lists linked just now."""
        linked = {}
        for row in self.db.query("SELECT * FROM lists WHERE cozyla_list_id IS NOT NULL"):
            wall_list = wall.get(row["cozyla_list_id"])
            if wall_list is None:  # deleted on the wall: kept here, no longer linked
                log.info("Cozyla list %s is gone; list %s stays", row["cozyla_list_id"], row["id"])
                self._unlink(row["id"])
            else:
                linked[wall_list.id] = row
                if wall_list.title.strip() and wall_list.title != row["name"]:
                    self.db.execute(
                        "UPDATE lists SET name = ? WHERE id = ?", (wall_list.title, row["id"])
                    )
        first = set()
        for wall_id, wall_list in wall.items():
            if wall_id in linked or not wall_list.title.strip():
                continue
            same = next(
                (
                    r
                    for r in self.db.query(
                        "SELECT * FROM lists WHERE owner_id IS NULL AND cozyla_list_id IS NULL"
                    )
                    if list_key(r["name"]) == list_key(wall_list.title)
                ),
                None,
            )
            if same is not None:
                self.db.execute(  # the wall's spelling, from now on
                    "UPDATE lists SET cozyla_list_id = ?, name = ? WHERE id = ?",
                    (wall_id, wall_list.title, same["id"]),
                )
            else:
                self.db.execute(
                    "INSERT INTO lists (name, owner_id, created_by, created_at, cozyla_list_id) "
                    "VALUES (?, NULL, NULL, ?, ?)",
                    (wall_list.title, to_utc_iso(clock.now()), wall_id),
                )
            first.add(wall_id)
        return first

    def _unlink(self, list_id: int) -> None:
        self.db.execute("UPDATE lists SET cozyla_list_id = NULL WHERE id = ?", (list_id,))
        self.db.execute(
            "UPDATE list_items SET cozyla_todo_id = NULL, wall_title = NULL, wall_done = NULL, "
            "pending = 0 WHERE list_id = ?",
            (list_id,),
        )

    # ----- items ------------------------------------------------------------------------

    async def _items(self, list_id: int, wall_id: str, todos: list[Todo], *, first: bool) -> None:
        rows = self.db.query("SELECT * FROM list_items WHERE list_id = ? ORDER BY id", (list_id,))
        by_todo = {r["cozyla_todo_id"]: r for r in rows if r["cozyla_todo_id"]}
        unsent = [r for r in rows if not r["cozyla_todo_id"]]
        for todo in todos:
            row = by_todo.pop(todo.id, None)
            if row is None and first:  # the same item on both sides: one item
                row = next((r for r in unsent if name_key(r["name"]) == name_key(todo.title)), None)
                if row is not None:  # Themi's wording and tick go out
                    unsent.remove(row)
                    row = {**row, "cozyla_todo_id": todo.id, "pending": 1}
            if row is None:  # new on the wall; ticked ones Themi never saw are history
                if not todo.completed and todo.title.strip():
                    self._bring_in(list_id, todo)
            elif row["pending"]:
                await self._send(row, todo)
            elif (todo.title, todo.completed) != (row["wall_title"], bool(row["wall_done"])):
                self._follow(row, todo)
        for row in by_todo.values():  # gone from the wall, or someone's job now
            self.db.execute("DELETE FROM list_items WHERE id = ?", (row["id"],))
        for row in unsent:
            await self._create(wall_id, row)

    def _bring_in(self, list_id: int, todo: Todo) -> None:
        self.db.execute(
            "INSERT INTO list_items (list_id, name, done, done_at, added_by, added_at, "
            "cozyla_todo_id, wall_title, wall_done) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)",
            (
                list_id,
                todo.title.strip(),
                int(todo.completed),
                to_utc_iso(clock.now()) if todo.completed else None,
                to_utc_iso(clock.now()),
                todo.id,
                todo.title,
                int(todo.completed),
            ),
        )

    def _follow(self, row: dict[str, Any], todo: Todo) -> None:
        """Changed on the wall: renamed, ticked or unticked."""
        name = todo.title.strip() or row["name"]
        done = todo.completed
        self.db.execute(
            "UPDATE list_items SET name = ?, done = ?, done_by = CASE WHEN ? THEN done_by END, "
            "done_at = CASE WHEN ? THEN COALESCE(done_at, ?) END WHERE id = ?",
            (name, int(done), int(done), int(done), to_utc_iso(clock.now()), row["id"]),
        )
        self._seen(row["id"], todo)

    async def _send(self, row: dict[str, Any], todo: Todo) -> None:
        """Changed in Themi: the wall's to-do is made to match."""
        try:
            if todo.title != row["name"]:
                await self.client.update(todo, title=row["name"], assignee=None, due=todo.due)
                todo = replace(todo, title=row["name"])
            if todo.completed != bool(row["done"]):
                await self.client.set_done(todo.id, bool(row["done"]))
                todo = replace(todo, completed=bool(row["done"]))
        except CozylaError as exc:
            log.warning("Cozyla list item %s waits: %s", row["id"], exc)
            return
        self._seen(row["id"], todo)

    async def _create(self, wall_id: str, row: dict[str, Any]) -> None:
        try:
            todo_id = await self.client.create(wall_id, row["name"], assignee=None, due=None)
            if row["done"]:
                await self.client.set_done(todo_id, True)
        except CozylaError as exc:
            log.warning("Cozyla list item %s waits: %s", row["id"], exc)
            return
        self.db.execute(
            "UPDATE list_items SET cozyla_todo_id = ?, wall_title = ?, wall_done = ?, pending = 0 "
            "WHERE id = ?",
            (todo_id, row["name"], row["done"], row["id"]),
        )

    def _seen(self, item_id: int, todo: Todo) -> None:
        """Remember how the wall has it now; nothing is waiting to go out."""
        self.db.execute(
            "UPDATE list_items SET cozyla_todo_id = ?, wall_title = ?, wall_done = ?, pending = 0 "
            "WHERE id = ?",
            (todo.id, todo.title, int(todo.completed), item_id),
        )

    # ----- putting a list on the wall ----------------------------------------------------

    async def _execute_put(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        nl = self.lists.get(int(payload["list_id"]), ctx.member)
        if nl is None:
            return "That list is gone, so nothing went on the wall."
        if nl.wall_id is not None:
            return f"{nl.name} is on the wall already."
        wall_id = await self.client.create_list(nl.name)
        self.db.execute("UPDATE lists SET cozyla_list_id = ? WHERE id = ?", (wall_id, nl.id))
        return f"{nl.name} is going on the wall; its items follow within a minute."


@staged_tool(
    "put_list_on_wall",
    "Put one of Themi's lists on the Cozyla wall as a list of its own, when someone asks ('put "
    "the packing list on the wall'). From then on it's kept in step both ways. Lists stay off "
    "the wall unless asked.",
    {"list": {"type": "string", "description": "The list's name, as they said it."}},
)
async def put_list_on_wall(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    lists = ctx.services.lists
    if lists is None:
        raise ToolFailed("Lists aren't set up.")
    nl = lists.find(ctx.member, args["list"])
    if nl.wall_id is not None:
        raise ToolDeclined(f"{nl.name} is on the wall already.")
    proposal = Proposal(PUT_CATEGORY, f"{nl.name} on the wall", PUT_EXECUTOR, {"list_id": nl.id})
    return replace(proposal, requested=named_in(nl, args["list"], ctx.request_text))
