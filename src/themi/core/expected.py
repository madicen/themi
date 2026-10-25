"""Expected emails and anomalies: the Tier 3 override for email.

An expected email is a recurring message someone counts on (the PG&E payment
confirmation each month): a sender pattern, an optional subject pattern, a
cadence and some grace days, on one linked inbox.

- Every synced email that matches updates its `last_seen_at` (first-sync mail
  too, so the baseline starts right).
- The `email.expected` job flags one that is overdue past its grace period:
  one alert per missed period, and its category escalates.
- Other anomalies escalate too:
    - an unknown sender inside a trusted pattern: mail that matches an
      expected email, from an address in its domain never seen for it;
    - an unusually large amount in a confirmation, against that sender's
      earlier confirmations (amounts are parsed from the text, not taken from
      the model).
- Escalating only changes an automatic (Tier 2) category: it asks first again
  until someone taps [Resume automatic] (admins) or resumes it on the website.

People set these up in chat ("tell me if the PG&E confirmation doesn't show
up", via `expect_email`) or on the website's My accounts page.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import (
    AccountsError,
    Actor,
    InvalidValue,
    LinkedAccount,
    Member,
    NotFound,
    PermissionDenied,
    sender_matches,
    sender_pattern,
)
from themi.accounts.store import SystemActor
from themi.autonomy import Tier
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.connectors.gmail import EmailReceived, GmailSync
from themi.core.services import Services
from themi.core.tools import ToolContext, tool
from themi.localtime import to_local, to_utc_iso

if TYPE_CHECKING:
    from themi.core.triage import Verdict

log = logging.getLogger(__name__)

DEFAULT_CATEGORY = "email_mark_read"
AMOUNT_HISTORY = 6  # earlier confirmations compared against
AMOUNT_MIN_HISTORY = 3
AMOUNT_FACTOR = 1.5  # unusual: above 1.5x the usual amount...
AMOUNT_MIN_JUMP_CENTS = 2000  # ...and at least $20 more

OVERDUE_TEXT = (
    "{name} hasn't shown up in {address} yet. It usually comes every {cadence}; "
    "the last one arrived {last}."
)
UNKNOWN_SENDER_TEXT = (
    "An email that looks like {name} came from an address not seen for it before: {sender}, "
    '"{subject}". Worth a look that it\'s genuine before trusting it.'
)
AMOUNT_TEXT = (
    'A confirmation from {sender} shows {amount}, well above the usual {usual}: "{subject}".'
)
PAUSED_TEXT = ' "{label}" is back to asking first until it\'s resumed.'
PAUSED_NOT_ADMIN_TEXT = (
    ' "{label}" is back to asking first; an admin can resume it from the website\'s Trust page.'
)
RESUMED_TEXT = '"{label}" is automatic again.'
ALREADY_RESUMED_TEXT = '"{label}" was already resumed.'

_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
_AMOUNT_WORDS = re.compile(r"\b(total|amount|paid|payment|charged|balance|due)\b", re.I)


@dataclass(frozen=True)
class ExpectedEmail:
    id: int
    account_id: int
    name: str
    sender_pattern: str
    subject_pattern: str
    cadence_days: int
    grace_days: int
    category: str
    known_senders: tuple[str, ...]
    last_seen_at: datetime | None
    last_alerted_at: datetime | None
    created_at: datetime

    def matches(self, address: str, subject: str) -> bool:
        if not sender_matches(self.sender_pattern, address):
            return False
        return self.subject_pattern.lower() in subject.lower()

    def missed_period(self, now: datetime) -> datetime | None:
        """When the current missed period began (due date plus grace), or None if on time."""
        cadence = timedelta(days=self.cadence_days)
        first_miss = (
            (self.last_seen_at or self.created_at) + cadence + timedelta(days=self.grace_days)
        )
        if now < first_miss:
            return None
        return first_miss + cadence * ((now - first_miss) // cadence)


def _expected_from_row(row: dict[str, Any]) -> ExpectedEmail:
    def when(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    return ExpectedEmail(
        id=row["id"],
        account_id=row["account_id"],
        name=row["name"],
        sender_pattern=row["sender_pattern"],
        subject_pattern=row["subject_pattern"],
        cadence_days=row["cadence_days"],
        grace_days=row["grace_days"],
        category=row["category"],
        known_senders=tuple(json.loads(row["known_senders"])),
        last_seen_at=when(row["last_seen_at"]),
        last_alerted_at=when(row["last_alerted_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def parse_amount(text: str) -> int | None:
    """The dollar amount an email is about, in cents: one next to a word like
    "total" or "paid" if there is one, otherwise the largest."""
    found: list[tuple[bool, int]] = []
    for match in _AMOUNT.finditer(text):
        cents = int(match.group(1).replace(",", "")) * 100 + int(match.group(2) or 0)
        before = text[max(0, match.start() - 40) : match.start()]
        found.append((bool(_AMOUNT_WORDS.search(before)), cents))
    if not found:
        return None
    labelled = [cents for near, cents in found if near]
    return max(labelled or [cents for _, cents in found])


def dollars(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def cadence_words(days: int) -> str:
    named = {1: "day", 7: "week", 14: "two weeks", 30: "month", 31: "month", 90: "three months"}
    if days in named:
        return named[days]
    if days in (365, 366):
        return "year"
    return f"{days} days"


class ExpectedEmails:
    def __init__(self, services: Services, gmail: GmailSync) -> None:
        self.services = services
        self.gmail = gmail
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.expected = self
        self.gmail.listeners.append(self.on_email)
        if s.triage is not None:
            s.triage.verdict_listeners.append(self.on_triaged)
        s.button_handlers["resume_automatic"] = self.on_resume_button
        s.tools.register(expect_email)
        s.tools.register(list_expected_emails)
        s.tools.register(forget_expected_email)

    # ----- managing them -----------------------------------------------------

    def get(self, expected_id: int) -> ExpectedEmail:
        row = self.db.one("SELECT * FROM expected_emails WHERE id = ?", (expected_id,))
        if row is None:
            raise NotFound(f"no expected email {expected_id}")
        return _expected_from_row(row)

    def for_account(self, account_id: int) -> list[ExpectedEmail]:
        rows = self.db.query(
            "SELECT * FROM expected_emails WHERE account_id = ? ORDER BY name", (account_id,)
        )
        return [_expected_from_row(r) for r in rows]

    def for_member(self, member: Member) -> list[ExpectedEmail]:
        rows = self.db.query(
            "SELECT x.* FROM expected_emails x JOIN linked_accounts a ON a.id = x.account_id "
            "WHERE a.member_id = ? ORDER BY x.name",
            (member.id,),
        )
        return [_expected_from_row(r) for r in rows]

    def _own_account(self, actor: Actor, account_id: int) -> LinkedAccount:
        account = self.store.get_linked_account(account_id)
        if not isinstance(actor, SystemActor) and actor.id != account.member_id:
            raise PermissionDenied("expected emails can only be set on their own inboxes")
        return account

    def add(
        self,
        actor: Actor,
        account_id: int,
        *,
        name: str,
        sender: str,
        subject: str = "",
        cadence_days: int = 30,
        grace_days: int = 3,
        category: str = DEFAULT_CATEGORY,
    ) -> ExpectedEmail:
        self._own_account(actor, account_id)
        name = " ".join(name.split())
        if not name:
            raise InvalidValue("an expected email needs a name")
        if not 1 <= cadence_days <= 400:
            raise InvalidValue("how often it comes should be between 1 and 400 days")
        if not 0 <= grace_days <= 60:
            raise InvalidValue("the grace period should be between 0 and 60 days")
        if self.services.autonomy.category(category).capped:
            raise InvalidValue("that category always asks first, so it has nothing to protect")
        pattern = sender_pattern(sender)
        subject = " ".join(subject.split())
        if self.db.one(
            "SELECT 1 FROM expected_emails WHERE account_id = ? AND name = ?", (account_id, name)
        ):
            raise InvalidValue(f"{name!r} is already expected in that inbox")
        expected_id = self.db.execute(
            "INSERT INTO expected_emails (account_id, name, sender_pattern, subject_pattern, "
            "cadence_days, grace_days, category, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                account_id,
                name,
                pattern,
                subject,
                cadence_days,
                grace_days,
                category,
                to_utc_iso(clock.now()),
            ),
        )
        expected = self.get(expected_id)
        # Mail already here (a first sync, say) sets the baseline.
        for row in self.db.query(
            "SELECT from_address, subject, received_at FROM emails WHERE account_id = ? "
            "ORDER BY received_at",
            (account_id,),
        ):
            if expected.matches(row["from_address"], row["subject"]):
                expected = self._seen(expected, row["from_address"], row["received_at"])
        return expected

    def remove(self, actor: Actor, expected_id: int) -> ExpectedEmail:
        expected = self.get(expected_id)
        self._own_account(actor, expected.account_id)
        self.db.execute("DELETE FROM expected_emails WHERE id = ?", (expected_id,))
        return expected

    def _seen(self, expected: ExpectedEmail, address: str, received_at: str) -> ExpectedEmail:
        known = list(expected.known_senders)
        if address.lower() not in known:
            known.append(address.lower())
        received = datetime.fromisoformat(received_at)
        last_seen = max(filter(None, [expected.last_seen_at, received]))
        self.db.execute(
            "UPDATE expected_emails SET known_senders = ?, last_seen_at = ? WHERE id = ?",
            (json.dumps(known), to_utc_iso(last_seen), expected.id),
        )
        return self.get(expected.id)

    # ----- incoming mail -------------------------------------------------------

    async def on_email(self, event: EmailReceived) -> None:
        row = self.db.one(
            "SELECT from_name, from_address, subject, received_at FROM emails WHERE id = ?",
            (event.email_id,),
        )
        if row is None:
            return
        address = row["from_address"].lower()
        for expected in self.for_account(event.account.id):
            if not expected.matches(address, row["subject"]):
                continue
            unknown = (
                expected.sender_pattern.startswith("@")
                and bool(expected.known_senders)
                and address not in expected.known_senders
            )
            self._seen(expected, address, row["received_at"])
            if unknown and not event.initial:
                sender = f"{row['from_name']} <{address}>" if row["from_name"] else address
                await self._anomaly(
                    event.account,
                    expected.category,
                    f"{expected.name} came from a new address ({address})",
                    UNKNOWN_SENDER_TEXT.format(
                        name=expected.name, sender=sender, subject=row["subject"]
                    ),
                    dedupe_key=f"expected-sender:{event.email_id}",
                )

    async def on_triaged(
        self, member: Member, account: LinkedAccount, row: dict[str, Any], verdict: Verdict
    ) -> None:
        """Confirmations: record the amount, and flag one far above that sender's usual."""
        if verdict.category != "confirmation":
            return
        amount = parse_amount(f"{row['subject']}\n{row['body_text']}")
        if amount is None:
            return
        self.db.execute("UPDATE emails SET amount_cents = ? WHERE id = ?", (amount, row["id"]))
        if row["initial"]:
            return
        earlier = [
            r["amount_cents"]
            for r in self.db.query(
                "SELECT amount_cents FROM emails WHERE account_id = ? AND from_address = ? "
                "AND category = 'confirmation' AND amount_cents IS NOT NULL AND id != ? "
                "ORDER BY received_at DESC LIMIT ?",
                (account.id, row["from_address"], row["id"], AMOUNT_HISTORY),
            )
        ]
        if len(earlier) < AMOUNT_MIN_HISTORY:
            return
        usual = int(statistics.median(earlier))
        if amount <= max(usual * AMOUNT_FACTOR, usual + AMOUNT_MIN_JUMP_CENTS):
            return
        await self._anomaly(
            account,
            DEFAULT_CATEGORY,
            f"an unusually large amount ({dollars(amount)}) from {row['from_address']}",
            AMOUNT_TEXT.format(
                sender=row["from_name"] or row["from_address"],
                amount=dollars(amount),
                usual=dollars(usual),
                subject=row["subject"],
            ),
            dedupe_key=f"expected-amount:{row['id']}",
        )

    # ----- overdue ---------------------------------------------------------------

    async def check_overdue(self) -> int:
        """Scheduler job: alert once per missed period. Returns how many were flagged."""
        now = clock.now()
        family = self.store.get_family()
        timezone = family.timezone if family else "UTC"
        flagged = 0
        for row in self.db.query("SELECT * FROM expected_emails ORDER BY id"):
            expected = _expected_from_row(row)
            since = expected.missed_period(now)
            if since is None:
                continue
            if expected.last_alerted_at is not None and expected.last_alerted_at >= since:
                continue
            account = self.store.get_linked_account(expected.account_id)
            last = (
                to_local(expected.last_seen_at, timezone).strftime("on %B %-d")
                if expected.last_seen_at
                else "before Themi started watching"
            )
            self.db.execute(
                "UPDATE expected_emails SET last_alerted_at = ? WHERE id = ?",
                (to_utc_iso(now), expected.id),
            )
            await self._anomaly(
                account,
                expected.category,
                f"{expected.name} is overdue",
                OVERDUE_TEXT.format(
                    name=expected.name[:1].upper() + expected.name[1:],
                    address=account.address,
                    cadence=cadence_words(expected.cadence_days),
                    last=last,
                ),
                dedupe_key=f"expected-overdue:{expected.id}:{to_utc_iso(since)}",
            )
            flagged += 1
        return flagged

    # ----- escalating ------------------------------------------------------------

    async def _anomaly(
        self, account: LinkedAccount, category: str, reason: str, text: str, *, dedupe_key: str
    ) -> None:
        autonomy = self.services.autonomy
        member = self.store.get_member(account.member_id)
        current = autonomy.category(category)
        buttons: list[Button] = []
        if current.tier is Tier.AUTOMATIC:
            if not current.escalated:
                autonomy.escalate(category, reason)
            if member.is_admin:
                text += PAUSED_TEXT.format(label=current.label)
                buttons.append(
                    Button("Resume automatic", "resume_automatic", {"category": category})
                )
            else:
                text += PAUSED_NOT_ADMIN_TEXT.format(label=current.label)
        await self.services.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
            kind="email",
            buttons=buttons,
            dedupe_key=dedupe_key,
        )

    async def on_resume_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        autonomy = self.services.autonomy
        try:
            category = autonomy.category(str(event.button.payload["category"]))
        except AccountsError:
            return
        if not category.escalated:
            text = ALREADY_RESUMED_TEXT.format(label=category.label)
        else:
            try:
                autonomy.resume(category.name, by=event.member)
            except PermissionDenied:
                await self.services.outbox.send(
                    event.member,
                    "Only an admin can resume an automatic category.",
                    priority=Priority.REPLY,
                )
                return
            text = RESUMED_TEXT.format(label=category.label)
        if event.button.message_id is not None:
            await self.services.outbox.edit(event.member, event.button.message_id, text)


