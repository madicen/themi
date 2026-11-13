"""Lists Themi keeps on request (L1a, Erin's idea #7): "packing for the trip", "gift ideas".

- A list is the household's unless someone says it's theirs ("my gift ideas"); a personal
  list is seen only by its owner, in chat and on the website.
- Names are checked against what the person typed, as F5 does for groceries: items they
  wrote go straight on; items the model inferred are staged (`list_add`) and wait for a
  yes. A whole list is deleted without asking only when they named it (`list_delete`).
- Ticked items stay, crossed off, until someone clears them (the family's choice).
- A list can be kept in step by a mirror, a display or app with lists of its own (L1b;
  CR21b: `themi.modules.mirrors`). Changes made here mark the item pending, and items and
  lists about to go are told to the mirrors; their syncs do the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import field_validator

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.accounts.preferences import Preferences
from themi.autonomy import ExecutionContext
from themi.core import groups, keys
from themi.core.prompts import OpenItem
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool, tool
from themi.core.wording import and_list, asks_to_add, name_key, picture_asks_to_add, refuse_spending
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.prompt import PromptFragment

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.modules.mirrors import Mirror

ADD_CATEGORY, ADD_EXECUTOR = "list_add", "lists.add"
THINGS_TO_BUY = "things_to_buy"  # the household's list for what isn't food (L2a)
DELETE_CATEGORY, DELETE_EXECUTOR = "list_delete", "lists.delete"
MAX_NAME = 60
MAX_ITEM = 500  # F21a, bug #117: a list of thoughts, not only things
SAID_BACK = 60  # characters: items up to this are named in the reply to an add
# "Gift list. A scarf", "gift ideas: board games", "packing list - hats" (idea #115)
OPENS_WITH_LIST = re.compile(r"\s*([^.:\n\u2013\u2014]{3,60}?)\s*(?:[.:\n\u2013\u2014]| - )\s*\S")


def _clean(raw: str, limit: int, what: str) -> str:
    text = " ".join(str(raw).split()).strip(" ,.;:")
    if not text:
        raise InvalidValue(f"a {what} needs a name")
    if len(text) > limit:
        raise InvalidValue(f"a {what} name is at most {limit} characters")
    return text


# Bug #151: "Add body double, move from room to room to service dog tasks" added "Add body
# double...". Their own verb, at the start of their message and of the item, isn't the item.
ITEM_VERB = re.compile(r"^(add|put)\s+(.+)$", re.IGNORECASE)
LEADING_VERB = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you|themi)[\s,]+)*(add|put)\b", re.IGNORECASE
)


def without_verb(name: str, request_text: str) -> str:
    item, lead = ITEM_VERB.match(name), LEADING_VERB.match(request_text)
    if (
        item is not None
        and lead is not None
        and item.group(1).lower() == lead.group(1).lower()
        and name_key(item.group(2)) in name_key(request_text[lead.end() :])
    ):
        return item.group(2)
    return name


def item_limit(nl: NamedList) -> int:
    """The longest item: shorter when a mirror keeping the list takes less (CR21b)."""
    mirror = nl.mirror
    return mirror.item_limit if mirror and mirror.item_limit else MAX_ITEM


def too_long(nl: NamedList) -> str:
    mirror = nl.mirror
    where = f", the most a list {mirror.where} takes," if mirror and mirror.item_limit else ","
    return f"That one's over {item_limit(nl)} characters{where} so it isn't on {nl.name} yet."


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
    parent_id: int | None = None  # F29g: a sub-item of that item


@dataclass(frozen=True)
class NamedList:
    id: int
    name: str
    owner_id: int | None  # None: the household's
    items: tuple[ListItem, ...]
    mirror: Mirror | None = None  # CR21b: what keeps it in step elsewhere (L1b), if anything
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


class ListsPreferences(Preferences):
    """CR7b1: how a list's levels show in chat (F29g): dashes, bullets or numbers."""

    module: ClassVar[str] = "lists"
    list_style: str = "dashes"

    @field_validator("list_style")
    @classmethod
    def _list_style(cls, value: str) -> str:
        if value not in ("dashes", "bullets", "numbers"):
            raise ValueError("a list style is dashes, bullets or numbers")
        return value


