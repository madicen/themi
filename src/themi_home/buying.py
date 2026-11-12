"""Things to buy that aren't food, and where things come from (L2a, Erin's idea #6).

- Food goes on the grocery list (OurGroceries) as before; anything else goes on the
  household's Things to Buy list, which is on the wall (the family's choice: the wall's
  Shopping List, renamed). When it's unclear, Themi asks.
- What's settled is remembered by item name (`item_homes`): food or not, and the store it
  usually comes from ("body wash comes from Amazon"). A remembered answer stops the model
  from putting an item on the other list by itself; what someone asks for in their own
  words wins, and is remembered instead.
- Receipts (`themi_home.pantry`) tick off what they bought and teach the store.
- A cart staged for a store (L2b: the Safeway cart) offers the open items that usually
  come from there, in the same approval.

Someday buys (F36b, Erin's idea #185): an item they mean to research or buy someday is on
Things to Buy with `someday` set, when their words say so ("research", "someday", "one
day"), never guessed from the item. It's theirs: the cart leaves it out unless the cart is
for whoever added it, and once a week at most (and only once it's been there a week) the
adder alone gets a gentle low-priority nudge about the one asked about least lately: look
into it now (a web search), keep it for someday, or not needed. None in burnout mode or
while their messages are paused. `set_someday` makes one ordinary (named as they decided,
with a store) or someday again.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import groups, keys
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool, tool
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.prompt import PromptFragment
from themi.standard.lists import (
    ADD_CATEGORY,
    THINGS_TO_BUY,
    ListItem,
    Lists,
    NamedList,
    name_key,
)
from themi_home.groceries import and_list, asks_to_add, picture_asks_to_add, refuse_spending

if TYPE_CHECKING:
    from themi.core.services import Services

Kind = Literal["food", "other"]
ADD_EXECUTOR = "buying.add"
MAX_STORE = 40

# F36b: someday buys.
SOMEDAY_KIND = "someday"
SOMEDAY_EVERY = timedelta(days=7)  # a nudge a week at most, about an item there a week
SOMEDAY_JOB_EVERY = timedelta(hours=1)
# Their words say it's for later or for research; the item alone never does.
SOMEDAY_SAID = re.compile(
    r"\b(?:research\w*|someday|some day|eventually|one day|look into|looking into|"
    r"down the road|at some point|maybe buy|later)\b",
    re.IGNORECASE,
)
# "someday: X", "research buy: X", "Things to research buy. X": a list-like ask.
SOMEDAY_PREFIX = re.compile(
    r"^\s*[\w' ]{0,30}\b(?:someday|research\w*)\b[\w' ]{0,30}[.:]\s+\S", re.IGNORECASE
)
SOMEDAY_NUDGE_TEXT = "The {item} is still on your someday list, if you feel like looking into it."
LOOK_LABEL, KEEP_LABEL, DROP_LABEL = "Look into it now", "Keep it for someday", "Not needed"
LOOK_TEXT = "Look into the {item} for me: a few options to buy, with where to get them."
KEPT_TEXT = "{nudge}\nKept on your someday list."
DROPPED_TEXT = "{nudge}\nTook it off Things to Buy."
GONE_TEXT = "{nudge}\nIt's not on Things to Buy any more."
PROMPT_RULES = (
    PromptFragment(
        "buying.someday-buys",
        "act",
        150,
        """\
- Someday and research buys: something they mean to research or buy someday ("Things
  to research buy. VNS device", "someday: a dog bed") goes on Things to Buy with someday set,
  only when their words say so. It stays theirs: never bring someone's someday item up with
  anyone else unless that person asks you to. When their research ends in a decision ("I'll
  get the Furhaven one"), set_someday makes it ordinary, named as they said it.""",
    ),
)


def _store(raw: str) -> str | None:
    store = " ".join(str(raw).split())[:MAX_STORE]
    return store or None


def _said(names: list[str], request_text: str) -> bool:
    said = name_key(request_text)
    return bool(said) and all(re.search(rf"\b{re.escape(name_key(n))}\b", said) for n in names)


def _matches(item: str, bought: str) -> bool:
    """A receipt line for this item: the same words, or one name inside the other
    ("body wash" and "lavender body wash")."""
    a, b = name_key(item), name_key(bought)
    if not a or not b:
        return False
    return a == b or bool(
        re.search(rf"\b{re.escape(a)}\b", b) or re.search(rf"\b{re.escape(b)}\b", a)
    )


