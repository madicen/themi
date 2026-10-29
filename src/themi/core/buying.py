"""Things to buy that aren't food, and where things come from (L2a, Erin's idea #6).

- Food goes on the grocery list (OurGroceries) as before; anything else goes on the
  household's Things to Buy list, which is on the wall (the family's choice: the wall's
  Shopping List, renamed). When it's unclear, Themi asks.
- What's settled is remembered by item name (`item_homes`): food or not, and the store it
  usually comes from ("body wash comes from Amazon"). A remembered answer stops the model
  from putting an item on the other list by itself; what someone asks for in their own
  words wins, and is remembered instead.
- Receipts (`themi.core.pantry`) tick off what they bought and teach the store.
- L2b will offer the items for a store when a cart for it is staged.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.autonomy import ExecutionContext
from themi.core.groceries import and_list, asks_to_add, refuse_spending
from themi.core.lists import ADD_CATEGORY, Lists, name_key
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

Kind = Literal["food", "other"]
ADD_EXECUTOR = "buying.add"
MAX_STORE = 40


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
        s.buying = self
        s.autonomy.executors.register(ADD_EXECUTOR)(self._execute_add)
        s.tools.register(add_to_things_to_buy)
        s.tools.register(set_usual_store)

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
        if not added:
            names = and_list([n for n, _ in entries])
            return f"{names} {'was' if len(entries) == 1 else 'were'} on {nl.name} already."
        return f"Added {and_list(added)} to {nl.name}."


def _buying(ctx: ToolContext) -> ThingsToBuy:
    buying = ctx.services.buying
    if buying is None:
        raise ToolFailed("The Things to Buy list isn't set up.")
    return buying


@staged_tool(
    "add_to_things_to_buy",
    "Put things to buy that aren't food (body wash, light bulbs, batteries, a charger) on the "
    "household's Things to Buy list, which is on the wall. Food and kitchen staples go on the "
    "grocery list (add_to_grocery_list). If it isn't clear which, ask_which_list. store: "
    "where it usually comes from if they said ('Amazon'), else ''. Items they wrote go "
    "straight on; anything else waits for their yes.",
    {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "store": {"type": "string"}},
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
        entries.append({"name": name, "store": _store(raw.get("store", ""))})
    if not entries:
        if skipped:
            raise ToolDeclined(f"Already on {nl.name}: {and_list(skipped)}. Nothing was added.")
        raise ToolFailed("There were no items to add.")
    names = [e["name"] for e in entries]
    refuse_spending(names, ctx.request_text)
    asked = _said(names, ctx.request_text) and asks_to_add(ctx.request_text, ctx.previous_text)
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
