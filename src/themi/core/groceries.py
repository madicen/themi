"""The grocery list: Themi's own, the source of truth. OurGroceries mirrors it.

- Adding goes through the trust tiers: the `grocery_list_add` category (which
  a locked rule can make automatic) and the `groceries.add` executor. Both the
  `add_to_grocery_list` tool and the pantry's restocking stage it.
- Buying (a receipt, "bought eggs", the website's "Got it") marks the row
  bought; the pantry item goes back to plenty.
- Every change sets the row's mirror state to pending; the mirror job does
  the rest (`themi.connectors.ourgroceries`). Nothing here waits for it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.autonomy import ExecutionContext
from themi.core.tools import Proposal, ToolContext, ToolDeclined, staged_tool, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

CATEGORY = "grocery_list_add"
EXECUTOR = "groceries.add"
ItemStatus = Literal["needed", "bought", "removed"]


def item_name(raw: str) -> str:
    """How an item is stored: lowercase, single-spaced, no stray punctuation."""
    name = " ".join(re.sub(r"[^\w\s&'/-]", " ", raw).split()).strip(" -'/").lower()
    if not name:
        raise InvalidValue(f"{raw.strip()!r} isn't an item name")
    if len(name) > 60:
        raise InvalidValue("item names are at most 60 characters")
    return name


def and_list(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


@dataclass(frozen=True)
class GroceryItem:
    id: int
    name: str
    status: ItemStatus
    pantry_item_id: int | None
    added_by: int | None
    added_at: datetime
    mirrored: bool


def _item_from_row(row: dict[str, Any]) -> GroceryItem:
    return GroceryItem(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        pantry_item_id=row["pantry_item_id"],
        added_by=row["added_by"],
        added_at=datetime.fromisoformat(row["added_at"]),
        mirrored=row["mirror_state"] == "done",
    )


class GroceryList:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.groceries = self
        s.autonomy.executors.register(EXECUTOR)(self._execute_add)
        s.tools.register(add_to_grocery_list)
        s.tools.register(show_grocery_list)

    # ----- reading ------------------------------------------------------------

    def needed(self) -> list[GroceryItem]:
        rows = self.db.query("SELECT * FROM grocery_list WHERE status = 'needed' ORDER BY id")
        return [_item_from_row(r) for r in rows]

    def get(self, item_id: int) -> GroceryItem | None:
        row = self.db.one("SELECT * FROM grocery_list WHERE id = ?", (item_id,))
        return _item_from_row(row) if row else None

    def is_needed(self, name: str) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM grocery_list WHERE name = ? AND status = 'needed'",
                (item_name(name),),
            )
        )

    # ----- changing -----------------------------------------------------------

    def add(
        self, names: list[str], *, by: Member | None, action_id: int | None = None
    ) -> list[str]:
        """Put items on the list; returns the ones that weren't there already."""
        added = []
        now = to_utc_iso(clock.now())
        for raw in names:
            name = item_name(raw)
            if name in added or self.is_needed(name):
                continue
            pantry = self.db.one("SELECT id FROM pantry_items WHERE name = ?", (name,))
            self.db.execute(
                "INSERT INTO grocery_list (name, pantry_item_id, added_by, action_id, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, pantry["id"] if pantry else None, by.id if by else None, action_id, now),
            )
            added.append(name)
        return added

    def finish(self, name: str, status: ItemStatus = "bought", *, since: str | None = None) -> bool:
        """Take an item off the list (bought or removed). `since`: only rows added before it."""
        changed = self.db.update(
            "UPDATE grocery_list SET status = ?, done_at = ?, mirror_state = 'pending', "
            "mirror_attempts = 0, mirror_after = NULL "
            "WHERE name = ? AND status = 'needed' AND (? IS NULL OR added_at <= ?)",
            (status, to_utc_iso(clock.now()), item_name(name), since, since),
        )
        return changed > 0

    def awaiting_approval(self) -> set[str]:
        """Items already staged and waiting on a yes, so they aren't staged twice."""
        names: set[str] = set()
        for row in self.db.query(
            "SELECT payload FROM pending_actions WHERE category = ? "
            "AND status IN ('pending', 'snoozed', 'failed')",
            (CATEGORY,),
        ):
            names.update(item_name(n) for n in json.loads(row["payload"]).get("items", []))
        return names

    async def _execute_add(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        names = [str(n) for n in payload.get("items", [])]
        added = self.add(names, by=ctx.member, action_id=ctx.action_id)
        if not added:
            return f"{and_list(names)} {'was' if len(names) == 1 else 'were'} already on the list."
        return f"Added {and_list(added)} to the grocery list."


def list_summary(names: list[str]) -> str:
    """How an approval reads: an offer ("Eggs for the grocery list"), never an order, so the
    PDA shield never has to rewrite it."""
    text = and_list(names)
    return f"{text[:1].upper()}{text[1:]} for the grocery list"


def proposal(names: list[str]) -> Proposal:
    return Proposal(CATEGORY, list_summary(names), EXECUTOR, {"items": names})


@staged_tool(
    "add_to_grocery_list",
    "Put items on the family's grocery list (it shows in OurGroceries too) when someone asks "
    "for that. It's not for things running low or out: update_pantry records those and offers "
    "staples for the list itself.",
    {
        "items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Plain item names, like 'olive oil' or 'cat food'.",
        }
    },
)
async def add_to_grocery_list(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    groceries = ctx.services.groceries
    assert groceries is not None
    waiting = groceries.awaiting_approval()
    names, skipped = [], []
    for raw in args["items"]:
        name = item_name(str(raw))
        if name in names or name in skipped:
            continue
        if name in waiting or groceries.is_needed(name):
            skipped.append(name)
        else:
            names.append(name)
    if not names:
        if skipped:
            raise ToolDeclined(
                f"Nothing new to ask about: already on the list or already waiting on a yes: "
                f"{and_list(skipped)}. No new approval was sent."
            )
        raise InvalidValue("no items to add")
    # Asked for, if every item is in what they just wrote ("add white miso", "out of eggs");
    # restocking, receipts and items the model inferred still wait for a yes.
    said = " ".join(re.sub(r"[^\w\s&'/-]", " ", ctx.request_text).split()).lower()
    asked = bool(said) and all(re.search(rf"\b{re.escape(n)}\b", said) for n in names)
    return replace(proposal(names), requested=asked)


@tool("show_grocery_list", "What's on the family's grocery list right now.", {})
async def show_grocery_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    groceries = ctx.services.groceries
    assert groceries is not None
    items = groceries.needed()
    waiting = sorted(groceries.awaiting_approval())
    text = "On the list: " + (", ".join(i.name for i in items) if items else "nothing") + "."
    if waiting:
        text += f" Waiting on a yes: {', '.join(waiting)}."
    return text
