"""The email audit (E2, Erin's idea #50): one task instead of single questions.

Senders that might always count as urgent (E1's suggestions) and emails triage wasn't sure
about wait in `email_audit_items`, not in messages of their own. While any are waiting, the
person has one task, "Email audit (5 to look at)", nudged like any other (one at a time, in
T1's order), with [Start] and [Later]. It's Themi's own, so never on the wall (E2b).
Started, it goes one at a time: the sender or the email in a line, then two questions on
sliding scales (E2b, Erin's idea #44), in words: how urgent (not urgent, same day, right
away), then how important (not important, somewhat, very), with [Stop for now] on each. At
the end, a short count ("All 5 sorted: 2 time-sensitive, 1 important.") and the task is
done. People read "time-sensitive" for the middle level and "urgent" only for right away
(Erin's idea #60); the stored answers keep their names.

What the answers do:
- a sender: urgent, its mail always counts as urgent (E1's urgent senders), and right away,
  its alerts always come at once; important, its mail is never offered for archiving as
  noise, and very, it's never marked as read for them either; neither, it isn't asked
  about again.
- an email: it's filed as urgent (urgent at all), kept (important), or left as it was.

Emails and the senders' names are shown to the person as they are; none of it reaches the
model.
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import LinkedAccount, Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from datetime import datetime

    from themi.core.services import Services
    from themi.core.tasks import Task, TaskBoard

log = logging.getLogger(__name__)

TITLE = "Email audit ({n} to look at)"
NUDGE_TEXT = "Email audit: {n} to look at, one at a time. Start now, or later?"
SENDER_TEXT = "{i} of {n}. Mail from {label} ({address}), {reason}."
EMAIL_TEXT = "{i} of {n}. An email from {label}: {subject}\n{summary}"
HOW_URGENT = "How soon does it need you?"
HOW_IMPORTANT = "How important is it?"
# 0, 1, 2; only ever shown in words. "Urgent" is kept for right away (Erin's idea #60).
URGENCY = ("No rush", "Time-sensitive", "Urgent")
IMPORTANCE = ("Not important", "Somewhat", "Very")
URGENCY_WORDS = ("no rush", "time-sensitive", "urgent")
IMPORTANCE_WORDS = ("not important", "somewhat important", "very important")
ANSWERED_TEXT = "{label}: {urgency}, {importance}."
DONE_TEXT = "All {n} sorted: {counts}. That's the email audit done."
STOPPED_TEXT = "Stopped for now; {n} still to look at. The audit comes back later."
NOTHING_TEXT = "There's nothing waiting for an email audit."
ANSWERS = ("urgent", "important", "both", "neither")
ANSWER_WORDS = {
    "urgent": "time-sensitive",
    "important": "important",
    "both": "time-sensitive and important",
    "neither": "neither",
}


class EmailAudit:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.email_audit = self
        s.button_handlers["email_audit"] = self.on_button
        s.tools.register(start_email_audit)
        s.tools.register(set_sender_levels)
        self.board.own_nudges.append(self._nudge)

    # ----- filling it -----------------------------------------------------------------

    def add_sender(
        self, account: LinkedAccount, address: str, label: str, reason: str, suggestion: int
    ) -> None:
        self.db.execute(
            "INSERT INTO email_audit_items (member_id, account_id, address, label, reason, "
            "suggestion_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (account.member_id, account.id, address.lower(), label, reason, suggestion, _now()),
        )

    async def set_levels(
        self, account: LinkedAccount, address: str, label: str, urgency: int, importance: int
    ) -> None:
        """A sender's two levels, said in chat (#59): as if answered in the audit. Time-
        sensitive or urgent puts it among the inbox's always time-sensitive senders; no rush
        takes it off (an address listed as it is, not a whole domain)."""
        address = address.lower()
        self.db.execute(
            "INSERT INTO email_audit_items (member_id, account_id, address, label, reason, "
            "created_at, urgency, importance, answer, answered_at) "
            "VALUES (?, ?, ?, ?, 'said in chat', ?, ?, ?, ?, ?) "
            "ON CONFLICT (account_id, address) WHERE email_id IS NULL DO UPDATE SET "
            "urgency = excluded.urgency, importance = excluded.importance, "
            "answer = excluded.answer, answered_at = excluded.answered_at",
            (
                account.member_id,
                account.id,
                address,
                label,
                _now(),
                urgency,
                importance,
                _quadrant(urgency, importance),
                _now(),
            ),
        )
        member = self.store.get_member(account.member_id)
        listed = [p for p in account.urgent_senders if p.lower() != address]
        if urgency:
            listed.append(address)
        if listed != list(account.urgent_senders):
            self.store.update_linked_account(member, account.id, urgent_senders=listed)
        await self.refresh(member)

    def add_email(self, account: LinkedAccount, row: dict[str, Any], summary: str) -> None:
        self.db.execute(
            "INSERT INTO email_audit_items (member_id, account_id, email_id, address, label, "
            "reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (
                account.member_id,
                account.id,
                row["id"],
                str(row["from_address"]).lower(),
                row["from_name"] or row["from_address"],
                summary,
                _now(),
            ),
        )

    async def refresh(self, member: Member) -> None:
        """Keep their audit task in step with what's waiting: made, retitled, or done."""
        waiting = len(self.waiting(member))
        audit = self.db.one("SELECT * FROM email_audits WHERE member_id = ?", (member.id,))
        task = self._open_task(audit)
        if waiting == 0:
            if task is not None:
                await self.board.complete(task.id, member)
            return
        title = TITLE.format(n=waiting)
        if task is None:
            task = await self.board.create(
                member,
                title,
                "text",
                1,
                assignee=member,
                importance="normal",
                nudge=False,
                off_wall=True,
            )
            self.db.execute(
                "INSERT INTO email_audits (member_id, task_id) VALUES (?, ?) "
                "ON CONFLICT (member_id) DO UPDATE SET task_id = excluded.task_id, "
                "started_at = NULL",
                (member.id, task.id),
            )
            await self.board.prompt(task)  # now it's known as the audit: its own nudge
        elif task.title != title:
            await self.board.update(task.id, member, title=title)

    def waiting(self, member: Member) -> list[dict[str, Any]]:
        return self.db.query(  # a sender added from an older message's button is settled
            "SELECT * FROM email_audit_items WHERE member_id = ? AND answer IS NULL "
            "AND (suggestion_id IS NULL OR suggestion_id NOT IN "
            "(SELECT id FROM sender_suggestions WHERE added_at IS NOT NULL)) ORDER BY id",
            (member.id,),
        )

    def sender_levels(self, account_id: int, address: str) -> tuple[int, int]:
        """How urgent and how important they said this sender's mail is (0 if not asked)."""
        row = self.db.one(
            "SELECT urgency, importance FROM email_audit_items WHERE account_id = ? "
            "AND address = ? AND email_id IS NULL AND answer IS NOT NULL",
            (account_id, address.lower()),
        )
        return (row["urgency"] or 0, row["importance"] or 0) if row else (0, 0)

    def _open_task(self, audit: dict[str, Any] | None) -> Task | None:
        if audit is None:
            return None
        task = self.board.get(audit["task_id"])
        return task if task.status in ("open", "snoozed") else None

    # ----- the nudge, and going through it ------------------------------------------------

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        audit = self.db.one("SELECT * FROM email_audits WHERE task_id = ?", (task.id,))
        if audit is None:
            return False
        waiting = len(self.waiting(member))
        if waiting == 0:
            return True  # nothing to ask about; refresh() closes it
        result = await self.services.outbox.send(
            member,
            NUDGE_TEXT.format(n=waiting),
            priority=Priority.NORMAL,
            kind="task",
            buttons=[
                Button("Start", "email_audit", {"action": "start"}),
                Button("Later", "task", {"task": task.id, "action": "later"}),
            ],
            not_before=not_before,
            deadline=deadline,
            dedupe_key=f"task-{task.id}-{secrets.token_hex(4)}",  # one of the task's nudges
        )
        if result.outbox_id is not None:
            self.db.execute(
                "UPDATE tasks SET prompt_outbox_id = ? WHERE id = ?", (result.outbox_id, task.id)
            )
        return True

    async def start(self, member: Member) -> bool:
        """Ask about the first one waiting. False if there's nothing."""
        self.db.execute(
            "UPDATE email_audits SET started_at = ? WHERE member_id = ?", (_now(), member.id)
        )
        return await self._ask_next(member)

    async def _ask_next(self, member: Member) -> bool:
        waiting = self.waiting(member)
        if not waiting:
            return False
        item = waiting[0]
        total = self._in_this_audit(member)
        done = total - len(waiting)
        text, buttons = self._question(item, done + 1, total)
        await self.services.outbox.send(
            member,
            text,
            priority=Priority.REPLY,  # they're going through it now
            kind="email_audit",
            buttons=buttons,
        )
        return True

    def _question(self, item: dict[str, Any], i: int, n: int) -> tuple[str, list[Button]]:
        """How urgent, or (that answered) how important, with its buttons."""
        about = self._about(item, i, n)
        if item["urgency"] is None:
            scale, labels, question = "urgency", URGENCY, HOW_URGENT
        else:
            scale, labels, question = "importance", IMPORTANCE, HOW_IMPORTANT
        buttons = [
            Button(label, "email_audit", {"action": scale, "item": item["id"], "level": level})
            for level, label in enumerate(labels)
        ]
        buttons.append(Button("Stop for now", "email_audit", {"action": "stop"}))
        return f"{about}\n{question}", buttons

    def _about(self, item: dict[str, Any], i: int, n: int) -> str:
        if item["email_id"] is None:
            return SENDER_TEXT.format(
                i=i, n=n, label=item["label"], address=item["address"], reason=item["reason"]
            )
        email = self.db.one("SELECT subject FROM emails WHERE id = ?", (item["email_id"],))
        subject = (email["subject"] if email else "") or "(no subject)"
        return EMAIL_TEXT.format(
            i=i, n=n, label=item["label"], subject=subject, summary=item["reason"]
        )

    def _in_this_audit(self, member: Member) -> int:
        """Answered since this audit started, plus those still waiting."""
        audit = self.db.one("SELECT started_at FROM email_audits WHERE member_id = ?", (member.id,))
        since = audit["started_at"] if audit and audit["started_at"] else _now()
        return self.db.scalar(
            "SELECT COUNT(*) FROM email_audit_items WHERE member_id = ? "
            "AND (answer IS NULL OR answered_at >= ?)",
            (member.id, since),
        )

    def _item(self, member: Member, item_id: int) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM email_audit_items WHERE id = ? AND member_id = ?", (item_id, member.id)
        )

    def set_urgency(self, member: Member, item_id: int, level: int) -> dict[str, Any] | None:
        """The first question's answer. Returns the item, to ask the second."""
        item = self._item(member, item_id)
        if item is None or item["answer"] is not None or level not in range(len(URGENCY)):
            return None
        self.db.execute("UPDATE email_audit_items SET urgency = ? WHERE id = ?", (level, item_id))
        return self._item(member, item_id)

    def set_importance(self, member: Member, item_id: int, level: int) -> str | None:
        """The second answer: the item is done and acted on. Returns the line the question
        becomes."""
        item = self._item(member, item_id)
        if item is None or item["urgency"] is None or level not in range(len(IMPORTANCE)):
            return None
        if item["answer"] is None:
            answer = _quadrant(item["urgency"], level)
            self.db.execute(
                "UPDATE email_audit_items SET importance = ?, answer = ?, answered_at = ? "
                "WHERE id = ?",
                (level, answer, _now(), item_id),
            )
            self._apply(member, item, answer)
        else:
            level = item["importance"]
        return ANSWERED_TEXT.format(
            label=item["label"],
            urgency=URGENCY_WORDS[item["urgency"]],
            importance=IMPORTANCE_WORDS[level],
        )

    def _apply(self, member: Member, item: dict[str, Any], answer: str) -> None:
        urgent = answer in ("urgent", "both")
        if item["email_id"] is None:
            if urgent and item["suggestion_id"] and self.services.senders is not None:
                self.services.senders.add(member, item["suggestion_id"])
            return
        if urgent:
            self.db.execute(
                "UPDATE emails SET category = 'urgent' WHERE id = ?", (item["email_id"],)
            )
        elif answer == "important":
            self.db.execute(
                "UPDATE emails SET category = 'routine' WHERE id = ? AND category = 'noise'",
                (item["email_id"],),
            )

    async def _finish(self, member: Member) -> None:
        audit = self.db.one("SELECT * FROM email_audits WHERE member_id = ?", (member.id,))
        since = audit["started_at"] if audit and audit["started_at"] else _now()
        rows = self.db.query(
            "SELECT answer, COUNT(*) AS n FROM email_audit_items WHERE member_id = ? "
            "AND answered_at >= ? GROUP BY answer",
            (member.id, since),
        )
        counts = {r["answer"]: r["n"] for r in rows}
        total = sum(counts.values())
        words = ", ".join(f"{counts[a]} {ANSWER_WORDS[a]}" for a in ANSWERS if counts.get(a))
        task = self._open_task(audit)
        if task is not None:
            await self.board.complete(task.id, member)
        await self.services.outbox.send(
            member, DONE_TEXT.format(n=total, counts=words), priority=Priority.REPLY
        )

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        member = event.member
        action = event.button.payload.get("action")
        message_id = event.button.message_id
        if action == "start":
            if message_id is not None:
                await self.services.outbox.edit(member, message_id, "Email audit: started.")
            if not await self.start(member):
                await self.services.outbox.send(member, NOTHING_TEXT, priority=Priority.REPLY)
            return
        if action == "stop":
            left = len(self.waiting(member))
            if message_id is not None:
                await self.services.outbox.edit(member, message_id, STOPPED_TEXT.format(n=left))
            task = self._open_task(
                self.db.one("SELECT * FROM email_audits WHERE member_id = ?", (member.id,))
            )
            if task is not None:
                self.board.snooze(task.id)
            return
        if action not in ("urgency", "importance"):
            return
        item_id, level = int(event.button.payload["item"]), int(event.button.payload["level"])
        if action == "urgency":
            item = self.set_urgency(member, item_id, level)
            if item is not None and message_id is not None:
                total = self._in_this_audit(member)
                done = total - len(self.waiting(member))
                text, buttons = self._question(item, done + 1, total)
                await self.services.outbox.edit(member, message_id, text, buttons)
            return
        line = self.set_importance(member, item_id, level)
        if line is None:
            return
        if message_id is not None:
            await self.services.outbox.edit(member, message_id, line)
        if not await self._ask_next(member):
            await self._finish(member)
        else:
            await self.refresh(member)  # the task's title keeps the count


