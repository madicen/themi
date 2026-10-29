"""Suggesting senders that should always count as urgent (E1, Erin's idea #27).

When someone links an inbox, Themi asks which senders always count as urgent. Rather than
leave them to think of it, once the inbox's first mail has been sorted Themi looks at who
writes and offers a few likely ones, a button each; only what they tap is added
(`urgent_senders`), never anything on Themi's own say-so.

A sender is likely when, in the last 90 days, triage called their mail urgent about money,
the property, tenants or family, or a real person who has written more than once was
waiting on a reply. Senders already marked urgent, or offered before, aren't offered again.
The `email.senders` job runs every 6 hours, so new likely senders come up now and then.
With the email audit (E2) they wait there, one task, instead of coming as a message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import AccountsError, LinkedAccount, Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.groceries import and_list
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

LOOK_BACK = timedelta(days=90)
MAX_OFFERED = 4
OFFER_TEXT = (
    "A few senders in {address} might always count as time-sensitive: {senders}. Tap any that "
    "should; nothing changes otherwise."
)
ADDED_TEXT = "Added: mail from {label} ({address}) always counts as time-sensitive now."
WHY = {
    "financial": "money",
    "property": "the property",
    "tenant": "a tenant",
    "family": "family",
}


@dataclass(frozen=True)
class Candidate:
    address: str
    label: str  # the sender's name, or the address
    reason: str  # "money", "waiting on replies"
    weight: int


class SenderSuggestions:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.button_handlers["urgent_sender"] = self.on_button
        self.services.tools.register(inbox_setup)
        self.services.senders = self

    def setup(self, account: LinkedAccount) -> str:
        """What's set for an inbox, in a line (bug #45)."""
        waiting = self.db.query(
            "SELECT DISTINCT label, address FROM sender_suggestions WHERE account_id = ? "
            "AND added_at IS NULL ORDER BY id",
            (account.id,),
        )
        expected = self.db.query(
            "SELECT name FROM expected_emails WHERE account_id = ? ORDER BY id", (account.id,)
        )
        state = "watched" if account.watched else "not watched"
        if not account.enabled:
            state += " (Google stopped accepting it; linking it again fixes it)"
        urgent = ", ".join(account.urgent_senders) or "none"
        suggested = and_list(
            [r["label"] if r["label"] == r["address"] else f"{r['label']} ({r['address']})"
             for r in waiting
             if r["address"] not in account.urgent_senders]
        )  # fmt: skip
        return (
            f"{account.address}: {state}. Time-sensitive senders: {urgent}. Suggested, not "
            f"answered yet: {suggested or 'none'}. Expected emails: "
            f"{', '.join(r['name'] for r in expected) or 'none'}."
        )

    def candidates(self, account: LinkedAccount) -> list[Candidate]:
        """Likely senders for this inbox, the likeliest first."""
        rows = self.db.query(
            "SELECT lower(from_address) AS address, MAX(from_name) AS name, "
            "SUM(category = 'urgent' AND urgent_kind IN ('financial', 'property', 'tenant', "
            "'family')) AS urgent, MAX(CASE WHEN category = 'urgent' THEN urgent_kind END) "
            "AS kind, SUM(category = 'needs_reply') AS replies, COUNT(*) AS mails "
            "FROM emails WHERE account_id = ? AND triage_status = 'done' AND received_at >= ? "
            "GROUP BY lower(from_address)",
            (account.id, to_utc_iso(clock.now() - LOOK_BACK)),
        )
        offered = {
            r["address"]
            for r in self.db.query(
                "SELECT address FROM sender_suggestions WHERE account_id = ?", (account.id,)
            )
        }
        found = []
        for r in rows:
            address = r["address"]
            if address in offered or account.is_urgent_sender(address):
                continue
            label = (r["name"] or address).strip()
            if r["urgent"]:
                why = WHY.get(r["kind"], "urgent mail")
                found.append(Candidate(address, label, why, 2 + r["urgent"]))
            elif r["replies"] and r["mails"] >= 2:
                found.append(Candidate(address, label, "waiting on replies", r["replies"]))
        return sorted(found, key=lambda c: (-c.weight, c.label.casefold()))[:MAX_OFFERED]

    async def offer(self) -> int:
        """Scheduler job: offer likely senders for each watched inbox whose first mail has
        been sorted. Returns how many offers went."""
        sent = 0
        accounts = [a for m in self.store.list_members() for a in self.store.linked_accounts(m.id)]
        for account in accounts:
            if not account.enabled or not account.watched:
                continue
            if self.db.one(
                "SELECT 1 FROM emails WHERE account_id = ? AND triage_status = 'pending'",
                (account.id,),
            ):
                continue  # not sorted yet
            found = self.candidates(account)
            if not found:
                continue
            member = self.store.get_member(account.member_id)
            buttons = []
            audit = self.services.email_audit
            for c in found:
                suggestion = self.db.execute(
                    "INSERT INTO sender_suggestions (account_id, address, label, offered_at) "
                    "VALUES (?, ?, ?, ?)",
                    (account.id, c.address, c.label, to_utc_iso(clock.now())),
                )
                if audit is not None:  # E2: waiting in the audit, not a message of its own
                    audit.add_sender(account, c.address, c.label, c.reason, suggestion)
                buttons.append(Button(c.label[:40], "urgent_sender", {"suggestion": suggestion}))
            if audit is not None:
                await audit.refresh(member)
                sent += 1
                continue
            senders = and_list([f"{c.label} ({c.reason})" for c in found])
            await self.services.outbox.send(
                member,
                OFFER_TEXT.format(address=account.address, senders=senders),
                priority=Priority.NORMAL,
                kind="email",
                buttons=buttons,
            )
            sent += 1
        if self.services.email_audit is not None:  # what's waiting has its task (E2)
            for member in self.store.list_members():
                if self.services.email_audit.waiting(member):
                    await self.services.email_audit.refresh(member)
        return sent

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        row = self.add(event.member, int(event.button.payload["suggestion"]))
        if row is None:
            return
        await self.services.outbox.send(
            event.member,
            ADDED_TEXT.format(label=row["label"], address=row["address"]),
            priority=Priority.REPLY,
        )

    def add(self, member: Member, suggestion: int) -> dict[str, Any] | None:
        """A suggested sender, confirmed: it always counts as urgent now. Returns the
        suggestion, or None if it isn't theirs."""
        row = self.db.one("SELECT * FROM sender_suggestions WHERE id = ?", (suggestion,))
        if row is None:
            return None
        try:
            account = self.store.get_linked_account(row["account_id"])
            if account.member_id != member.id:
                return None
            patterns = list(account.urgent_senders)
            if row["address"] not in patterns:
                self.store.update_linked_account(
                    member, account.id, urgent_senders=[*patterns, row["address"]]
                )
        except AccountsError:
            return None
        self.db.execute(
            "UPDATE sender_suggestions SET added_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), row["id"]),
        )
        return row


@tool(
    "inbox_setup",
    "What's set for each of this person's linked Gmail inboxes: watched or not, the senders "
    "that always count as time-sensitive, the suggested senders they haven't answered yet, "
    "the expected emails, and what time-sensitive, urgent and important do. For 'what's my "
    "email set up to do?', 'what does urgent mean?' or 'which senders did I need to look "
    "at?'; set one sender's levels with set_sender_levels.",
    {},
)
async def inbox_setup(ctx: ToolContext, args: dict[str, Any]) -> str:
    senders = ctx.services.senders
    if senders is None:
        raise ToolFailed("Email isn't set up on this server.")
    accounts = [
        a for a in ctx.services.store.linked_accounts(ctx.member.id) if a.provider == "gmail"
    ]
    if not accounts:
        return "They haven't linked a Gmail inbox (My accounts on the website)."
    from themi.core.email_audit import LEVELS_TEXT

    return "\n".join([*(senders.setup(a) for a in accounts), LEVELS_TEXT])
