"""Relays (34a): a note one partner asks Themi to pass on to the other.

"Tell him the vet called", "let Erin know the dog's been fed", "ask her if she wants
takeout": `relay_to_partner` keeps the note and sends it through the outbox, so it goes
with the recipient's own PDA shielding, phrasing, quiet hours and busy times. When:
- urgent: now, even in quiet hours (an urgent outbox message);
- today: at the recipient's next good window, and by early evening at the latest (a
  deadline at 6 pm; said after that, it goes at their next free moment);
- whenever: at the recipient's next good window.

A job for the other person to do ("ask him to take the bins out") isn't a note: it's a task
assigned to them, so it reaches them as a nudge. The person must have asked for something
to be passed on in their own words (`ASKS_TO_PASS_ON`); the model's say-so isn't enough.

Notes not passed on yet are open items for whoever asked. Each is recorded in
`liaison_items` and marked delivered when its message goes. Prompt 34b adds the family
group and alignment prompts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.outbox import OutboxResult, Priority
from themi.core.prompts import OpenItem
from themi.core.tasks import clock_words
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import start_of_local_day, to_local, to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

KIND = "relay"  # the outbox kind; the "notes" pause topic holds it
URGENCIES = ("urgent", "today", "whenever")
EARLY_EVENING = time(18, 0)  # a "today" note goes by then at the latest
SAME_NOTE = timedelta(minutes=30)  # the same note asked for again this soon: already done
MAX_BODY = 1000

# What the person must have said: a message to pass on, not a job for them ("ask him to
# take the bins out" is a task). "Tell Hundo I wuv u", "let Erin know...", "message him",
# "send her a note", "pass it on to him", "ask Erin if she wants takeout".
_NOT_THEM = r"(?!me\b|myself\b|us\b|you\b)"
ASKS_TO_PASS_ON = re.compile(
    rf"\btell\s+{_NOT_THEM}\w+"
    rf"|\blet\s+{_NOT_THEM}\w+\s+know\b"
    rf"|\b(?:message|text|ping)\s+{_NOT_THEM}\w+"
    rf"|\bsend\s+{_NOT_THEM}\w+\s+(?:a\s+)?(?:message|note|text)\b"
    r"|\bpass(?:\s+(?:it|this|that|these|a\s+message|a\s+note))?\s+(?:on|along)\b"
    rf"|\bask\s+{_NOT_THEM}\w+\s+(?:if|whether|what|when|where|how|why|who|which|about)\b",
    re.IGNORECASE,
)
_PARTNER_WORDS = frozenset(
    {"", "partner", "my partner", "wife", "my wife", "husband", "my husband", "him", "her"}
)


@dataclass(frozen=True)
class Relay:
    id: int
    from_member_id: int
    to_member_id: int
    body: str
    urgency: str
    outbox_id: int | None
    created_at: datetime
    delivered_at: datetime | None


def _relay(row: dict[str, Any]) -> Relay:
    return Relay(
        id=row["id"],
        from_member_id=row["from_member_id"],
        to_member_id=row["to_member_id"],
        body=row["body"],
        urgency=row["urgency"],
        outbox_id=row["outbox_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        delivered_at=datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None,
    )


def timing(urgency: str, now: datetime, timezone: str) -> tuple[Priority, datetime | None]:
    """The outbox priority and deadline for a note of this urgency, asked for at `now`."""
    if urgency == "urgent":
        return Priority.URGENT, None
    if urgency == "today":
        midnight = to_local(start_of_local_day(now, timezone), timezone)
        evening = midnight.replace(hour=EARLY_EVENING.hour, minute=EARLY_EVENING.minute)
        return Priority.NORMAL, max(now, evening)
    return Priority.NORMAL, None


def delivery_text(sender: Member, body: str, urgency: str) -> str:
    """What the recipient reads: who it's from and the note in the sender's words."""
    return f"{'Urgent, from' if urgency == 'urgent' else 'From'} {sender.name}: {body}"


class Liaison:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.outbox = services.outbox

    def install(self) -> None:
        self.services.liaison = self
        self.services.tools.register(relay_to_partner)
        self.services.open_item_sources.append(self.open_items)
        self.outbox.sent_listeners.append(self.on_sent)

    @property
    def timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    # ----- relaying -------------------------------------------------------------------

    def recipient(self, sender: Member, to: str) -> Member:
        """Who `to` names: a family member by name, or (with only one other person) the
        partner, by "partner", "him", or a nickname the notes explain."""
        others = [m for m in self.store.list_members() if m.id != sender.id]
        wanted = to.strip().lower()
        if wanted and wanted == sender.name.lower():
            raise ToolFailed("That's the person asking: there's no one to pass it on to.")
        for other in others:
            if wanted in (other.name.lower(), other.name.lower().split()[0]):
                return other
        if len(others) == 1 and wanted in _PARTNER_WORDS:
            return others[0]
        if (nicknamed := self._nicknamed(sender, wanted, others)) is not None:
            return nicknamed
        names = ", ".join(m.name for m in others) or "no one else"
        raise ToolFailed(
            f"Not passed on: Themi only passes notes between the family ({names}); say "
            "which of them it's for."
        )

    def _nicknamed(self, sender: Member, wanted: str, others: list[Member]) -> Member | None:
        """The one family member a note Themi keeps gives this nickname ('Erin calls
        Michael "Hundo"'), so "tell Mom" never goes to the partner by default."""
        if not wanted:
            return None
        word = re.compile(rf"\b{re.escape(wanted)}\b", re.IGNORECASE)
        rows = self.db.query(
            "SELECT fact FROM facts WHERE scope = 'family' OR member_id = ?", (sender.id,)
        )
        named = {
            other.id: other
            for row in rows
            if word.search(row["fact"])
            for other in others
            if re.search(rf"\b{re.escape(other.name)}\b", row["fact"], re.IGNORECASE)
        }
        return next(iter(named.values())) if len(named) == 1 else None

    async def relay(
        self, sender: Member, recipient: Member, body: str, urgency: str
    ) -> tuple[Relay, OutboxResult]:
        body = body.strip()[:MAX_BODY]
        if urgency not in URGENCIES:
            raise ToolFailed(f"The urgency is one of {', '.join(URGENCIES)}.")
        if not body:
            raise ToolFailed("Not passed on: the note was empty.")
        if recipient.telegram_user_id is None:
            raise ToolFailed(
                f"Not passed on: {recipient.name} isn't connected to Themi on Telegram yet."
            )
        if (same := self._same_note(sender, recipient, body)) is not None:
            state = "already went" if same.delivered_at else "is already waiting to go"
            raise ToolDeclined(f"That note to {recipient.name} {state}; it wasn't sent twice.")
        now = clock.now()
        relay_id = self.db.execute(
            "INSERT INTO liaison_items (kind, from_member_id, to_member_id, body, urgency, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (KIND, sender.id, recipient.id, body, urgency, to_utc_iso(now)),
        )
        priority, deadline = timing(urgency, now, self.timezone)
        result = await self.outbox.send(
            recipient,
            delivery_text(sender, body, urgency),
            priority=priority,
            kind=KIND,
            deadline=deadline,
            dedupe_key=f"relay:{relay_id}",
        )
        self.db.execute(
            "UPDATE liaison_items SET outbox_id = ? WHERE id = ?", (result.outbox_id, relay_id)
        )
        if result.status == "sent":  # the listener ran before outbox_id was stored
            self._delivered(relay_id)
        log.info(
            "Relay %s from member %s to member %s (%s): %s",
            relay_id,
            sender.id,
            recipient.id,
            urgency,
            result.status,
        )
        return self.get(relay_id), result

    def said_back(self, recipient: Member, relay: Relay, result: OutboxResult) -> str:
        """What to tell whoever asked: when it goes, in plain words."""
        name = recipient.name
        if result.status == "sent":
            return f"Passed on to {name}."
        if result.status != "queued" or result.send_after is None or relay.urgency == "urgent":
            return f"I couldn't reach {name} just now; I'll keep trying."
        when = self._when(result.send_after)
        if relay.urgency == "today":
            _, deadline = timing("today", relay.created_at, self.timezone)
            if deadline is not None and result.send_after <= deadline:
                return (
                    f"I'll pass that on to {name} at a good moment today, by "
                    f"{clock_words(EARLY_EVENING)} at the latest."
                )
        return f"I'll pass that on to {name} at a good moment for them (likely {when})."

    def _when(self, moment: datetime) -> str:
        local = to_local(moment, self.timezone)
        today = to_local(clock.now(), self.timezone).date()
        if local.date() == today:
            day = "today"
        elif local.date() == today + timedelta(days=1):
            day = "tomorrow"
        else:
            day = f"{local:%a}"
        return f"{day} around {clock_words(local)}"

    def _same_note(self, sender: Member, recipient: Member, body: str) -> Relay | None:
        row = self.db.one(
            "SELECT * FROM liaison_items WHERE from_member_id = ? AND to_member_id = ? "
            "AND lower(body) = lower(?) AND (delivered_at IS NULL OR created_at >= ?) "
            "ORDER BY id DESC LIMIT 1",
            (sender.id, recipient.id, body, to_utc_iso(clock.now() - SAME_NOTE)),
        )
        return _relay(row) if row else None

    # ----- keeping track --------------------------------------------------------------

    def get(self, relay_id: int) -> Relay:
        row = self.db.one("SELECT * FROM liaison_items WHERE id = ?", (relay_id,))
        assert row is not None
        return _relay(row)

    def waiting_from(self, member: Member) -> list[Relay]:
        """Notes this person asked to pass on that haven't gone yet."""
        rows = self.db.query(
            "SELECT l.* FROM liaison_items l JOIN outbox o ON o.id = l.outbox_id "
            "WHERE l.from_member_id = ? AND l.delivered_at IS NULL AND o.status = 'queued' "
            "ORDER BY l.id",
            (member.id,),
        )
        return [_relay(r) for r in rows]

    def on_sent(self, row: dict[str, Any], message_id: int | None) -> None:
        """Outbox listener: a note went out."""
        if row["kind"] != KIND:
            return
        found = self.db.one("SELECT id FROM liaison_items WHERE outbox_id = ?", (row["id"],))
        if found is not None:
            self._delivered(found["id"])

    def _delivered(self, relay_id: int) -> None:
        self.db.execute(
            "UPDATE liaison_items SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL",
            (to_utc_iso(clock.now()), relay_id),
        )

    def open_items(self, member: Member) -> list[OpenItem]:
        items = []
        for relay in self.waiting_from(member):
            recipient = self.store.get_member(relay.to_member_id)
            latest = clock_words(EARLY_EVENING)
            by = f" (by {latest} at the latest)" if relay.urgency == "today" else ""
            items.append(
                OpenItem(f"A note for {recipient.name}, not passed on yet{by}: {relay.body[:80]}")
            )
        return items


def _liaison(ctx: ToolContext) -> Liaison:
    liaison = ctx.services.liaison
    assert liaison is not None
    return liaison


@tool(
    "relay_to_partner",
    "Pass a message on to another family member when someone asks ('tell my husband I'll be "
    "home late', 'let Erin know the dog's been fed', 'ask her if she wants takeout'). to: "
    "their name from the family list (for a nickname, the name the notes say it's for), or "
    "'partner'. message: the note as they'll read it, with the sender's facts and words "
    "('I'll be home late tonight'; a question stays a question: 'Do you want takeout "
    "tonight?'). urgency: 'urgent' only when they say it's urgent or it can't wait (goes "
    "now, even at night); 'today' when it matters today (goes by early evening); otherwise "
    "'whenever' (their next good moment). A job for the other person ('ask him to take the "
    "bins out') is create_task assigned to them, not this.",
    {
        "to": {"type": "string"},
        "message": {"type": "string"},
        "urgency": {"type": "string", "enum": list(URGENCIES)},
    },
)
async def relay_to_partner(ctx: ToolContext, args: dict[str, Any]) -> str:
    if not ASKS_TO_PASS_ON.search(ctx.request_text.replace("\u2019", "'")):
        raise ToolFailed(
            "Not passed on: their message doesn't ask Themi to pass anything on. Ask them "
            "whether they'd like it passed on."
        )
    liaison = _liaison(ctx)
    recipient = liaison.recipient(ctx.member, args["to"])
    relay, result = await liaison.relay(ctx.member, recipient, args["message"], args["urgency"])
    said = liaison.said_back(recipient, relay, result)
    ctx.replies.append(said)
    return f"{said} (note {relay.id})"