class ThingsToBuy:
    def __init__(self, services: Services, lists: Lists) -> None:
        self.services = services
        self.lists = lists
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.provide(keys.buying, self)
        s.autonomy.executors.register(ADD_EXECUTOR)(self._execute_add)
        s.tools.register(add_to_things_to_buy)
        s.tools.register(set_usual_store)
        s.tools.register(set_someday)
        s.button_handlers[SOMEDAY_KIND] = self.on_someday_button

    # ----- what's known about an item -----------------------------------------------------

    def kind_of(self, name: str) -> Kind | None:
        row = self.db.one("SELECT kind FROM item_homes WHERE name_key = ?", (name_key(name),))
        return row["kind"] if row else None

    def store_of(self, name: str) -> str | None:
        row = self.db.one("SELECT store FROM item_homes WHERE name_key = ?", (name_key(name),))
        return row["store"] if row else None

    def remember(self, name: str, *, kind: Kind | None = None, store: str | None = None) -> None:
        """Settle what's known about an item; None leaves that part as it was."""
        self.db.execute(
            "INSERT INTO item_homes (name_key, kind, store, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name_key) DO UPDATE SET kind = COALESCE(excluded.kind, kind), "
            "store = COALESCE(excluded.store, store), updated_at = excluded.updated_at",
            (name_key(name), kind, store, to_utc_iso(clock.now())),
        )

    def forget_store(self, name: str) -> None:
        self.db.execute("UPDATE item_homes SET store = NULL WHERE name_key = ?", (name_key(name),))

    def from_store(self, member: Member, store: str) -> tuple[NamedList, list[str]] | None:
        """Things to Buy and its open items that usually come from `store` ("Safeway's" and
        "Safeway" both match "safeway"); None when there's no such list yet, which this
        never makes."""
        row = self.db.one("SELECT id FROM lists WHERE purpose = ?", (THINGS_TO_BUY,))
        nl = self.lists.get(row["id"], member) if row else None
        if nl is None:
            return None
        wanted = re.escape(name_key(store))
        stores = self.lists.stores(nl)
        later = self.lists.someday(nl)
        names = [
            i.name
            for i in nl.open_items
            if re.search(rf"\b{wanted}\b", name_key(stores.get(i.id, "")))
            and (i.id not in later or later[i.id] == member.id)  # F36b: someday stays theirs
        ]
        return nl, names

    # ----- someday buys (F36b) --------------------------------------------------------------

    def someday_item(self, member: Member, words: str) -> ListItem | None:
        """The open Things to Buy item these words name, best first: the same name, else
        one name inside the other."""
        row = self.db.one("SELECT id FROM lists WHERE purpose = ?", (THINGS_TO_BUY,))
        nl = self.lists.get(row["id"], member) if row else None
        if nl is None:
            return None
        items = nl.open_items
        key = name_key(words)
        return next((i for i in items if name_key(i.name) == key), None) or next(
            (i for i in items if _matches(i.name, words)), None
        )

    async def someday_nudges(self) -> int:
        """Scheduler job: at most one nudge a week for each person, about one of their own
        someday items, never in burnout mode or while their messages are paused."""
        now = clock.now()
        sent = 0
        for member in self.services.store.list_members():
            if not member.reachable or self._holding(member):
                continue
            if self._asked_lately(member, now):
                continue
            row = self.db.one(
                "SELECT i.* FROM list_items i JOIN lists l ON l.id = i.list_id "
                "WHERE l.purpose = ? AND i.someday = 1 AND i.done = 0 AND i.added_by = ? "
                "AND i.added_at <= ? ORDER BY i.someday_asked_at IS NOT NULL, "
                "i.someday_asked_at, i.id LIMIT 1",
                (THINGS_TO_BUY, member.id, to_utc_iso(now - SOMEDAY_EVERY)),
            )
            if row is None:
                continue
            await self._nudge(member, row, now)
            sent += 1
        return sent

    def _holding(self, member: Member) -> bool:
        burnout = self.services.maybe(keys.burnout)
        if burnout is not None and burnout.current(member):
            return True
        return self.services.outbox.pauses.held_until(member, SOMEDAY_KIND) is not None

    def _asked_lately(self, member: Member, now: datetime) -> bool:
        last = self.db.scalar(
            "SELECT MAX(i.someday_asked_at) FROM list_items i JOIN lists l ON l.id = i.list_id "
            "WHERE l.purpose = ? AND i.added_by = ?",
            (THINGS_TO_BUY, member.id),
        )
        return last is not None and datetime.fromisoformat(last) > now - SOMEDAY_EVERY

    async def _nudge(self, member: Member, row: dict[str, Any], now: datetime) -> None:
        item = str(row["name"])
        self.db.execute(
            "UPDATE list_items SET someday_asked_at = ? WHERE id = ?", (to_utc_iso(now), row["id"])
        )
        tap = {"item": row["id"]}
        await self.services.outbox.send(
            member,
            SOMEDAY_NUDGE_TEXT.format(item=item),
            priority=Priority.LOW,  # waits for a good moment
            kind=SOMEDAY_KIND,
            buttons=[
                Button(LOOK_LABEL, "reply", {"text": LOOK_TEXT.format(item=item)}),
                Button(KEEP_LABEL, SOMEDAY_KIND, {**tap, "choice": "keep"}),
                Button(DROP_LABEL, SOMEDAY_KIND, {**tap, "choice": "drop"}),
            ],
            dedupe_key=f"someday-{row['id']}-{now.date().isoformat()}",
            expires=now + timedelta(days=1),  # held past a day (a pause began): not now
        )

    async def on_someday_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        row = self.db.one(
            "SELECT * FROM list_items WHERE id = ? AND added_by = ?",
            (int(payload["item"]), event.member.id),
        )
        nudge = SOMEDAY_NUDGE_TEXT.format(item=row["name"]) if row else "That someday item"
        if row is None or row["done"]:
            text = GONE_TEXT.format(nudge=nudge)
        elif payload.get("choice") == "drop":
            item = next(
                (i for i in self.lists.things_to_buy(event.member).items if i.id == row["id"]),
                None,
            )
            if item is not None:
                self.lists.remove(item)
            text = DROPPED_TEXT.format(nudge=nudge)
        else:
            self.db.execute(
                "UPDATE list_items SET someday_asked_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), row["id"]),
            )
            text = KEPT_TEXT.format(nudge=nudge)
        if event.message_id is not None:
            await self.services.outbox.edit(event.member, event.message_id, text)

    # ----- bought -------------------------------------------------------------------------

    def bought(self, names: list[str], vendor: str, member: Member) -> list[str]:
        """A receipt's items: matching things to buy are ticked off, and the store is
        learned for them. Returns the items ticked."""
        nl = self.lists.things_to_buy(member)
        store = _store(vendor)
        ticked = []
        for item in nl.open_items:
            if any(_matches(item.name, n) for n in names):
                self.lists.tick(item, True, None)
                if store:
                    self.remember(item.name, kind="other", store=store)
                ticked.append(item.name)
        return ticked

    async def _execute_add(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        nl = self.lists.things_to_buy(ctx.member)
        entries = [(str(e["name"]), e.get("store") or None) for e in payload.get("items", [])]
        added = self.lists.add(nl, [n for n, _ in entries], ctx.member)
        for name, store in entries:
            self.remember(name, kind="other", store=store)
        later = {name_key(str(e["name"])) for e in payload.get("items", []) if e.get("someday")}
        for item in self.lists.reload(nl).open_items:
            if name_key(item.name) in later and item.parent_id is None:
                self.lists.set_someday(item, True)
        if not added:
            names = and_list([n for n, _ in entries])
            return f"{names} {'was' if len(entries) == 1 else 'were'} on {nl.name} already."
        return f"Added {and_list(added)} to {nl.name}."


def _buying(ctx: ToolContext) -> ThingsToBuy:
    buying = ctx.services.maybe(keys.buying)
    if buying is None:
        raise ToolFailed("The Things to Buy list isn't set up.")
    return buying


@staged_tool(
    "add_to_things_to_buy",
    "Put things to buy that aren't food (body wash, light bulbs, batteries, a charger) on the "
    "household's Things to Buy list, which is on the wall. store: "
    "where it usually comes from if they said ('Amazon'), else ''. someday: true only when "
    "their words say it's to research or buy someday ('Things to research buy. X', "
    "'someday: X'), never from the item alone. Items they wrote go straight on; anything "
    "else waits for their yes.",
    {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "store": {"type": "string"},
                    "someday": {"type": "boolean"},
                },
                "required": ["name", "store"],
                "additionalProperties": False,
            },
        }
    },
)
async def add_to_things_to_buy(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    buying = _buying(ctx)
    nl = buying.lists.things_to_buy(ctx.member)
    there = {name_key(i.name) for i in nl.open_items}
    entries: list[dict[str, Any]] = []
    skipped = []
    for raw in args["items"]:
        name = " ".join(str(raw.get("name", "")).split())[:100]
        if not name:
            continue
        if name_key(name) in there or any(name_key(e["name"]) == name_key(name) for e in entries):
            skipped.append(name)
            continue
        entry: dict[str, Any] = {"name": name, "store": _store(raw.get("store", ""))}
        if raw.get("someday") and SOMEDAY_SAID.search(ctx.request_text):  # their words
            entry["someday"] = True
        entries.append(entry)
    if not entries:
        if skipped:
            raise ToolDeclined(f"Already on {nl.name}: {and_list(skipped)}. Nothing was added.")
        raise ToolFailed("There were no items to add.")
    names = [e["name"] for e in entries]
    refuse_spending(names, ctx.request_text)
    asked = (
        _said(names, ctx.request_text)
        and (
            asks_to_add(ctx.request_text, ctx.previous_text)
            or bool(SOMEDAY_PREFIX.match(ctx.request_text))  # F36b: "someday: dog bed"
        )
    ) or picture_asks_to_add(ctx, names)
    food = [n for n in names if buying.kind_of(n) == "food"]
    if food and not asked:
        raise ToolFailed(
            f"{and_list(food)} went on the grocery list before (remembered as food): use "
            "add_to_grocery_list, or ask_which_list."
        )
    text = and_list(names)
    proposal = Proposal(
        ADD_CATEGORY,
        f"{text[:1].upper()}{text[1:]} for {nl.name}",
        ADD_EXECUTOR,
        {"items": entries},
    )
    return replace(proposal, requested=asked)


@tool(
    "set_usual_store",
    "Remember where something usually comes from ('body wash comes from Amazon', 'we get "
    "light bulbs at Home Depot'), so the Things to Buy list is sorted by store. store empty "
    "forgets it.",
    {"item": {"type": "string"}, "store": {"type": "string"}},
)
async def set_usual_store(ctx: ToolContext, args: dict[str, Any]) -> str:
    buying = _buying(ctx)
    name = " ".join(str(args["item"]).split())
    if not name:
        raise ToolFailed("Which item?")
    store = _store(args["store"])
    if store is None:
        buying.forget_store(name)
        return f"Forgot where {name} comes from."
    try:
        buying.remember(name, store=store)
    except InvalidValue as exc:
        raise ToolFailed(str(exc)) from exc
    return f"Noted: {name} usually comes from {store}."


@tool(
    "set_someday",
    "Make a Things to Buy item a someday buy (to research or buy one day) or an ordinary one "
    "again ('let's just get the dog bed'). When their research ends in a decision ('I'll get "
    "the Furhaven one'): someday false, name as they said it, store if they gave one. name "
    "and store: '' leaves them as they are.",
    {
        "item": {"type": "string"},
        "someday": {"type": "boolean"},
        "name": {"type": "string", "default": ""},
        "store": {"type": "string", "default": ""},
    },
)
async def set_someday(ctx: ToolContext, args: dict[str, Any]) -> str:
    buying = _buying(ctx)
    item = buying.someday_item(ctx.member, str(args["item"]))
    if item is None:
        raise ToolFailed(f"There's no {args['item']} on Things to Buy.")
    on = bool(args["someday"])
    buying.lists.set_someday(item, on)
    name = " ".join(str(args.get("name") or "").split())
    if name and name_key(name) != name_key(item.name):
        try:
            buying.lists.rename_item(item, name)
        except InvalidValue as exc:
            raise ToolFailed(str(exc)) from exc
    shown = name or item.name
    store = _store(args.get("store") or "")
    if store:
        buying.remember(shown, kind="other", store=store)
    where = f", from {store}" if store else ""
    if on:
        return f"{shown} is a someday buy on Things to Buy now, kept for whoever added it."
    return f"{shown} is an ordinary thing to buy on Things to Buy now{where}."


class BuyingModule(Module):
    """L2a: things to buy that aren't food, and their stores."""

    name = "buying"
    title = "Things to buy"
    summary = "Things to buy that aren't food, sorted by the store that has them."
    tool_groups = (groups.LISTS,)
    requires = ("lists",)

    def install(self, ctx: ModuleContext) -> None:
        buying = ctx.provide(ThingsToBuy(ctx.services, ctx.get(Lists)))
        buying.install()
        ctx.prompt(*PROMPT_RULES)
        ctx.periodic("buying.someday", SOMEDAY_JOB_EVERY, buying.someday_nudges)
