"""Approvals from one email thread in one message (F26b, Erin's idea #137).

Five cards came at once from one client's emails: a reply to send, two invitations for the
calendar and two "mark as read"s. Now approvals that triage stages from the same thread,
or from the same sender within `SENDER_WINDOW`, share one message:

    4 things from Jennifer Noble's emails:
    - A reply to ... about ...
    - Tutoring, Mon 16 Nov, 4-5 pm, for your calendar
    - ...
    Go ahead with all of them, one by one, or not now?

with [Go ahead with all] [One by one] [Not now]. One by one sends today's single cards.
Not now snoozes them all; they come back together.

- A "mark as read" for an email whose event is also being added isn't a line of its own:
  it follows that event (done when the event is done, left or snoozed with it).
- A group with one line looks and answers like a single card.
- A later email in the thread joins the waiting message, which is edited to add its line.
  An email triage rated urgent, or from a sender they said is important (E2b), gets a
  message of its own instead (Erin, 2026-11-05).
- The message is an approval like any other: quiet hours and the daily limit hold it, and
  while it waits it's rebuilt as things stand when it goes.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.accounts.store import SYSTEM
from themi.autonomy import Action, Decision, InvalidTransition
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.approvals import ApprovalsUI
    from themi.core.services import AwaitingItem

log = logging.getLogger(__name__)

# Staged by triage from an email: these group. (Asked for in chat, like a forward, they don't.)
GROUPED = frozenset({"email_mark_read", "email_reply", "calendar_from_email"})
MARK_READ, FROM_EMAIL = "email_mark_read", "calendar_from_email"
SENDER_WINDOW = timedelta(minutes=10)  # the same sender, another thread: this close together
OPEN = ("pending", "failed")  # still to answer, in the message
FROM_SENDER = re.compile(r" \(from ([^()]*)\)$")

HEADER_TEXT = "{count} things from {name}'s emails:"
ASK_ALL_TEXT = "Go ahead with all of them, one by one, or not now?"
ONE_BY_ONE_TEXT = "One at a time, below."
CHAT_ANSWERS = {"yes": "all", "no": "no", "later": "later"}  # a bare yes, no or later
LATER_TEXT = "No rush, these will come back later."
STATUS_WORDS = {
    "done": "done",
    "declined": "left as is",
    "snoozed": "later",
    "failed": "didn't go through",
    "expired": "lapsed",
}


def email_of(action: Action) -> int | None:
    """The email an approval came from, if triage staged it from one."""
    if action.category not in GROUPED:
        return None
    if action.category == FROM_EMAIL:
        source = str(action.payload.get("source") or "")
        return int(source[6:]) if source.startswith("email:") and source[6:].isdigit() else None
    email_id = action.payload.get("email_id")
    return int(email_id) if email_id is not None else None


class ApprovalGroups:
    def __init__(self, ui: ApprovalsUI) -> None:
        self.ui = ui
        self.autonomy = ui.autonomy
        self.outbox = ui.outbox
        self.store = ui.store
        self.db = ui.db
        self._holding: set[int] = set()  # groups being answered all at once: shown at the end

    def install(self) -> None:
        services = self.ui.services
        assert services is not None
        services.button_handlers["approval_group"] = self.on_button
        self.outbox.refreshers["approval"] = self.as_it_stands

    # ----- taking an approval in --------------------------------------------------------

    async def take(self, action: Action, priority: Priority) -> bool:
        """Ask about this approval in its email's message. False: not one of these."""
        email_id = email_of(action)
        if email_id is None:
            return False
        email = self.db.one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if email is None:
            return False
        alone = self._alone(email)
        sender = str(email["from_address"]).lower()
        group = self.db.one(
            "SELECT * FROM approval_groups WHERE member_id = ? AND closed_at IS NULL AND ("
            "(? AND alone_email = ?) OR (NOT ? AND alone_email IS NULL AND "
            "(thread_id = ? OR (sender = ? AND last_at >= ?)))) ORDER BY id DESC LIMIT 1",
            (
                action.member_id,
                int(alone), email_id, int(alone),
                email["thread_id"], sender, to_utc_iso(clock.now() - SENDER_WINDOW),
            ),
        )  # fmt: skip
        if group is None:
            group_id = self.db.execute(
                "INSERT INTO approval_groups (member_id, thread_id, sender, sender_name, "
                "alone_email, created_at, last_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    action.member_id,
                    email["thread_id"],
                    sender,
                    email["from_name"] or email["from_address"],
                    email_id if alone else None,
                    to_utc_iso(clock.now()),
                    to_utc_iso(clock.now()),
                ),
            )
        else:
            group_id = group["id"]
            self.db.execute(
                "UPDATE approval_groups SET last_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), group_id),
            )
        self.db.execute(
            "INSERT OR IGNORE INTO approval_group_items (group_id, action_id, email_id) "
            "VALUES (?, ?, ?)",
            (group_id, action.id, email_id),
        )
        await self.show(group_id, priority=priority)
        return True

    def _alone(self, email: dict[str, Any]) -> bool:
        """Triage rated it urgent, or its sender is one they said is important (E2b)."""
        if email["category"] == "urgent":
            return True
        audit = self.ui.services.maybe(keys.email_audit) if self.ui.services else None
        if audit is None:
            return False
        return audit.sender_levels(email["account_id"], email["from_address"])[1] > 0

    # ----- what the message says --------------------------------------------------------

    def _group(self, group_id: int) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM approval_groups WHERE id = ?", (group_id,))

    def _items(self, group_id: int) -> list[tuple[Action, int]]:
        rows = self.db.query(
            "SELECT action_id, email_id FROM approval_group_items WHERE group_id = ? "
            "ORDER BY action_id",
            (group_id,),
        )
        return [(self.autonomy.action(r["action_id"]), r["email_id"]) for r in rows]

    def lines(self, group_id: int) -> list[Action]:
        """The approvals with a line of their own: not a "mark as read" riding on its event."""
        items = self._items(group_id)
        events = {email for action, email in items if action.category == FROM_EMAIL}
        return [a for a, email in items if not (a.category == MARK_READ and email in events)]

    def riders(self, action: Action) -> list[Action]:
        """The "mark as read"s that go with this event (from its email, in its group)."""
        if action.category != FROM_EMAIL:
            return []
        rows = self.db.query(
            "SELECT o.action_id FROM approval_group_items i JOIN approval_group_items o "
            "ON o.group_id = i.group_id AND o.email_id = i.email_id AND o.action_id != i.action_id "
            "JOIN pending_actions a ON a.id = o.action_id "
            "WHERE i.action_id = ? AND a.category = ?",
            (action.id, MARK_READ),
        )
        return [self.autonomy.action(r["action_id"]) for r in rows]

    def render(self, group_id: int) -> tuple[str, list[Button]] | None:
        """The message as things stand, or None when nothing in it is waiting any more
        (its text then is the last one shown: see `final`)."""
        from themi.core.approvals import ASK_TEXT, RETRY_TEXT

        group = self._group(group_id)
        lines = self.lines(group_id) if group else []
        if not lines:
            return None
        if len(lines) == 1:
            (action,) = lines
            if action.status not in OPEN:
                return None
            template = RETRY_TEXT if action.status == "failed" else ASK_TEXT
            return template.format(summary=action.summary), self.ui.buttons(action)
        if not any(a.status in OPEN for a in lines):
            return None
        assert group is not None
        return f"{self._listing(group, lines)}\n{ASK_ALL_TEXT}", [
            Button("Go ahead with all", "approval_group", {"group": group_id, "answer": "all"}),
            Button("One by one", "approval_group", {"group": group_id, "answer": "each"}),
            Button("Not now", "approval_group", {"group": group_id, "answer": "later"}),
            *(  # F37c: for all of it
                [Button("Not ever", "approval_group", {"group": group_id, "answer": "never"})]
                if self._not_ever_line(lines) is not None
                else []
            ),
        ]

    def _not_ever_line(self, lines: list[Action]) -> Action | None:
        """The first line still waiting whose kind can be turned down for good (F37c)."""
        return next((a for a in lines if a.status in OPEN and a.category in self.ui.not_ever), None)

    def final(self, group_id: int, footer: str = "") -> str:
        """The message once nothing in it waits: each line with what became of it."""
        from themi.core.approvals import RESULT_TEXT

        group = self._group(group_id)
        lines = self.lines(group_id)
        assert group is not None
        if len(lines) == 1 and not footer:
            (action,) = lines
            if note := self._note(action.id):
                return f"{action.summary}\n{note}"
            template = RESULT_TEXT.get(action.status, "{summary}")
            message = action.result or f"Done: {action.summary}"
            return template.format(summary=action.summary, message=message)
        listing = self._listing(group, lines, with_status=not footer)
        return f"{listing}\n{footer}" if footer else listing

    def _listing(self, group: dict[str, Any], lines: list[Action], with_status: bool = True) -> str:
        said = [HEADER_TEXT.format(count=len(lines), name=group["sender_name"])]
        for action in lines:
            status = STATUS_WORDS.get(action.status) if with_status else None
            if with_status and (note := self._note(action.id)):
                status = note.rstrip(".")
            first, *rest = _line(action, group).split("\n")  # a reply's draft follows its line
            said.append("\n".join([f"- {first}" + (f" ({status})" if status else ""), *rest]))
        return "\n".join(said)

    def _note(self, action_id: int) -> str | None:
        return self.db.scalar(
            "SELECT note FROM approval_group_items WHERE action_id = ? AND note IS NOT NULL",
            (action_id,),
        )

    # ----- showing it -------------------------------------------------------------------

    async def show(self, group_id: int, *, priority: Priority = Priority.NORMAL) -> None:
        """Send the message, or edit it to match. Closes the group once nothing waits."""
        from themi.core.approvals import CARD_WITHIN

        group = self._group(group_id)
        if group is None or group["closed_at"] or group_id in self._holding:
            return
        member = self.store.get_member(group["member_id"])
        fresh = self.render(group_id)
        if fresh is None:
            self._close(group_id)
            text, buttons = self.final(group_id), []
        else:
            text, buttons = fresh
        shown = json.dumps([text, [b.label for b in buttons]])
        if shown == group["shown"]:
            return
        outbox_id = group["outbox_id"]
        status = self.db.scalar("SELECT status FROM outbox WHERE id = ?", (outbox_id,))
        if status == "queued":  # its refresher has it right when it goes
            if fresh is None:
                self.outbox.cancel(outbox_id)
            self._shown(group_id, shown)
            return
        message_id = self.outbox.message_id(outbox_id) if outbox_id is not None else None
        if message_id is not None:
            await self.outbox.edit(member, message_id, text, buttons)
            self._shown(group_id, shown)
            return
        if fresh is None:
            return
        expiries = [a.expires_at for a in self.lines(group_id)]
        result = await self.outbox.send(
            member,
            text,
            priority=priority,
            buttons=buttons,
            kind="approval",
            deadline=clock.now() + CARD_WITHIN,
            expires=max(expiries) if expiries and None not in expiries else None,  # type: ignore[type-var]
        )
        self.db.execute(
            "UPDATE approval_groups SET outbox_id = ?, shown = ? WHERE id = ?",
            (result.outbox_id, shown, group_id),
        )

    def _shown(self, group_id: int, shown: str) -> None:
        self.db.execute("UPDATE approval_groups SET shown = ? WHERE id = ?", (shown, group_id))

    def _close(self, group_id: int) -> None:
        self.db.execute(
            "UPDATE approval_groups SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
            (to_utc_iso(clock.now()), group_id),
        )

    def as_it_stands(self, member: Member, row: dict[str, Any]) -> Any:
        """Outbox refresher for approvals: a group's message is rebuilt before it goes
        (an approval card of its own goes as written)."""
        group = self.db.one("SELECT id FROM approval_groups WHERE outbox_id = ?", (row["id"],))
        if group is None:
            return row["text"]
        fresh = self.render(group["id"])
        if fresh is None:
            self._close(group["id"])
        return fresh

    def open_group_of(self, action_id: int) -> int | None:
        row = self.db.one(
            "SELECT g.id FROM approval_group_items i JOIN approval_groups g ON g.id = i.group_id "
            "WHERE i.action_id = ? AND g.closed_at IS NULL ORDER BY g.id DESC LIMIT 1",
            (action_id,),
        )
        return row["id"] if row else None

    async def changed(self, action: Action, note: str | None = None) -> None:
        """An approval was answered, withdrawn (`note`: why) or lapsed: its message shows it."""
        if note:
            self.db.execute(
                "UPDATE approval_group_items SET note = ? WHERE action_id = ?", (note, action.id)
            )
        for row in self.db.query(
            "SELECT group_id FROM approval_group_items WHERE action_id = ?", (action.id,)
        ):
            await self.show(row["group_id"])

    # ----- answering --------------------------------------------------------------------

    async def follow(self, action: Action, decision: Decision) -> None:
        """Its "mark as read"s go with an event: done once it's done, or left or snoozed."""
        if decision is Decision.APPROVE and action.status != "done":
            return
        for rider in self.riders(action):
            try:
                await self.autonomy.resolve(rider.id, decision, by=SYSTEM)
            except InvalidTransition:
                continue

    async def on_button(self, event: InboundEvent) -> None:
        from themi.core.approvals import ALREADY_TEXT

        assert event.button is not None
        group_id = int(event.button.payload["group"])
        answer = str(event.button.payload["answer"])
        group = self._group(group_id)
        if group is None or group["closed_at"]:
            await self.outbox.send(event.member, ALREADY_TEXT, priority=Priority.REPLY)
            return
        if group["member_id"] != event.member.id:
            await self.outbox.send(
                event.member, "That one isn't yours to answer.", priority=Priority.REPLY
            )
            return
        await self.answer(group_id, answer, event.member)

    async def answer(self, group_id: int, answer: str, member: Member) -> str:
        """ "all", "each", "later" or "no", for every line still waiting. Returns a line."""
        decision = {"all": Decision.APPROVE, "later": Decision.SNOOZE, "no": Decision.DECLINE,
                    "never": Decision.DECLINE}  # fmt: skip
        waiting = [a for a in self.lines(group_id) if a.status in OPEN]
        asked_about = self._not_ever_line(waiting) if answer == "never" else None
        if answer == "each":
            group = self._group(group_id)
            assert group is not None
            self._close(group_id)
            await self._edit_to(group_id, self.final(group_id, ONE_BY_ONE_TEXT))
            for action in waiting:
                await self.ui.ask(action, priority=Priority.REPLY)
            return ONE_BY_ONE_TEXT
        chosen = decision[answer]
        self._holding.add(group_id)
        said: list[str] = []
        try:
            for action in waiting:
                if chosen is Decision.SNOOZE and action.status == "failed":
                    continue  # nothing to snooze: it's waiting to be tried again
                said.append(await self.ui.resolve(action.id, chosen, member))
        finally:
            self._holding.discard(group_id)
        if chosen is Decision.SNOOZE:
            self._close(group_id)
            await self._edit_to(group_id, self.final(group_id, LATER_TEXT))
            return LATER_TEXT
        await self.show(group_id)
        if asked_about is not None:  # F37c: then the sender question, on the same message
            group = self._group(group_id)
            assert group is not None
            outbox_id = group["outbox_id"]
            message_id = self.outbox.message_id(outbox_id) if outbox_id is not None else None
            if message_id is not None:
                await self.ui.ask_about_sender(member, message_id, asked_about.id, group_id)
        return " ".join(said)

    async def _edit_to(self, group_id: int, text: str) -> None:
        group = self._group(group_id)
        assert group is not None
        member = self.store.get_member(group["member_id"])
        outbox_id = group["outbox_id"]
        message_id = self.outbox.message_id(outbox_id) if outbox_id is not None else None
        if message_id is None:
            if outbox_id is not None:
                self.outbox.cancel(outbox_id)  # never went out: no need now
        else:
            await self.outbox.edit(member, message_id, text)
        self._shown(group_id, json.dumps([text, []]))

    def group_for_message(self, member_id: int, message_id: int) -> int | None:
        row = self.db.one(
            "SELECT g.id FROM approval_groups g JOIN outbox o ON o.id = g.outbox_id "
            "WHERE g.member_id = ? AND o.telegram_message_id = ? AND g.closed_at IS NULL",
            (member_id, message_id),
        )
        return row["id"] if row else None

    async def on_reaction(self, member: Member, message_id: int, decision: Decision) -> bool:
        """✅ or 💤 on a group's message answers what's in it. False: not a group's."""
        group_id = self.group_for_message(member.id, message_id)
        if group_id is None:
            return False
        lines = self.lines(group_id)
        if len(lines) == 1:
            await self.ui.resolve(lines[0].id, decision, member)
        else:
            await self.answer(group_id, "all" if decision is Decision.APPROVE else "later", member)
        return True

    # ----- a bare "yes" -----------------------------------------------------------------

    def awaiting(self, member: Member) -> tuple[list[AwaitingItem], set[int]]:
        """What a bare yes/no/later answers in their open groups, and which approvals
        those cover (so they aren't listed again one by one)."""
        from themi.core.services import AwaitingItem

        items: list[AwaitingItem] = []
        covered: set[int] = set()
        for group in self.db.query(
            "SELECT g.*, o.telegram_message_id AS message_id FROM approval_groups g "
            "LEFT JOIN outbox o ON o.id = g.outbox_id WHERE g.member_id = ? "
            "AND g.closed_at IS NULL ORDER BY g.id",
            (member.id,),
        ):
            covered |= {a.id for a, _ in self._items(group["id"])}
            asked = (group["message_id"],) if group["message_id"] else ()
            lines = [a for a in self.lines(group["id"]) if a.status == "pending"]
            if not lines:
                continue
            if len(self.lines(group["id"])) == 1:
                items.append(
                    AwaitingItem(
                        f"action:{lines[0].id}",
                        lines[0].summary,
                        self.ui.chat_resolver(lines[0].id, member),
                        asked,
                    )
                )
                continue
            items.append(
                AwaitingItem(
                    f"group:{group['id']}",
                    self._listing(group, self.lines(group["id"])),
                    self._chat_resolver(group["id"], member),
                    asked,
                )
            )
        return items, covered

    def _chat_resolver(self, group_id: int, member: Member) -> Callable[[str], Awaitable[str]]:
        async def resolve(decision: str) -> str:
            return await self.answer(group_id, CHAT_ANSWERS[decision], member)

        return resolve


def _line(action: Action, group: dict[str, Any]) -> str:
    """Its summary, without what the header already says (who it's from)."""
    text = action.summary
    named = FROM_SENDER.search(text.split("\n", 1)[0])
    if named and group["sender"] in named.group(1).lower():
        text = text[: named.start()] + text[named.end() :]
    if text.startswith("From an email: "):
        text = text[len("From an email: ") :]
        text = text[:1].upper() + text[1:]
    return text