class Lists:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.provide(keys.lists, self)
        s.autonomy.executors.register(ADD_EXECUTOR)(self._execute_add)
        s.autonomy.executors.register(DELETE_EXECUTOR)(self._execute_delete)
        for t in (
            create_list, add_to_list, tick_list_items, remove_from_list, show_lists,
            move_list_item,
        ):  # fmt: skip
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
                r["parent_id"],
            )
            for r in self.db.query(
                "SELECT * FROM list_items WHERE list_id = ? ORDER BY id", (row["id"],)
            )
        )
        mirror = self.services.mirrors.keeping_list(row["id"])
        return NamedList(row["id"], row["name"], row["owner_id"], items, mirror, row["purpose"])

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
        """A new name; a mirror keeping the list renames it there at its next sync."""
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

    def someday(self, nl: NamedList) -> dict[int, int | None]:
        """F36b: item id -> who added it, for its someday items (research ones included)."""
        rows = self.db.query(
            "SELECT id, added_by FROM list_items WHERE list_id = ? AND someday = 1", (nl.id,)
        )
        return {r["id"]: r["added_by"] for r in rows}

    def set_someday(self, item: ListItem, on: bool) -> None:
        self.db.execute("UPDATE list_items SET someday = ? WHERE id = ?", (int(on), item.id))

    def rename_item(self, item: ListItem, name: str) -> None:
        """A new name for an item, as they said it (F36b: a decision after research)."""
        nl = self.db.one("SELECT * FROM lists WHERE id = ?", (item.list_id,))
        limit = item_limit(self._load(nl)) if nl else 100
        self.db.execute(
            "UPDATE list_items SET name = ? WHERE id = ?",
            (_clean(name, limit, "list item"), item.id),
        )

    def describe(self, nl: NamedList) -> str:
        """A list in a line; things to buy grouped by where they usually come from, and
        someday items apart, with whose they are (F36b)."""
        if nl.purpose != THINGS_TO_BUY or not nl.open_items:
            return words(nl)
        stores = self.stores(nl)
        later = self.someday(nl)
        groups: dict[str, list[str]] = {}
        theirs: dict[int | None, list[str]] = {}
        for item in nl.open_items:
            if item.id in later:
                theirs.setdefault(later[item.id], []).append(item.name)
            else:
                groups.setdefault(stores.get(item.id, "anywhere"), []).append(item.name)
        order = sorted(groups, key=lambda g: (g == "anywhere", g.casefold()))
        text = f"{nl.name}: " + (
            "; ".join(f"{g}: {and_list(groups[g])}" for g in order) or "nothing but someday things"
        )
        if nl.ticked:
            text += f" (ticked: {and_list([i.name for i in nl.ticked])})"
        text += "."
        for who, names in theirs.items():
            whose = self.name_of(who)
            text += (
                f" Someday ({whose}'s): {and_list(names)}."
                if whose
                else (f" Someday: {and_list(names)}.")
            )
        return text

    def name_of(self, member_id: int | None) -> str:
        if member_id is None:
            return ""
        row = self.db.one("SELECT name FROM members WHERE id = ?", (member_id,))
        return str(row["name"]) if row else ""

    def add(
        self, nl: NamedList, names: list[str], by: Member | None, parent_id: int | None = None
    ) -> list[str]:
        """Put items on a list (under that item, F29g); returns the ones that weren't on it
        (unticked, at that level) already. A name with leading dashes ("-- go upstairs") goes
        that many levels down, under the last one above it."""
        added = []
        parents: list[int | None] = [parent_id]  # parents[n]: the item at level n so far
        for raw in names:
            depth, raw = _depth(str(raw))
            level = min(max(depth, 1), len(parents))  # a level can't be skipped
            under = parents[level - 1]
            name = _clean(raw, item_limit(nl), "list item")
            nl = self.reload(nl)
            same = next(
                (
                    i
                    for i in nl.items
                    if i.parent_id == under and name_key(i.name) == name_key(name)
                ),
                None,
            )
            if same is None:
                item_id = self.db.execute(
                    "INSERT INTO list_items (list_id, name, added_by, added_at, parent_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (nl.id, name, by.id if by else None, to_utc_iso(clock.now()), under),
                )
                added.append(name)
            else:
                item_id = same.id
                if same.done:  # back on: untick it rather than list it twice
                    self.tick(same, False, by)
                    added.append(name)
            del parents[level:]
            parents.append(item_id)
        return added

    def reload(self, nl: NamedList) -> NamedList:
        row = self.db.one("SELECT * FROM lists WHERE id = ?", (nl.id,))
        return self._load(row) if row else nl

    def children(self, nl: NamedList, item: ListItem) -> list[ListItem]:
        """Every item below this one, at any depth."""
        below: list[ListItem] = []
        level = [i for i in nl.items if i.parent_id == item.id]
        while level:
            below += level
            ids = {i.id for i in level}
            level = [i for i in nl.items if i.parent_id in ids]
        return below

    def move(self, nl: NamedList, item: ListItem, under: ListItem | None) -> None:
        """Put an item (with its sub-items) under another, or back at the top. Sub-items
        aren't a mirror's: their lists are flat."""
        if under is not None and (under.id == item.id or under in self.children(nl, item)):
            raise ToolFailed(f'"{item.name}" can\'t go under itself or one of its sub-items.')
        if under is not None:
            self.services.mirrors.leaving([item.id])
            self.services.mirrors.reset(item.id)
        self.db.execute(
            "UPDATE list_items SET parent_id = ? WHERE id = ?",
            (under.id if under else None, item.id),
        )

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
        self.services.mirrors.leaving([item.id])  # CR21b: their copies go too
        self.db.execute("DELETE FROM list_items WHERE id = ?", (item.id,))

    def clear_ticked(self, nl: NamedList) -> int:
        self.services.mirrors.leaving([i.id for i in nl.ticked])
        return self.db.update("DELETE FROM list_items WHERE list_id = ? AND done = 1", (nl.id,))

    def delete(self, nl: NamedList) -> None:
        """Delete a list, and a mirror's copy of it too."""
        if nl.mirror is not None:
            self.services.mirrors.list_leaving(nl.id)
        self.db.execute("DELETE FROM lists WHERE id = ?", (nl.id,))

    def where(self, nl: NamedList, item: ListItem) -> str:
        """ "food (under cats)": an item, with its parent if it has one."""
        parent = next((i for i in nl.items if i.id == item.parent_id), None)
        return f"{item.name} (under {parent.name})" if parent else item.name

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
            if len(close) > 1 and any(i.parent_id for i in close):  # F29g: which level
                which = "; ".join(self.where(nl, i) for i in close)
                raise ToolFailed(f'More than one "{raw}" on {nl.name}: {which}. Ask which.')
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
        under = payload.get("under")
        added = self.add(nl, names, ctx.member, int(under) if under else None)
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
            + (f" ({nl.mirror.where})" if nl.mirror else "")
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
    """A list in a line: what's left, then what's ticked. Sub-items in brackets after
    their item (F29g)."""

    def said(item: ListItem) -> str:
        below = [i for i in nl.open_items if i.parent_id == item.id]
        return item.name + (f" ({', '.join(said(i) for i in below)})" if below else "")

    top = [i for i in nl.open_items if i.parent_id is None or not _has(nl, i.parent_id)]
    left = and_list([said(i) for i in top]) if nl.open_items else "nothing left"
    text = f"{nl.name}: {left}"
    if nl.ticked:
        text += f" (ticked: {and_list([i.name for i in nl.ticked])})"
    return text + "."


