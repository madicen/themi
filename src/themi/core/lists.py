"""Lists Themi keeps on request (L1a, Erin's idea #7): "packing for the trip", "gift ideas".

- A list is the household's unless someone says it's theirs ("my gift ideas"); a personal
  list is seen only by its owner, in chat and on the website.
- Names are checked against what the person typed, as F5 does for groceries: items they
  wrote go straight on; items the model inferred are staged (`list_add`) and wait for a
  yes. A whole list is deleted without asking only when they named it (`list_delete`).
- Ticked items stay, crossed off, until someone clears them (the family's choice).
- A list can be kept in step with a list on the Cozyla wall (L1b, `themi.core.cozyla_lists`):
  the wall's own lists come in, and a list goes on the wall when someone asks. Changes made
  here mark the item pending and removals are queued for the wall; the sync does the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.autonomy import ExecutionContext
from themi.core.groceries import and_list, asks_to_add, refuse_spending
from themi.core.prompts import OpenItem
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

ADD_CATEGORY, ADD_EXECUTOR = "list_add", "lists.add"
THINGS_TO_BUY = "things_to_buy"  # the household's list for what isn't food (L2a)
DELETE_CATEGORY, DELETE_EXECUTOR = "list_delete", "lists.delete"
MAX_NAME = 60
MAX_ITEM = 100


def _clean(raw: str, limit: int, what: str) -> str:
    text = " ".join(str(raw).split()).strip(" ,.;:")
    if not text:
        raise InvalidValue(f"a {what} needs a name")
    if len(text) > limit:
        raise InvalidValue(f"a {what} name is at most {limit} characters")
    return text


def name_key(text: str) -> str:
    """For comparing names: lowercase words, no punctuation."""
    return " ".join(re.sub(r"[^\w\s&'/-]", " ", text.lower()).split())


def list_key(text: str) -> str:
    """A list's name as people say it: "the packing list" is "packing"."""
    key = re.sub(r"^(?:the|my|our)\s+", "", name_key(text))
    return re.sub(r"\s+list$", "", key) or key


def _said(names: list[str], request_text: str) -> bool:
    """Every name appears, as whole words, in what they wrote this turn."""
    said = name_key(request_text)
    return bool(said) and all(re.search(rf"\b{re.escape(name_key(n))}\b", said) for n in names)


@dataclass(frozen=True)
class ListItem:
    id: int
    list_id: int
    name: str
    done: bool
    added_at: datetime


@dataclass(frozen=True)
class NamedList:
    id: int
    name: str
    owner_id: int | None  # None: the household's
    items: tuple[ListItem, ...]
    wall_id: str | None = None  # the Cozyla list it's kept in step with (L1b)
    purpose: str | None = None  # THINGS_TO_BUY, or None for an ordinary list

    @property
    def personal(self) -> bool:
        return self.owner_id is not None

    @property
    def open_items(self) -> list[ListItem]:
        return [i for i in self.items if not i.done]

    @property
    def ticked(self) -> list[ListItem]:
        return [i for i in self.items if i.done]