# ----- tools: expected emails in conversation --------------------------------------


def _account_for(ctx: ToolContext, inbox: str) -> LinkedAccount | str:
    accounts = [a for a in ctx.services.store.linked_accounts(ctx.member.id) if a.enabled]
    if inbox.strip():
        match = [a for a in accounts if a.address == inbox.strip().lower()]
        return match[0] if match else "That isn't one of this person's linked inboxes."
    if len(accounts) == 1:
        return accounts[0]
    if not accounts:
        return "This person has no linked inbox yet; /link gmail links one."
    return "Which inbox? This person has " + ", ".join(a.address for a in accounts) + "."


def _sender_from(ctx: ToolContext, account: LinkedAccount, sender: str) -> str | None:
    """An address or domain as given, or the domain of recent mail from a sender named so."""
    if "@" in sender or "." in sender:
        return sender
    row = ctx.services.store.db.one(
        "SELECT from_address FROM emails WHERE account_id = ? AND lower(from_name) LIKE ? "
        "ORDER BY received_at DESC LIMIT 1",
        (account.id, f"%{sender.strip().lower()}%"),
    )
    return "@" + row["from_address"].split("@", 1)[1] if row else None


def _describe(expected: ExpectedEmail, address: str) -> str:
    subject = (
        f' with "{expected.subject_pattern}" in the subject' if expected.subject_pattern else ""
    )
    seen = (
        f"last seen {expected.last_seen_at.date().isoformat()}"
        if expected.last_seen_at
        else "not seen yet"
    )
    return (
        f"{expected.name} in {address}: from {expected.sender_pattern}{subject}, every "
        f"{expected.cadence_days} days with {expected.grace_days} days' grace ({seen})"
    )