def _has(nl: NamedList, item_id: int) -> bool:
    return any(i.id == item_id and not i.done for i in nl.items)


DASHES = re.compile(r"^\s*(-+|\u2013+|\u2014+)\s*")


def _depth(raw: str) -> tuple[int, str]:
    """ "-- go upstairs" -> (2, "go upstairs"): an item written with its level."""
    found = DASHES.match(raw)
    return (len(found.group(1)), raw[found.end() :]) if found else (0, raw)


STYLES = ("dashes", "bullets", "numbers")


def render(nl: NamedList, style: str = "dashes") -> str:
    """A list as Themi shows it (F29g): its name, then each open item at its level, in the
    reader's style ("- ", "-- "; indented bullets; "1.", "1.1.")."""
    lines = [nl.name]

    def walk(parent: int | None, depth: int, number: str) -> None:
        level = [i for i in nl.open_items if i.parent_id == parent]
        for n, item in enumerate(level, 1):
            label = f"{number}{n}."
            if style == "numbers":
                lines.append(f"{label} {item.name}")
            elif style == "bullets":
                lines.append(f"{'  ' * (depth - 1)}\u2022 {item.name}")
            else:
                lines.append(f"{'-' * depth} {item.name}")
            walk(item.id, depth + 1, label)

    walk(None, 1, "")
    if len(lines) == 1:
        lines.append("Nothing on it.")
    if nl.ticked:
        lines.append(f"({len(nl.ticked)} ticked)")
    return "\n".join(lines)