def _now() -> str:
    return to_utc_iso(clock.now())


def _quadrant(urgency: int, importance: int) -> str:
    if urgency and importance:
        return "both"
    return "urgent" if urgency else "important" if importance else "neither"


@tool(
    "start_email_audit",
    "Go through the emails and senders Themi wasn't sure about, one at a time, when they "
    "ask ('let's do the email audit', 'which emails did I need to look at?'). Each one comes "
    "with buttons: how soon it needs them, then how important.",
    {},
)
async def start_email_audit(ctx: ToolContext, args: dict[str, Any]) -> str:
    audit = ctx.services.email_audit
    if audit is None:
        raise ToolFailed("Email isn't set up.")
    if not await audit.start(ctx.member):
        raise ToolDeclined(NOTHING_TEXT)
    return "The first one is on its way to them, with buttons. Say nothing more about it."


# What the levels do, said plainly when anyone asks (#59: "highlighted" and "the top of your
# inbox" were made up). Themi never reorders, highlights or labels anything in Gmail.
LEVELS_TEXT = (
    "What the levels do: urgent mail gets a message at once, even in quiet hours. "
    "Time-sensitive mail gets a message when it arrives, within quiet hours and the daily "
    "limit. No rush: no message. Somewhat important mail is never offered for archiving; "
    "very important mail is also never marked as read. Nothing is moved, highlighted or "
    "reordered in the inbox."
)
URGENCY_KEYS = ("no_rush", "time_sensitive", "urgent")
IMPORTANCE_KEYS = ("not", "somewhat", "very")