@tool(
    "expect_email",
    "Watch for a recurring email (like a bill confirmation) and say so if it doesn't show up "
    "on time. Use when someone asks to be told if an email doesn't arrive.",
    {
        "name": {"type": "string", "description": "What it is, e.g. 'the PG&E confirmation'."},
        "sender": {
            "type": "string",
            "description": "The sender's address or domain, or their name as it appears "
            "on earlier mail (e.g. 'PG&E') to look it up.",
        },
        "subject": {
            "type": "string",
            "description": "Words its subject always has, or '' for any subject.",
        },
        "cadence_days": {"type": "integer", "description": "How often it comes: 30 for monthly."},
        "grace_days": {
            "type": "integer",
            "description": "Days of slack after it's due; 3 if unsure.",
        },
        "inbox": {
            "type": "string",
            "description": "The linked Gmail address, or '' if they have only one.",
        },
    },
)
async def expect_email(ctx: ToolContext, args: dict[str, Any]) -> str:
    expected_emails = ctx.services.expected
    if expected_emails is None:
        return "Email isn't set up on this server."
    account = _account_for(ctx, str(args.get("inbox") or ""))
    if isinstance(account, str):
        return account
    sender = _sender_from(ctx, account, str(args["sender"]))
    if sender is None:
        return f"No mail from {args['sender']!r} found in {account.address}; ask for their address."
    try:
        expected = expected_emails.add(
            ctx.member,
            account.id,
            name=str(args["name"]),
            sender=sender,
            subject=str(args.get("subject") or ""),
            cadence_days=int(args["cadence_days"]),
            grace_days=int(args["grace_days"]),
        )
    except AccountsError as exc:
        return f"Not saved: {exc}"
    return "Watching for " + _describe(expected, account.address) + "."


@tool("list_expected_emails", "List the recurring emails Themi watches for, for this person.", {})
async def list_expected_emails(ctx: ToolContext, args: dict[str, Any]) -> str:
    expected_emails = ctx.services.expected
    if expected_emails is None:
        return "Email isn't set up on this server."
    addresses = {a.id: a.address for a in ctx.services.store.linked_accounts(ctx.member.id)}
    items = expected_emails.for_member(ctx.member)
    if not items:
        return "No expected emails yet."
    return "\n".join("- " + _describe(x, addresses[x.account_id]) for x in items)


@tool(
    "forget_expected_email",
    "Stop watching for one of this person's expected emails.",
    {"name": {"type": "string", "description": "Its name, as list_expected_emails shows it."}},
)
async def forget_expected_email(ctx: ToolContext, args: dict[str, Any]) -> str:
    expected_emails = ctx.services.expected
    if expected_emails is None:
        return "Email isn't set up on this server."
    wanted = " ".join(str(args["name"]).split()).lower()
    for expected in expected_emails.for_member(ctx.member):
        if expected.name.lower() == wanted:
            expected_emails.remove(ctx.member, expected.id)
            return f"No longer watching for {expected.name}."
    return "No expected email by that name."
