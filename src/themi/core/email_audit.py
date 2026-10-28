"""The email audit (E2, Erin's idea #50): one task instead of single questions.

Senders that might always count as urgent (E1's suggestions) and emails triage wasn't sure
about wait in `email_audit_items`, not in messages of their own. While any are waiting, the
person has one task, "Email audit (5 to look at)", nudged like any other (one at a time, in
T1's order), with [Start] and [Later]. Started, it goes one at a time: the sender or the
email in a line, with [Urgent] [Important] [Both] [Neither] and [Stop for now]. At the end,
a short count ("All 5 sorted: 2 urgent, 1 important.") and the task is done.

What an answer does:
- a sender: urgent or both, its mail always counts as urgent (E1's urgent senders);
  important or both, its mail is never offered for archiving as noise; neither, it isn't
  asked about again.
- an email: it's filed as urgent (urgent or both), kept (important), or left as it was.

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
SENDER_TEXT = (
    "{i} of {n}. Mail from {label} ({address}), {reason}.\nUrgent, important, both or neither?"
)
EMAIL_TEXT = (
    "{i} of {n}. An email from {label}: {subject}\n{summary}\nUrgent, important, both or neither?"
)
ANSWERED_TEXT = "{label}: {words}."
DONE_TEXT = "All {n} sorted: {counts}. That's the email audit done."
STOPPED_TEXT = "Stopped for now; {n} still to look at. The audit comes back later."
NOTHING_TEXT = "There's nothing waiting for an email audit."
ANSWERS = ("urgent", "important", "both", "neither")
ANSWER_WORDS = {
    "urgent": "urgent",
    "important": "important",
    "both": "urgent and important",
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
                member, title, "text", 1, assignee=member, importance="normal", nudge=False
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

    def important_sender(self, account_id: int, address: str) -> bool:
        """They said this sender's mail is important: never offered for archiving."""
        return bool(
            self.db.one(
                "SELECT 1 FROM email_audit_items WHERE account_id = ? AND address = ? "
                "AND email_id IS NULL AND answer IN ('important', 'both')",
                (account_id, address.lower()),
            )
        )

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
        await self.services.outbox.send(
            member,
            self._question(item, done + 1, total),
            priority=Priority.REPLY,  # they're going through it now
            kind="email_audit",
            buttons=[
                *(
                    Button(
                        a.capitalize(),
                        "email_audit",
                        {"action": "answer", "item": item["id"], "answer": a},
                    )
                    for a in ANSWERS
                ),
                Button("Stop for now", "email_audit", {"action": "stop"}),
            ],
        )
        return True

    def _question(self, item: dict[str, Any], i: int, n: int) -> str:
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

    async def answer(self, member: Member, item_id: int, answer: str) -> str | None:
        """Record one answer and act on it. Returns the line the question becomes."""
        item = self.db.one(
            "SELECT * FROM email_audit_items WHERE id = ? AND member_id = ?", (item_id, member.id)
        )
        if item is None or answer not in ANSWERS:
            return None
        if item["answer"] is None:
            self.db.execute(
                "UPDATE email_audit_items SET answer = ?, answered_at = ? WHERE id = ?",
                (answer, _now(), item_id),
            )
            self._apply(member, item, answer)
        return ANSWERED_TEXT.format(label=item["label"], words=ANSWER_WORDS[answer])

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
        line = await self.answer(
            member, int(event.button.payload["item"]), str(event.button.payload["answer"])
        )
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


@tool(
    "start_email_audit",
    "Go through the emails and senders Themi wasn't sure about, one at a time, when they "
    "ask ('let's do the email audit', 'which emails did I need to look at?'). Each one comes "
    "with buttons: urgent, important, both or neither.",
    {},
)
async def start_email_audit(ctx: ToolContext, args: dict[str, Any]) -> str:
    audit = ctx.services.email_audit
    if audit is None:
        raise ToolFailed("Email isn't set up.")
    if not await audit.start(ctx.member):
        raise ToolDeclined(NOTHING_TEXT)
    return "The first one is on its way to them, with buttons. Say nothing more about it."
