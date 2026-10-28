"""Approvals in the chat: asking, answering, and tidying up afterwards.

When an action starts waiting on someone, they get a message with
[Go ahead] [Not now]. They can answer by:
- tapping a button,
- reacting ✅ (go ahead) or 💤 (not now) to that message,
- a bare "yes" / "no" / "not now" when it's the only thing waiting,
- /pending, which lists everything open with buttons.

However it's answered, the original message is edited to show the result,
so the thread doesn't fill up. "Not now" snoozes rather than declines: the
action comes back later, which feels gentler than a hard no. Anything left
unanswered for `ttl` lapses quietly (its message is edited, nothing new is
sent).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Literal

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.accounts.store import Actor
from themi.autonomy import Action, Autonomy, Decision, InvalidTransition
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Outbox, Priority
from themi.core.services import AwaitingItem, Services
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

APPROVAL_TTL = timedelta(days=3)
CARD_WITHIN = timedelta(hours=2)  # a card waits at most this long for a good moment (F15b)
APPROVE_REACTIONS = frozenset({"✅", "👍", "👌"})
SNOOZE_REACTIONS = frozenset({"💤", "⏰"})

ASK_TEXT = "{summary}\nGo ahead, or not now?"
RETRY_TEXT = "{summary}\nThis one didn't go through earlier. Try again, or leave it?"
RESULT_TEXT = {
    "done": "{summary}\nDone. {message}",
    "declined": "{summary}\nLeft as is.",
    "snoozed": "{summary}\nNo rush, this will come back later.",
    "failed": "{summary}\nThat didn't go through. It's in /pending to try again.",
    "expired": "{summary}\nThis one lapsed. Happy to line it up again any time.",
}
ALREADY_TEXT = "That one's already taken care of."
NOTHING_PENDING_TEXT = "Nothing is waiting on you at the moment."

ChatDecision = Literal["yes", "no", "later"]
_CHAT_DECISIONS = {"yes": Decision.APPROVE, "no": Decision.DECLINE, "later": Decision.SNOOZE}


def buttons_for(action: Action) -> list[Button]:
    if action.status == "failed":
        return [
            Button("Try again", "approval", {"action": action.id, "decision": "approve"}),
            Button("Leave it", "approval", {"action": action.id, "decision": "decline"}),
        ]
    return [
        Button("Go ahead", "approval", {"action": action.id, "decision": "approve"}),
        Button("Not now", "approval", {"action": action.id, "decision": "snooze"}),
    ]


class ApprovalsUI:
    def __init__(self, autonomy: Autonomy, outbox: Outbox, *, ttl: timedelta = APPROVAL_TTL):
        self.autonomy = autonomy
        self.outbox = outbox
        self.store = autonomy.store
        self.db = autonomy.db
        self.ttl = ttl

    def install(self, services: Services) -> None:
        """Wire approvals into the agent: listeners, buttons, reactions, fast path, /pending."""
        self.autonomy.pending_listeners.append(self.on_pending)
        self.autonomy.withdrawn_listeners.append(self.on_withdrawn)
        services.button_handlers["approval"] = self.on_button
        services.reaction_handlers.append(self.on_reaction)
        services.awaiting_sources.append(self.awaiting_items)
        services.add_command("/pending", self.on_pending_command, "See what's waiting on you")

    # ----- asking ---------------------------------------------------------------

    async def on_pending(self, action: Action, interactive: bool) -> None:
        await self.ask(action, priority=Priority.REPLY if interactive else Priority.NORMAL)

    async def ask(self, action: Action, *, priority: Priority) -> None:
        member = self.store.get_member(action.member_id)
        template = RETRY_TEXT if action.status == "failed" else ASK_TEXT
        result = await self.outbox.send(
            member,
            template.format(summary=action.summary),
            priority=priority,
            buttons=buttons_for(action),
            kind="approval",
            deadline=clock.now() + CARD_WITHIN,  # the daily limit doesn't hold it to tomorrow
            expires=action.expires_at,
        )
        if result.outbox_id is not None:
            self._remember_message(action.id, member.id, result.outbox_id)

    def _remember_message(self, action_id: int, member_id: int, outbox_id: int) -> None:
        self.db.execute(
            "INSERT INTO approval_messages (action_id, member_id, outbox_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (action_id, member_id, outbox_id, to_utc_iso(clock.now())),
        )

    # ----- answering --------------------------------------------------------------

    async def resolve(self, action_id: int, decision: Decision, by: Actor) -> str:
        """Answer an action however the answer arrived. Returns a line for the person."""
        try:
            outcome = await self.autonomy.resolve(action_id, decision, by=by)
        except InvalidTransition:
            return ALREADY_TEXT
        except (PermissionDenied, NotFound):
            return "That one isn't yours to answer."
        await self._show_result(outcome.action, outcome.message)
        return outcome.message

    async def on_withdrawn(self, action: Action, reason: str) -> None:
        await self._edit_cards(action, f"{action.summary}\n{reason}")

    async def _show_result(self, action: Action, message: str) -> None:
        template = RESULT_TEXT.get(action.status)
        if template is None:
            return
        await self._edit_cards(action, template.format(summary=action.summary, message=message))

    async def _edit_cards(self, action: Action, text: str) -> None:
        for row in self.db.query(
            "SELECT * FROM approval_messages WHERE action_id = ?", (action.id,)
        ):
            member = self.store.get_member(row["member_id"])
            message_id = self.outbox.message_id(row["outbox_id"])
            if message_id is None:
                self.outbox.cancel(row["outbox_id"])  # never went out: no need now
            else:
                await self.outbox.edit(member, message_id, text)
            self.db.execute("DELETE FROM approval_messages WHERE id = ?", (row["id"],))

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        action_id = int(event.button.payload["action"])
        decision = Decision(event.button.payload["decision"])
        reply = await self.resolve(action_id, decision, event.member)
        if reply == ALREADY_TEXT or reply.startswith("That one isn't"):
            await self.outbox.send(event.member, reply, priority=Priority.REPLY)

    async def on_reaction(self, event: InboundEvent) -> None:
        assert event.reaction is not None
        emoji = set(event.reaction.added)
        if emoji & APPROVE_REACTIONS:
            decision = Decision.APPROVE
        elif emoji & SNOOZE_REACTIONS:
            decision = Decision.SNOOZE
        else:
            return
        action_id = self._action_for_message(event.member.id, event.reaction.message_id)
        if action_id is not None:
            await self.resolve(action_id, decision, event.member)

    def _action_for_message(self, member_id: int, message_id: int) -> int | None:
        row = self.db.one(
            "SELECT m.action_id FROM approval_messages m JOIN outbox o ON o.id = m.outbox_id "
            "WHERE m.member_id = ? AND o.telegram_message_id = ? ORDER BY m.id DESC LIMIT 1",
            (member_id, message_id),
        )
        return row["action_id"] if row else None

    def awaiting_items(self, member: Member) -> list[AwaitingItem]:
        def resolver(action_id: int):
            async def resolve(decision: ChatDecision) -> str:
                return await self.resolve(action_id, _CHAT_DECISIONS[decision], member)

            return resolve

        return [
            AwaitingItem(
                f"action:{a.id}", a.summary, resolver(a.id), self._asked_in(a.id, member.id)
            )
            for a in self.autonomy.awaiting(member)
        ]

    def _asked_in(self, action_id: int, member_id: int) -> tuple[int, ...]:
        rows = self.db.query(
            "SELECT o.telegram_message_id FROM approval_messages m JOIN outbox o "
            "ON o.id = m.outbox_id WHERE m.action_id = ? AND m.member_id = ? "
            "AND o.telegram_message_id IS NOT NULL",
            (action_id, member_id),
        )
        return tuple(r["telegram_message_id"] for r in rows)

    async def on_pending_command(self, member: Member, argument: str) -> None:
        actions = self.autonomy.open_for(member)
        if not actions:
            await self.outbox.send(member, NOTHING_PENDING_TEXT, priority=Priority.REPLY)
            return
        count = len(actions)
        header = "One thing is waiting:" if count == 1 else f"{count} things are waiting:"
        await self.outbox.send(member, header, priority=Priority.REPLY)
        for action in actions:
            template = RETRY_TEXT if action.status == "failed" else ASK_TEXT
            result = await self.outbox.send(
                member,
                template.format(summary=action.summary),
                priority=Priority.REPLY,
                buttons=buttons_for(action),
                kind="approval",
            )
            if result.outbox_id is not None:
                self._remember_message(action.id, member.id, result.outbox_id)

    # ----- housekeeping (scheduler) -------------------------------------------------

    async def resurface(self) -> int:
        """Snoozed actions whose time has come are asked about again."""
        actions = self.autonomy.resurface_snoozed()
        for action in actions:
            await self.ask(action, priority=Priority.NORMAL)
        return len(actions)

    async def expire(self) -> int:
        actions = self.autonomy.expire_stale(self.ttl)
        for action in actions:
            await self._show_result(action, "")
        return len(actions)