def _lists(ctx: ToolContext) -> Lists:
    lists = ctx.services.maybe(keys.lists)
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
    "use. Items they wrote go straight on; anything else waits for their yes. People call "
    "list items tasks and tasks items: a named list means a list item, a due date or a "
    "person means a task. under: words from an item already on the list, to add these as "
    "its sub-items (one level below it, wherever it is), or ''. Several levels at once: "
    "start each item with its level's dashes ('- body doubling', '-- go upstairs').",
    {
        "list": {"type": "string", "description": "The list's name, as they said it."},
        "items": {"type": "array", "items": {"type": "string"}},
        "under": {"type": "string", "default": ""},
    },
)
async def add_to_list(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    lists = _lists(ctx)
    nl = lists.find(ctx.member, args["list"])
    under = str(args.get("under") or "").strip()
    parent = lists.match(nl, [under], ticked=False)[0] if under else None
    there = {
        name_key(i.name) for i in nl.open_items if i.parent_id == (parent.id if parent else None)
    }
    names, skipped, shaped = [], [], []
    for raw in args["items"]:
        depth, raw = _depth(str(raw))
        try:
            name = without_verb(_clean(raw, item_limit(nl), "list item"), ctx.request_text)
        except InvalidValue as exc:
            long = " ".join(str(raw).split()).strip(" ,.;:")
            reply = too_long(nl) if long else None
            raise ToolFailed(f"{str(exc).capitalize()}.", reply) from exc
        if not depth and (name_key(name) in there or name in names):
            skipped.append(name)
        else:
            names.append(name)
            shaped.append("-" * depth + (" " if depth else "") + name)
    if not names:
        if skipped:
            raise ToolDeclined(f"Already on {nl.name}: {and_list(skipped)}. Nothing was added.")
        raise ToolFailed("There were no items to add.")
    refuse_spending(names, ctx.request_text, prices=nl.purpose == THINGS_TO_BUY)
    text = and_list(names)
    summary = f"{text[:1].upper()}{text[1:]} for {nl.name}"
    if parent is not None:
        summary = f"{text[:1].upper()}{text[1:]} under {parent.name} on {nl.name}"
    said = and_list([f'"{n}"' for n in names]) if len(text) <= SAID_BACK else ""
    proposal = Proposal(
        ADD_CATEGORY,
        summary,
        ADD_EXECUTOR,
        {"list_id": nl.id, "items": shaped, "under": parent.id if parent else None},
        said=f"Added {said} to {nl.name}." if said else f"Added to {nl.name}.",
    )
    asked = (
        _said(names, ctx.request_text)
        and (
            asks_to_add(ctx.request_text, ctx.previous_text)
            or _opens_with(lists, ctx.member, nl, ctx.request_text)
        )
    ) or picture_asks_to_add(ctx, names)
    return replace(proposal, requested=asked)


def _opens_with(lists: Lists, member: Member, nl: NamedList, request_text: str) -> bool:
    """The message starts with this list's name, then the items: "Gift list. A scarf"
    asks to add them as plainly as "add a scarf to the gift list" (idea #115)."""
    found = OPENS_WITH_LIST.match(request_text)
    if found is None or len(list_key(found.group(1))) < 3:
        return False
    try:
        return lists.find(member, found.group(1)).id == nl.id
    except ToolFailed:
        return False


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
    below = 0
    for item in items:
        lists.tick(item, done, ctx.member)
        for child in lists.children(nl, item):  # F29g: its sub-items go with it
            if child.done != done:
                lists.tick(child, done, ctx.member)
                below += 1
    fresh = lists.get(nl.id, ctx.member)
    assert fresh is not None
    verb = "Ticked off" if done else "Unticked"
    sub_items = f" and its {below} sub-item{'s' if below != 1 else ''}" if below else ""
    return f"{verb} {and_list([i.name for i in items])}{sub_items}. Now: {words(fresh)}"


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
    below = 0
    if args["items"]:
        for item in lists.match(nl, args["items"]):
            below += len(lists.children(nl, item))  # they go with it (F29g)
            lists.remove(item)
            removed.append(item.name)
            nl = lists.reload(nl)
    cleared = lists.clear_ticked(nl) if args["ticked"] else 0
    if not removed and not cleared:
        raise ToolDeclined(f"Nothing to take off {nl.name}.")
    fresh = lists.get(nl.id, ctx.member)
    assert fresh is not None
    with_below = f" (and {below} sub-item{'s' if below != 1 else ''})" if below else ""
    done = [f"took off {and_list(removed)}{with_below}"] if removed else []
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
        nl = lists.find(ctx.member, args["list"])
        if any(i.parent_id for i in nl.open_items):
            # F29g (reply 271): with levels, Themi shows the list itself, in their style
            shown = render(
                nl, ctx.services.store.preferences(ctx.member.id, ListsPreferences).list_style
            )
            ctx.replies.append(shown)
            return f"Sent them the list as it is:\n{shown}"
        return lists.describe(nl)
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
    there = f", {nl.mirror.where} too" if nl.mirror else ""
    proposal = Proposal(
        DELETE_CATEGORY, f"Deleting the list {nl.name}{there}", DELETE_EXECUTOR, {"list_id": nl.id}
    )
    return replace(proposal, requested=named)


@tool(
    "move_list_item",
    "Move an item on one of Themi's lists under another item, as its sub-item ('put go "
    "upstairs under body doubling'), or back to the top level (under ''). Its own sub-items "
    "go with it.",
    {"list": {"type": "string"}, "item": {"type": "string"}, "under": {"type": "string"}},
)
async def move_list_item(ctx: ToolContext, args: dict[str, Any]) -> str:
    lists = _lists(ctx)
    nl = lists.find(ctx.member, args["list"])
    (item,) = lists.match(nl, [args["item"]], ticked=False)
    under = str(args["under"]).strip()
    parent = lists.match(nl, [under], ticked=False)[0] if under else None
    lists.move(nl, item, parent)
    fresh = lists.get(nl.id, ctx.member)
    assert fresh is not None
    where = f"under {parent.name}" if parent else "at the top level"
    return f"Moved {item.name} {where}. Now: {words(fresh)}"


# CR8a: the system prompt's rules about this module's feature.
PROMPT_RULES = (
    PromptFragment(
        "lists.a-named-list-someone",
        "act",
        220,
        """\
- A named list someone asks for ("a packing list", "my gift ideas") is one of Themi's
  lists (create_list, add_to_list...), not a task and not the grocery list.""",
    ),
)


class ListsModule(Module):
    """L1a: named lists Themi keeps."""

    name = "lists"
    title = "Lists"
    summary = "Named lists Themi keeps, made and changed from chat."
    tool_groups = (groups.LISTS,)
    preferences = ListsPreferences

    def install(self, ctx: ModuleContext) -> None:
        from themi.modules.web import MenuEntry
        from themi.web import icons, list_pages

        ctx.prompt(*PROMPT_RULES)
        ctx.web(
            list_pages.routes,
            MenuEntry(
                "/lists", "Lists", "Shopping and the other lists", "Main", 30, icon=icons.LISTS
            ),
        )
        ctx.provide(Lists(ctx.services)).install()
