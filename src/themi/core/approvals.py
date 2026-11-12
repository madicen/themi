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

A category in `held` gets no card of its own: another module asks about them
together (F16b: noise emails, in one message at the person's chosen time). They
still show in /pending, and a bare "yes" never answers one unseen.

Approvals triage stages from one email thread (or one sender, a few minutes apart) share
one message instead (F26b): see `themi.core.approval_groups`.

F37c (Michael's idea #188, "these email things need a 'not ever' option"): a kind of card a
module registers in `not_ever` gets a third button, [Not ever]. It declines the card for
good, and the card then asks once whether to skip that sender's offers of this kind from
now on: [Yes, skip them] [Just this one]. The module keeps the skipped senders.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.accounts.store import Actor
from themi.autonomy import Action, Autonomy, Decision, InvalidTransition
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Outbox, Priority
from themi.core.approval_groups import ApprovalGroups
from themi.core.services import AwaitingItem, Services
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

APPROVAL_TTL = timedelta(days=3)
CARD_WITHIN = timedelta(hours=2)  # a card waits at most this long for a good moment (F15b)
APPROVE_REACTIONS = frozenset({"✅", "👍", "👌"})
SNOOZE_REACTIONS = frozenset({"💤", "⏰"})
DECLINE_REACTION = "👎"  # F38c
DECLINED_BY_REACTION = "declined by the 👎"

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


NEVER = "never"  # the button's decision: declined for good, then the sender question (F37c)
NOT_EVER_KIND = "not_ever"
NOT_EVER_ASK = "{head}\nLeft as is, for good. Skip {words} from {name} from now on?"
FOR_GOOD_TEXT = "{head}\nLeft as is, for good."
SKIPPED_TEXT = "{head}\nLeft as is. No more {words} from {name}."
MAX_NAME = 60


@dataclass(frozen=True)
class NotEver:
    """F37c: a kind of card that can be turned down for good. `words` name its offers
    ("calendar offers"); `sender(action)` is (address, name) of whoever's email made it, or
    None; `skip(member, address, category)` stops that sender's offers of this kind."""

    words: str
    sender: Callable[[Action], tuple[str, str] | None]
    skip: Callable[[Member, str, str], None]


def buttons_for(action: Action, *, not_ever: bool = False) -> list[Button]:
    if action.status == "failed":
        return [
            Button("Try again", "approval", {"action": action.id, "decision": "approve"}),
            Button("Leave it", "approval", {"action": action.id, "decision": "decline"}),
        ]
    return [
        Button("Go ahead", "approval", {"action": action.id, "decision": "approve"}),
        Button("Not now", "approval", {"action": action.id, "decision": "snooze"}),
        *([Button("Not ever", "approval", {"action": action.id, "decision": NEVER})]
          if not_ever else []),
    ]  # fmt: skip


def shown_name(name: str) -> str:
    """A sender's name as the card shows it: one line, not too long (it's the email's text,
    shown as data and never read as anything else)."""
    flat = " ".join(name.split())
    return flat if len(flat) <= MAX_NAME else flat[: MAX_NAME - 1].rstrip() + "…"


class ApprovalsUI:
    def __init__(self, autonomy: Autonomy, outbox: Outbox, *, ttl: timedelta = APPROVAL_TTL):
        self.autonomy = autonomy
        self.outbox = outbox
        self.store = autonomy.store
        self.db = autonomy.db
        self.ttl = ttl
        self.held: set[str] = set()  # categories asked about elsewhere, together
        # 35a: categories whose card is about right now (dinner tonight): it goes at once,
        # not at a good moment, though a pause, quiet hours and busy times still hold it.
        self.timely: set[str] = set()
        self.services: Services | None = None
        self.groups = ApprovalGroups(self)
        self.not_ever: dict[str, NotEver] = {}  # F37c: by category, from the modules

    def install(self, services: Services) -> None:
        """Wire approvals into the agent: listeners, buttons, reactions, fast path, /pending."""
        self.services = services
        self.groups.install()
        self.autonomy.pending_listeners.append(self.on_pending)
        self.autonomy.withdrawn_listeners.append(self.on_withdrawn)
        services.button_handlers["approval"] = self.on_button
        services.button_handlers[NOT_EVER_KIND] = self.on_not_ever
        services.reaction_handlers.append(self.on_reaction)
        services.awaiting_sources.append(self.awaiting_items)
        services.add_command("/pending", self.on_pending_command, "See what's waiting on you")

    # ----- asking ---------------------------------------------------------------

    async def on_pending(self, action: Action, interactive: bool) -> None:
        if action.category in self.held:
            return
        if not interactive and await self.groups.take(action, Priority.NORMAL):
            return  # F26b: in its email's message
        await self.ask(action, priority=Priority.REPLY if interactive else Priority.NORMAL)

    async def ask(self, action: Action, *, priority: Priority) -> None:
        member = self.store.get_member(action.member_id)
        template = RETRY_TEXT if action.status == "failed" else ASK_TEXT
        result = await self.outbox.send(
            member,
            template.format(summary=action.summary),
            priority=priority,
            buttons=self.buttons(action),
            kind="approval",
            # the daily limit doesn't hold it to tomorrow; a timely one goes now
            deadline=clock.now()
            + (timedelta(0) if action.category in self.timely else CARD_WITHIN),
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
        await self.groups.follow(outcome.action, Decision(decision))
        await self._show_result(outcome.action, outcome.message)
        return outcome.message

    async def on_withdrawn(self, action: Action, reason: str) -> None:
        await self._edit_cards(action, f"{action.summary}\n{reason}")
        await self.groups.changed(action, reason)

    async def _show_result(self, action: Action, message: str) -> None:
        await self.groups.changed(action)  # its email's message, if it's in one (F26b)
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
            self.db.execute(  # F38c: how the card ended, for `themi feedback`
                "UPDATE outbox SET card_outcome = COALESCE(card_outcome, ?) WHERE id = ?",
                (action.status, row["outbox_id"]),
            )
            if message_id is None:
                self.outbox.cancel(row["outbox_id"])  # never went out: no need now
            else:
                await self.outbox.edit(member, message_id, text)
            self.db.execute("DELETE FROM approval_messages WHERE id = ?", (row["id"],))

    def buttons(self, action: Action) -> list[Button]:
        return buttons_for(action, not_ever=action.category in self.not_ever)

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        action_id = int(event.button.payload["action"])
        if event.button.payload["decision"] == NEVER:
            await self._not_ever(action_id, event)
            return
        decision = Decision(event.button.payload["decision"])
        reply = await self.resolve(action_id, decision, event.member)
        if reply == ALREADY_TEXT or reply.startswith("That one isn't"):
            await self.outbox.send(event.member, reply, priority=Priority.REPLY)

    # ----- not ever (F37c) ----------------------------------------------------------

    async def _not_ever(self, action_id: int, event: InboundEvent) -> None:
        reply = await self.resolve(action_id, Decision.DECLINE, event.member)
        if reply == ALREADY_TEXT or reply.startswith("That one isn't"):
            await self.outbox.send(event.member, reply, priority=Priority.REPLY)
            return
        if event.message_id is not None:
            await self.ask_about_sender(event.member, event.message_id, action_id)

    async def ask_about_sender(
        self, member: Member, message_id: int, action_id: int, group_id: int = 0
    ) -> None:
        """The card, declined for good, asks once whether to skip the sender's offers."""
        action = self.autonomy.action(action_id)
        head = self.groups.final(group_id) if group_id else action.summary
        spec = self.not_ever.get(action.category)
        sender = spec.sender(action) if spec else None
        if spec is None or sender is None:
            await self.outbox.edit(member, message_id, FOR_GOOD_TEXT.format(head=head))
            return
        tap = {"action": action_id, "group": group_id}
        await self.outbox.edit(
            member,
            message_id,
            NOT_EVER_ASK.format(head=head, words=spec.words, name=shown_name(sender[1])),
            [
                Button("Yes, skip them", NOT_EVER_KIND, {**tap, "answer": "skip"}),
                Button("Just this one", NOT_EVER_KIND, {**tap, "answer": "one"}),
            ],
        )

    async def on_not_ever(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        action = self.autonomy.action(int(payload["action"]))
        if action.member_id != event.member.id:
            await self.outbox.send(
                event.member, "That one isn't yours to answer.", priority=Priority.REPLY
            )
            return
        group_id = int(payload.get("group") or 0)
        head = self.groups.final(group_id) if group_id else action.summary
        spec = self.not_ever.get(action.category)
        sender = spec.sender(action) if spec else None
        if payload["answer"] == "skip" and spec is not None and sender is not None:
            spec.skip(event.member, sender[0], action.category)
            text = SKIPPED_TEXT.format(head=head, words=spec.words, name=shown_name(sender[1]))
        else:
            text = FOR_GOOD_TEXT.format(head=head)
        if event.message_id is not None:
            await self.outbox.edit(event.member, event.message_id, text)

    async def on_reaction(self, event: InboundEvent) -> None:
        assert event.reaction is not None
        emoji = set(event.reaction.added)
        if emoji & APPROVE_REACTIONS:
            decision = Decision.APPROVE
        elif emoji & SNOOZE_REACTIONS:
            decision = Decision.SNOOZE
        elif DECLINE_REACTION in emoji:
            # F38c: a 👎 on a card says the card is wrong, so it doesn't stay open: a "no".
            decision = Decision.DECLINE
        else:
            return
        message_id = event.reaction.message_id
        if await self.groups.on_reaction(event.member, message_id, decision):
            self._declined_by_reaction(event.member.id, message_id, decision)
            return
        action_id = self._action_for_message(event.member.id, message_id)
        if action_id is not None:
            await self.resolve(action_id, decision, event.member)
            self._declined_by_reaction(event.member.id, message_id, decision)

    def _declined_by_reaction(self, member_id: int, message_id: int, decision: Decision) -> None:
        if decision is Decision.DECLINE:
            self.db.execute(
                "UPDATE outbox SET card_outcome = ? WHERE member_id = ? "
                "AND telegram_message_id = ?",
                (DECLINED_BY_REACTION, member_id, message_id),
            )

    def _action_for_message(self, member_id: int, message_id: int) -> int | None:
        row = self.db.one(
            "SELECT m.action_id FROM approval_messages m JOIN outbox o ON o.id = m.outbox_id "
            "WHERE m.member_id = ? AND o.telegram_message_id = ? ORDER BY m.id DESC LIMIT 1",
            (member_id, message_id),
        )
        return row["action_id"] if row else None

    def chat_resolver(
        self, action_id: int, member: Member
    ) -> Callable[[ChatDecision], Awaitable[str]]:
        async def resolve(decision: ChatDecision) -> str:
            return await self.resolve(action_id, _CHAT_DECISIONS[decision], member)

        return resolve

    def awaiting_items(self, member: Member) -> list[AwaitingItem]:
        grouped, covered = self.groups.awaiting(member)
        return grouped + [
            AwaitingItem(
                f"action:{a.id}",
                a.summary,
                self.chat_resolver(a.id, member),
                self._asked_in(a.id, member.id),
            )
            for a in self.autonomy.awaiting(member)
            if a.category not in self.held and a.id not in covered
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
                buttons=self.buttons(action),
                kind="approval",
            )
            if result.outbox_id is not None:
                self._remember_message(action.id, member.id, result.outbox_id)

    # ----- housekeeping (scheduler) -------------------------------------------------

    async def resurface(self) -> int:
        """Snoozed actions whose time has come are asked about again (held ones wait for
        their own message)."""
        actions = self.autonomy.resurface_snoozed()
        for action in actions:
            if action.category not in self.held and not await self.groups.take(
                action, Priority.NORMAL
            ):
                await self.ask(action, priority=Priority.NORMAL)
        return len(actions)

    async def expire(self) -> int:
        actions = self.autonomy.expire_stale(self.ttl)
        for action in actions:
            await self._show_result(action, "")
        return len(actions)