@tool(
    "set_sender_levels",
    "How soon a sender's mail needs this person, and how much it matters, when they say so "
    "('set Stanford emails to medium urgency and medium importance', 'SoFi can wait'). "
    "urgency: no_rush (no message); time_sensitive (a message when it comes, within quiet "
    "hours and the daily limit: 'medium', 'within a day or two'); urgent (a message at once, "
    "even in quiet hours: only for 'drop everything'). importance: not; somewhat (never "
    "offered for archiving: 'medium'); very (also never marked as read). sender: words from "
    "the sender's name or address, as they said them. The result says what the levels do: "
    "use it to explain them, in full sentences.",
    {
        "sender": {"type": "string"},
        "urgency": {"type": "string", "enum": list(URGENCY_KEYS)},
        "importance": {"type": "string", "enum": list(IMPORTANCE_KEYS)},
    },
)
async def set_sender_levels(ctx: ToolContext, args: dict[str, Any]) -> str:
    from themi.core.triage import find_email

    audit = ctx.services.email_audit
    if audit is None:
        raise ToolFailed("Email isn't set up.")
    row = find_email(ctx, str(args["sender"]))
    if row is None:
        raise ToolFailed(
            f"No email from the last month in their linked inboxes is from {args['sender']!r}."
        )
    account = ctx.services.store.get_linked_account(row["account_id"])
    urgency = URGENCY_KEYS.index(args["urgency"])
    importance = IMPORTANCE_KEYS.index(args["importance"])
    label = row["from_name"] or row["from_address"]
    await audit.set_levels(account, row["from_address"], label, urgency, importance)
    return (
        f"Set: mail from {label} ({str(row['from_address']).lower()}) is "
        f"{URGENCY_WORDS[urgency]} and {IMPORTANCE_WORDS[importance]}, in {account.address}. "
        + LEVELS_TEXT
    )
