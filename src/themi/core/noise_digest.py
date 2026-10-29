"""Noise emails in one message (F16b; ideas #61 and #63, bug #66).

Triage still stages each noise email as `email_archive_noise`, but approvals holds them:
no card each. Instead, at the time the person chose (`members.noise_emails`: once a day
at 6 pm by default, twice a day at noon and 6 pm, or every other day at 6 pm), one message
lists them, with [Archive all] and [Not now]:

    3 emails look like noise:
    - Shop: 20% off
    - ...
    Archive them all? You can also pick on the website, under Emails to archive.

- It's a normal message: the daily limit, quiet hours and pauses hold it like any other.
  A newer one replaces one still waiting to go.
- Before it goes, each email is looked up in Gmail. One no longer in the Primary inbox
  (archived, deleted, filed by hand, or in another of Gmail's tabs, F16d) is left out and
  its offer closed quietly. If Gmail can't be reached, it's listed anyway. A message the
  daily limit is holding is made again at most once an hour, so it stays true.
- [Archive all] (or a bare "yes" to it) archives every one still open and edits the
  message to say so. [Not now] leaves them for the next message.
- The website's "Emails to archive" page lists the same offers, to archive or keep each.

Automatic archiving (F16a: the person's own switch) still runs at once; this only changes
how the asking is done.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.autonomy import Action, Decision
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.connectors.gmail.parse import in_primary
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.connectors.gmail import GmailSync
    from themi.core.approvals import ApprovalsUI
    from themi.core.services import AwaitingItem, Services
    from themi.core.services import Decision as ChatDecision

log = logging.getLogger(__name__)

CATEGORY = "email_archive_noise"
NOON, EVENING = time(12), time(18)
SLOTS = {"daily": (EVENING,), "twice": (NOON, EVENING), "every_other_day": (EVENING,)}
SEND_WITHIN = timedelta(hours=3)  # a time missed by more than this (Themi was down) waits
REBUILD_AFTER = timedelta(hours=1)  # a message still held is made again this often (F16d)
MAX_LINES = 15

HEADER_ONE = "One email looks like noise:"
HEADER_MANY = "{count} emails look like noise:"
ASK_ONE = "Archive it? You can also pick on the website, under Emails to archive."
ASK_MANY = "Archive them all? You can also pick on the website, under Emails to archive."
ARCHIVED_TEXT = "Archived {count}."
FAILED_TEXT = " {count} didn't go through; they're in /pending to try again."
LATER_TEXT = "Left for now. They'll be in the next one."
NOTHING_LEFT_TEXT = "Those are all taken care of already."


class NoiseDigest:
    def __init__(self, services: Services, approvals: ApprovalsUI, gmail: GmailSync) -> None:
        self.services = services
        self.approvals = approvals
        self.gmail = gmail
        self.autonomy = services.autonomy
        self.db = services.store.db

    def install(self) -> None:
        self.approvals.held.add(CATEGORY)
        self.services.button_handlers["noise"] = self.on_button
        self.services.awaiting_sources.append(self.awaiting_items)
        self.services.noise = self

    # ----- what's waiting -------------------------------------------------------------

    def waiting(self, member: Member) -> list[Action]:
        """Their offers to archive that nobody has answered yet, oldest first."""
        return [
            a
            for a in self.autonomy.open_for(member)
            if a.category == CATEGORY and a.status in ("pending", "snoozed")
        ]

    def line(self, action: Action) -> str:
        """'Shop: 20% off', from the email itself (the summary as a fallback)."""
        row = self.gmail.email(int(action.payload.get("email_id", 0)))
        if row is None:
            return action.summary
        sender = row["from_name"] or row["from_address"]
        return f"{sender}: {row['subject'] or '(no subject)'}"

    async def still_in_inbox(self, actions: list[Action]) -> list[Action]:
        """Leave out (and close) offers for email that's no longer in the inbox (#66)."""
        kept = []
        for action in actions:
            row = self.gmail.email(int(action.payload.get("email_id", 0)))
            if row is None:
                await self.autonomy.withdraw(action.id, "That email is gone.")
                continue
            try:
                message = await self.gmail.client(row["account_id"]).get_message(row["gmail_id"])
            except Exception as exc:  # Gmail unreachable: list it anyway
                log.info("Couldn't check email %s in Gmail (%s)", row["id"], type(exc).__name__)
                kept.append(action)
                continue
            if message is None or not in_primary(message.get("labelIds", [])):
                await self.autonomy.withdraw(action.id, "Already out of the inbox.")
                continue
            kept.append(action)
        return kept

    # ----- the message ------------------------------------------------------------------

    async def run(self) -> int:
        """Scheduler job: send each person's message when their time comes. Returns how many."""
        tz = self._tz()
        now = clock.now().astimezone(tz)
        sent = 0
        for member in self.services.store.list_members():
            if member.telegram_user_id is None:
                continue
            due = self._due(member, now) or self._stale(member, now)
            if due and await self.send(member):
                sent += 1
        return sent

    def _due(self, member: Member, now: datetime) -> bool:
        last = self._last(member)
        for at in SLOTS.get(member.noise_emails, SLOTS["daily"]):
            due_at = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
            if not due_at <= now < due_at + SEND_WITHIN:
                continue
            if last is not None and last >= due_at:
                return False  # this one went already
            if member.noise_emails == "every_other_day" and last is not None:
                return (now.date() - last.astimezone(now.tzinfo).date()).days >= 2
            return True
        return False

    def _stale(self, member: Member, now: datetime) -> bool:
        """Their latest message is still waiting to go (the daily limit), and was made over
        an hour ago: make it again, so what it lists is still in the inbox."""
        row = self._latest(member)
        if row is None or not row["outbox_id"] or row["answer"] is not None:
            return False
        if datetime.fromisoformat(row["created_at"]) > now - REBUILD_AFTER:
            return False
        return bool(
            self.db.one(
                "SELECT 1 FROM outbox WHERE id = ? AND status = 'queued'", (row["outbox_id"],)
            )
        )

    async def send(self, member: Member) -> bool:
        """List what's waiting, in one message. False (and nothing sent) if nothing is."""
        actions = await self.still_in_inbox(self.waiting(member))
        previous = self._latest(member)
        if previous is not None and previous["outbox_id"] and previous["answer"] is None:
            self.services.outbox.cancel(previous["outbox_id"])  # not gone yet: this replaces it
        now = to_utc_iso(clock.now())
        digest_id = self.db.execute(
            "INSERT INTO noise_digests (member_id, action_ids, created_at) VALUES (?, ?, ?)",
            (member.id, json.dumps([a.id for a in actions]), now),
        )
        if not actions:
            return False
        result = await self.services.outbox.send(
            member,
            self.text(actions),
            priority=Priority.NORMAL,
            kind="email",
            buttons=[
                Button("Archive all", "noise", {"digest": digest_id, "answer": "archive"}),
                Button("Not now", "noise", {"digest": digest_id, "answer": "later"}),
            ],
        )
        self.db.execute(
            "UPDATE noise_digests SET outbox_id = ? WHERE id = ?", (result.outbox_id, digest_id)
        )
        return True

    def text(self, actions: list[Action]) -> str:
        count = len(actions)
        lines = [f"- {self.line(a)}" for a in actions[:MAX_LINES]]
        if count > MAX_LINES:
            lines.append(f"- and {count - MAX_LINES} more")
        if count == 1:
            return "\n".join([HEADER_ONE, *lines, ASK_ONE])
        return "\n".join([HEADER_MANY.format(count=count), *lines, ASK_MANY])

    # ----- answering -----------------------------------------------------------------

    async def archive(self, member: Member, action_ids: list[int]) -> tuple[int, int]:
        """Archive these offers of theirs that are still open: (archived, failed)."""
        done = failed = 0
        for action_id in action_ids:
            action = self.autonomy.action(action_id)
            if action.member_id != member.id or action.status not in ("pending", "snoozed"):
                continue
            await self.approvals.resolve(action_id, Decision.APPROVE, member)
            if self.autonomy.action(action_id).status == "done":
                done += 1
            else:
                failed += 1
        return done, failed

    async def keep(self, member: Member, action_ids: list[int]) -> int:
        """Leave these in the inbox (a no to each). Returns how many."""
        kept = 0
        for action_id in action_ids:
            action = self.autonomy.action(action_id)
            if action.member_id != member.id or action.status not in ("pending", "snoozed"):
                continue
            await self.approvals.resolve(action_id, Decision.DECLINE, member)
            kept += 1
        return kept

    async def answer(self, member: Member, digest_id: int, answer: str) -> str:
        row = self.db.one(
            "SELECT * FROM noise_digests WHERE id = ? AND member_id = ?", (digest_id, member.id)
        )
        if row is None:
            return NOTHING_LEFT_TEXT
        action_ids = json.loads(row["action_ids"])
        listed = [self.autonomy.action(i) for i in action_ids]
        open_ids = [a.id for a in listed if a.status in ("pending", "snoozed")]
        if not open_ids:
            said = NOTHING_LEFT_TEXT
        elif answer == "archive":
            done, failed = await self.archive(member, open_ids)
            said = ARCHIVED_TEXT.format(count=done) + (
                FAILED_TEXT.format(count=failed) if failed else ""
            )
        else:
            said = LATER_TEXT
        self.db.execute(
            "UPDATE noise_digests SET answer = ? WHERE id = ?",
            ("archived" if answer == "archive" else "later", digest_id),
        )
        message_id = self.services.outbox.message_id(row["outbox_id"]) if row["outbox_id"] else None
        if message_id is not None:
            header = self.text(listed).split("\n", 1)[0]
            await self.services.outbox.edit(member, message_id, f"{header}\n{said}")
        return said

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        said = await self.answer(event.member, int(payload["digest"]), str(payload["answer"]))
        if said == NOTHING_LEFT_TEXT:
            await self.services.outbox.send(event.member, said, priority=Priority.REPLY)

    def awaiting_items(self, member: Member) -> list[AwaitingItem]:
        """The latest message, while it's unanswered: a bare "yes" archives them all."""
        from themi.core.services import AwaitingItem

        row = self._latest(member)
        if row is None or row["answer"] is not None or not row["outbox_id"]:
            return []
        message_id = self.services.outbox.message_id(row["outbox_id"])
        if message_id is None:
            return []
        open_ids = [
            i
            for i in json.loads(row["action_ids"])
            if self.autonomy.action(i).status in ("pending", "snoozed")
        ]
        if not open_ids:
            return []

        async def resolve(decision: ChatDecision) -> str:
            answer = "archive" if decision == "yes" else "later"
            return await self.answer(member, row["id"], answer)

        count = len(open_ids)
        return [
            AwaitingItem(
                f"noise:{row['id']}",
                f"Archive {count} email{'s' if count != 1 else ''} that look like noise",
                resolve,
                (message_id,),
            )
        ]

    # ----- small things ---------------------------------------------------------------

    def _latest(self, member: Member) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM noise_digests WHERE member_id = ? ORDER BY id DESC LIMIT 1",
            (member.id,),
        )

    def _last(self, member: Member) -> datetime | None:
        row = self._latest(member)
        return datetime.fromisoformat(row["created_at"]) if row else None

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")
