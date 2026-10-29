"""Which list, as a card (F17b, Erin's idea #68).

"paper towels" went to the grocery list when Erin meant Things to Buy. When an item could
go on more than one list, the model calls `ask_which_list` instead of guessing or asking in
words: one card, a button per likely list (at most three) and [Not now].

    Paper towels: which list?
    [Grocery list] [Things to Buy] [Not now]

A tap is their answer in their own words, so the add is staged as asked for (the trust
tiers still decide whether it needs a yes), and the card is edited to say what happened.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from themi.autonomy import AutonomyError
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import buying, groceries
from themi.core.groceries import item_name
from themi.core.lists import ADD_CATEGORY, ADD_EXECUTOR, THINGS_TO_BUY, list_key, name_key
from themi.core.tools import Proposal, ToolContext, ToolFailed, tool

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.core.services import Services

log = logging.getLogger(__name__)

KIND = "which_list"
GROCERY = "grocery"
GROCERY_LABEL = "Grocery list"
GROCERY_WORDS = frozenset({"grocery", "grocery list", "groceries", "the grocery list"})
BUY_WORDS = frozenset({"things to buy", "to buy"})  # as list_key says them
MAX_LISTS = 3

QUESTION_TEXT = "{item}: which list?"
WAITING_TEXT = "{item}: {where}, waiting for a yes on the card below."
ALREADY_TEXT = "{item} is on {where} already."
LATER_TEXT = "{item}: left off the lists for now."
FAILED_TEXT = "{item}: that didn't go through, so nothing has changed."


class WhichList:
    def __init__(self, services: Services) -> None:
        self.services = services

    def install(self) -> None:
        self.services.button_handlers[KIND] = self.on_button
        self.services.tools.register(ask_which_list)
        self.services.which_list = self

    def target(self, member: Member, name: str) -> tuple[str, str]:
        """(the button's target, its label) for a list named in words. Raises ToolFailed."""
        if name.strip().lower() in GROCERY_WORDS:
            return GROCERY, GROCERY_LABEL
        lists = self.services.lists
        if lists is None:
            raise ToolFailed("Themi's lists aren't set up.")
        if list_key(name) in BUY_WORDS:  # made the first time it's needed
            nl = lists.things_to_buy(member)
        else:
            nl = lists.find(member, name)
        return str(nl.id), nl.name

    async def ask(self, member: Member, item: str, targets: list[tuple[str, str]]) -> None:
        buttons = [Button(label, KIND, {"item": item, "to": to}) for to, label in targets]
        buttons.append(Button("Not now", KIND, {"item": item, "to": ""}))
        await self.services.outbox.send(
            member, QUESTION_TEXT.format(item=_capital(item)), priority=Priority.REPLY,
            buttons=buttons,
        )  # fmt: skip

    async def put(self, member: Member, item: str, to: str) -> str:
        """Stage the add they picked, as asked for. Returns what the card says now."""
        proposal, where = self._proposal(member, item, to)
        if proposal is None:
            return ALREADY_TEXT.format(item=_capital(item), where=where)
        try:
            outcome = await self.services.autonomy.stage(
                proposal.category, member, proposal.summary, proposal.payload,
                proposal.executor, interactive=True, requested=True,
            )  # fmt: skip
        except AutonomyError:
            log.exception("Couldn't add %r for member %s", item, member.id)
            return FAILED_TEXT.format(item=_capital(item))
        if outcome.action.status == "pending":
            return WAITING_TEXT.format(item=_capital(item), where=where)
        if outcome.action.status == "done":
            return outcome.message
        return FAILED_TEXT.format(item=_capital(item))

    def _proposal(self, member: Member, item: str, to: str) -> tuple[Proposal | None, str]:
        """The add, or None when it's there already; and the list's name."""
        s = self.services
        if to == GROCERY:
            assert s.groceries is not None
            name = item_name(item)
            if s.groceries.is_needed(name) or name in s.groceries.awaiting_approval():
                return None, "the grocery list"
            return groceries.proposal([name]), "the grocery list"
        assert s.lists is not None
        nl = s.lists.get(int(to), member)
        if nl is None:
            raise ToolFailed("That list is gone.")
        if any(name_key(i.name) == name_key(item) for i in nl.open_items):
            return None, nl.name
        summary = f"{_capital(item)} for {nl.name}"
        if nl.purpose == THINGS_TO_BUY:  # its own executor remembers it isn't food (L2a)
            payload: dict[str, Any] = {"items": [{"name": item, "store": None}]}
            return Proposal(ADD_CATEGORY, summary, buying.ADD_EXECUTOR, payload), nl.name
        payload = {"list_id": nl.id, "items": [item]}
        return Proposal(ADD_CATEGORY, summary, ADD_EXECUTOR, payload), nl.name

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        item, to = str(event.button.payload["item"]), str(event.button.payload["to"])
        if not to:
            said = LATER_TEXT.format(item=_capital(item))
        else:
            try:
                said = await self.put(event.member, item, to)
            except ToolFailed as exc:
                said = str(exc)
        if event.button.message_id is not None:
            await self.services.outbox.edit(event.member, event.button.message_id, said)
        else:
            await self.services.outbox.send(event.member, said, priority=Priority.REPLY)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


@tool(
    "ask_which_list",
    "When something could go on more than one list ('paper towels': groceries or Things to "
    "Buy), ask with buttons instead of guessing or asking in words: one card with a button "
    "per likely list, most likely first, and Not now. lists: two or three names, 'grocery "
    "list' for the grocery list, otherwise as in the context's Lists ('Things to Buy'). One "
    "item per card. The card asks by itself; don't ask again in your reply.",
    {"item": {"type": "string"}, "lists": {"type": "array", "items": {"type": "string"}}},
)
async def ask_which_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    which = ctx.services.which_list
    assert which is not None
    item = " ".join(str(args["item"]).split())[:100]
    if not item:
        raise ToolFailed("Which item?")
    targets: list[tuple[str, str]] = []
    for name in args["lists"]:
        target = which.target(ctx.member, str(name))
        if target not in targets:
            targets.append(target)
    if len(targets) < 2:
        raise ToolFailed(
            "That's only one list: add it there with its own tool, no need to ask which."
        )
    await which.ask(ctx.member, item, targets[:MAX_LISTS])
    names = ", ".join(label for _, label in targets[:MAX_LISTS])
    return f"Asked which list ({names}, or not now) on a card with buttons; nothing is added yet."