class Lists:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.lists = self
        s.autonomy.executors.register(ADD_EXECUTOR)(self._execute_add)
        s.autonomy.executors.register(DELETE_EXECUTOR)(self._execute_delete)
        for t in (create_list, add_to_list, tick_list_items, remove_from_list, show_lists):
            s.tools.register(t)
        s.tools.register(delete_list)
        s.open_item_sources.append(self._open_items)

    # ----- reading ------------------------------------------------------------

    def visible(self, member: Member) -> list[NamedList]:
        """The household's lists and this person's own, oldest first."""
        rows = self.db.query(
            "SELECT * FROM lists WHERE owner_id IS NULL OR owner_id = ? ORDER BY id", (member.id,)
        )
        return [self._load(r) for r in rows]

    def get(self, list_id: int, member: Member) -> NamedList | None:
        row = self.db.one(
            "SELECT * FROM lists WHERE id = ? AND (owner_id IS NULL OR owner_id = ?)",
            (list_id, member.id),
        )
        return self._load(row) if row else None

    def find(self, member: Member, name: str) -> NamedList:
        """The list they mean: the same name, or the one list whose name has all their words
        ("packing" for "packing for the trip"). Raises ToolFailed naming the lists there are."""
        lists = self.visible(member)
        wanted = list_key(name)
        exact = [nl for nl in lists if list_key(nl.name) == wanted]
        if len(exact) == 1:
            return exact[0]
        words = wanted.split()
        close = [
            nl
            for nl in lists
            if words and all(any(w.startswith(x) for w in list_key(nl.name).split()) for x in words)
        ]
        if len(close) == 1:
            return close[0]
        names = and_list([f'"{nl.name}"' for nl in lists]) if lists else "none yet"
        raise ToolFailed(
            f'There\'s no one list called "{name}". Their lists: {names}. create_list makes one.'
        )

    def _load(self, row: dict[str, Any]) -> NamedList:
        items = tuple(
            ListItem(
                r["id"],
                r["list_id"],
                r["name"],
                bool(r["done"]),
                datetime.fromisoformat(r["added_at"]),
            )
            for r in self.db.query(
                "SELECT * FROM list_items WHERE list_id = ? ORDER BY id", (row["id"],)
            )
        )
        return NamedList(
            row["id"], row["name"], row["owner_id"], items, row["cozyla_list_id"], row["purpose"]
        )

    # ----- changing -----------------------------------------------------------

    def create(self, member: Member, name: str, *, personal: bool) -> NamedList:
        name = _clean(name, MAX_NAME, "list")
        for nl in self.visible(member):
            if list_key(nl.name) == list_key(name):
                raise InvalidValue(f'there\'s a list called "{nl.name}" already')
        list_id = self.db.execute(
            "INSERT INTO lists (name, owner_id, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, member.id if personal else None, member.id, to_utc_iso(clock.now())),
        )
        found = self.get(list_id, member)
        assert found is not None
        return found

    def things_to_buy(self, member: Member) -> NamedList:
        """The household's list for things to buy that aren't food, made if there isn't one."""
        row = self.db.one("SELECT id FROM lists WHERE purpose = ?", (THINGS_TO_BUY,))
        if row is None:
            list_id = self.db.execute(
                "INSERT INTO lists (name, owner_id, created_by, created_at, purpose) "
                "VALUES ('Things to Buy', NULL, NULL, ?, ?)",
                (to_utc_iso(clock.now()), THINGS_TO_BUY),
            )
        else:
            list_id = row["id"]
        found = self.get(list_id, member)
        assert found is not None
        return found

    def rename(self, nl: NamedList, member: Member, name: str) -> NamedList:
        """A new name; a list on the wall is renamed there at the next sync."""
        name = _clean(name, MAX_NAME, "list")
        for other in self.visible(member):
            if other.id != nl.id and list_key(other.name) == list_key(name):
                raise InvalidValue(f'there\'s a list called "{other.name}" already')
        self.db.execute("UPDATE lists SET name = ? WHERE id = ?", (name, nl.id))
        found = self.get(nl.id, member)
        assert found is not None
        return found

    def stores(self, nl: NamedList) -> dict[int, str]:
        """Item id -> the store it usually comes from, where known (L2a)."""
        found = {}
        for item in nl.items:
            row = self.db.one(
                "SELECT store FROM item_homes WHERE name_key = ? AND store IS NOT NULL",
                (name_key(item.name),),
            )
            if row:
                found[item.id] = row["store"]
        return found

    def describe(self, nl: NamedList) -> str:
        """A list in a line; things to buy grouped by where they usually come from."""
        if nl.purpose != THINGS_TO_BUY or not nl.open_items:
            return words(nl)
        stores = self.stores(nl)
        groups: dict[str, list[str]] = {}
        for item in nl.open_items:
            groups.setdefault(stores.get(item.id, "anywhere"), []).append(item.name)
        order = sorted(groups, key=lambda g: (g == "anywhere", g.casefold()))
        text = f"{nl.name}: " + "; ".join(f"{g}: {and_list(groups[g])}" for g in order)
        if nl.ticked:
            text += f" (ticked: {and_list([i.name for i in nl.ticked])})"
        return text + "."

    def add(self, nl: NamedList, names: list[str], by: Member | None) -> list[str]:
        """Put items on a list; returns the ones that weren't on it (unticked) already."""
        there = {name_key(i.name) for i in nl.open_items}
        added = []
        for raw in names:
            name = _clean(raw, MAX_ITEM, "list item")
            if name_key(name) in there:
                continue
            ticked = next((i for i in nl.ticked if name_key(i.name) == name_key(name)), None)
            if ticked is not None:  # back on: untick it rather than list it twice
                self.tick(ticked, False, by)
            else:
                self.db.execute(
                    "INSERT INTO list_items (list_id, name, added_by, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (nl.id, name, by.id if by else None, to_utc_iso(clock.now())),
                )
            there.add(name_key(name))
            added.append(name)
        return added

    def tick(self, item: ListItem, done: bool, by: Member | None) -> None:
        self.db.execute(
            "UPDATE list_items SET done = ?, done_by = ?, done_at = ?, pending = 1 WHERE id = ?",
            (
                int(done),
                by.id if by and done else None,
                to_utc_iso(clock.now()) if done else None,
                item.id,
            ),
        )

    def remove(self, item: ListItem) -> None:
        self._off_the_wall("id = ?", (item.id,))
        self.db.execute("DELETE FROM list_items WHERE id = ?", (item.id,))

    def clear_ticked(self, nl: NamedList) -> int:
        self._off_the_wall("list_id = ? AND done = 1", (nl.id,))
        return self.db.update("DELETE FROM list_items WHERE list_id = ? AND done = 1", (nl.id,))

    def delete(self, nl: NamedList) -> None:
        """Delete a list, and its wall list too if it has one."""
        if nl.wall_id is not None:
            self.db.execute(
                "INSERT OR IGNORE INTO list_wall_removals (kind, wall_id) VALUES ('list', ?)",
                (nl.wall_id,),
            )
        self.db.execute("DELETE FROM lists WHERE id = ?", (nl.id,))

    def _off_the_wall(self, where: str, params: tuple[Any, ...]) -> None:
        """Queue the wall's copies of these items for deletion."""
        self.db.execute(
            "INSERT OR IGNORE INTO list_wall_removals (kind, wall_id) SELECT 'todo', "
            f"cozyla_todo_id FROM list_items WHERE cozyla_todo_id IS NOT NULL AND {where}",
            params,
        )

    def match(
        self, nl: NamedList, names: list[str], *, ticked: bool | None = None
    ) -> list[ListItem]:
        """The items they named: the same words, or the one item containing them. Raises
        ToolFailed naming what's on the list."""
        pool = [i for i in nl.items if ticked is None or i.done == ticked]
        found: list[ListItem] = []
        for raw in names:
            key = name_key(str(raw))
            exact = [i for i in pool if name_key(i.name) == key]
            close = exact or [
                i for i in pool if re.search(rf"\b{re.escape(key)}\b", name_key(i.name))
            ]
            if len(close) != 1:
                on = and_list([i.name for i in pool]) if pool else "nothing"
                raise ToolFailed(f'"{raw}" isn\'t one item on {nl.name}. On it: {on}.')
            if close[0] not in found:
                found.append(close[0])
        return found

    # ----- staged actions -----------------------------------------------------

    async def _execute_add(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        nl = self.get(int(payload["list_id"]), ctx.member)
        if nl is None:
            return "That list is gone, so nothing was added."
        names = [str(n) for n in payload.get("items", [])]
        added = self.add(nl, names, ctx.member)
        if not added:
            return f"{and_list(names)} {'was' if len(names) == 1 else 'were'} on {nl.name} already."
        return f"Added {and_list(added)} to {nl.name}."

    async def _execute_delete(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        nl = self.get(int(payload["list_id"]), ctx.member)
        if nl is None:
            return "That list was gone already."
        self.delete(nl)
        return f"Deleted the list {nl.name}."

    # ----- for the model ------------------------------------------------------

    def _open_items(self, member: Member) -> list[OpenItem]:
        lists = self.visible(member)
        if not lists:
            return []
        parts = [
            f'"{nl.name}"{" (theirs only)" if nl.personal else ""}'
            + (" (on the wall)" if nl.wall_id else "")
            + f": {len(nl.open_items)} to go"
            + (f", {len(nl.ticked)} ticked" if nl.ticked else "")
            for nl in lists
        ]
        return [OpenItem("Lists: " + "; ".join(parts))]


def named_in(nl: NamedList, asked_for: str, request_text: str) -> bool:
    """Its name, or the words that found it ("the packing list"), are in what they wrote."""
    said = name_key(request_text)
    names = {list_key(nl.name), list_key(asked_for)}
    return bool(said) and any(re.search(rf"\b{re.escape(n)}\b", said) for n in names if n)


def words(nl: NamedList) -> str:
    """A list in a line: what's left, then what's ticked."""
    left = and_list([i.name for i in nl.open_items]) if nl.open_items else "nothing left"
    text = f"{nl.name}: {left}"
    if nl.ticked:
        text += f" (ticked: {and_list([i.name for i in nl.ticked])})"
    return text + "."


def _lists(ctx: ToolContext) -> Lists:
    lists = ctx.services.lists
    if lists is None:
        raise ToolFailed("Lists aren't set up.")
    return lists


@tool(
    "create_list",
    "Make a new named list Themi keeps ('a packing list for the trip', 'gift ideas'), when "
    "someone asks for one. personal: true only when they say it's theirs ('my gift ideas "
    "list', 'a list just for me'); otherwise it's the household's. Not for groceries "
    "(add_to_grocery_list) or tasks. Add items after with add_to_list.",
    {"name": {"type": "string"}, "personal": {"type": "boolean"}},
)
async def create_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        nl = _lists(ctx).create(ctx.member, args["name"], personal=bool(args["personal"]))
    except InvalidValue as exc:
        raise ToolDeclined(str(exc)) from exc
    whose = "just theirs" if nl.personal else "the household's"
    return f'Made the list "{nl.name}" ({whose}). It\'s empty.'


@staged_tool(
    "add_to_list",
    "Put items on one of Themi's named lists (see Lists in the context), by the name they "
    "use. Items they wrote go straight on; anything else waits for their yes.",
    {
        "list": {"type": "string", "description": "The list's name, as they said it."},
        "items": {"type": "array", "items": {"type": "string"}},
    },
)
async def add_to_list(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    lists = _lists(ctx)
    nl = lists.find(ctx.member, args["list"])
    there = {name_key(i.name) for i in nl.open_items}
    names, skipped = [], []
    for raw in args["items"]:
        try:
            name = _clean(raw, MAX_ITEM, "list item")
        except InvalidValue as exc:
            raise ToolFailed(f"{str(exc).capitalize()}.") from exc
        if name_key(name) in there or name in names:
            skipped.append(name)
        else:
            names.append(name)
    if not names:
        if skipped:
            raise ToolDeclined(f"Already on {nl.name}: {and_list(skipped)}. Nothing was added.")
        raise ToolFailed("There were no items to add.")
    refuse_spending(names, ctx.request_text, prices=nl.purpose == THINGS_TO_BUY)
    text = and_list(names)
    summary = f"{text[:1].upper()}{text[1:]} for {nl.name}"
    proposal = Proposal(ADD_CATEGORY, summary, ADD_EXECUTOR, {"list_id": nl.id, "items": names})
    asked = _said(names, ctx.request_text) and asks_to_add(ctx.request_text, ctx.previous_text)
    return replace(proposal, requested=asked)


@tool(
    "tick_list_items",
    "Tick items off one of Themi's lists (done: true), or untick them (done: false). They "
    "stay on the list, crossed off, until cleared with remove_from_list.",
    {
        "list": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "done": {"type": "boolean"},
    },
)
async def tick_list_items(ctx: ToolContext, args: dict[str, Any]) -> str:
    lists = _lists(ctx)
    nl = lists.find(ctx.member, args["list"])
    done = bool(args["done"])
    items = lists.match(nl, args["items"], ticked=not done)
    for item in items:
        lists.tick(item, done, ctx.member)
    fresh = lists.get(nl.id, ctx.member)
    assert fresh is not None
    verb = "Ticked off" if done else "Unticked"
    return f"{verb} {and_list([i.name for i in items])}. Now: {words(fresh)}"


@tool(
    "remove_from_list",
    "Take items off one of Themi's lists altogether, or clear the ticked ones (ticked: true, "
    "items empty).",
    {
        "list": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "ticked": {"type": "boolean"},
    },
)
async def remove_from_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    lists = _lists(ctx)
    nl = lists.find(ctx.member, args["list"])
    removed = []
    if args["items"]:
        for item in lists.match(nl, args["items"]):
            lists.remove(item)
            removed.append(item.name)
    cleared = lists.clear_ticked(nl) if args["ticked"] else 0
    if not removed and not cleared:
        raise ToolDeclined(f"Nothing to take off {nl.name}.")
    fresh = lists.get(nl.id, ctx.member)
    assert fresh is not None
    done = [f"took off {and_list(removed)}"] if removed else []
    done += [f"cleared {cleared} ticked"] if cleared else []
    return f"{' and '.join(done).capitalize()}. Now: {words(fresh)}"


@tool(
    "show_lists",
    "What's on one of Themi's lists (by name), or every list they can see (list empty).",
    {"list": {"type": "string"}},
)
async def show_lists(ctx: ToolContext, args: dict[str, Any]) -> str:
    lists = _lists(ctx)
    if args["list"].strip():
        return lists.describe(lists.find(ctx.member, args["list"]))
    found = lists.visible(ctx.member)
    if not found:
        return "There are no lists yet."
    return " ".join(lists.describe(nl) for nl in found)


@staged_tool(
    "delete_list",
    "Delete one of Themi's lists and everything on it. Without asking only when they named "
    "the list; otherwise it waits for their yes.",
    {"list": {"type": "string"}},
)
async def delete_list(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    nl = _lists(ctx).find(ctx.member, args["list"])
    named = named_in(nl, args["list"], ctx.request_text)
    wall = ", on the wall too" if nl.wall_id else ""
    proposal = Proposal(
        DELETE_CATEGORY, f"Deleting the list {nl.name}{wall}", DELETE_EXECUTOR, {"list_id": nl.id}
    )
    return replace(proposal, requested=named)
