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
`liaison_items` and marked delivered when its message goes.

Alignment prompts (34b): when two expectations conflict (how full the feeders should be),
`flag_expectation_conflict` queues a short two-option question to the family group. It goes
only when everyone is free and predicted receptive at once (`Outbox.send(to_group=True)`).
Each person's tap is recorded (a change of mind counts until everyone has answered); when
they all pick the same, that choice is put forward as a household rule, to lock in with a
YES as any rule is. Different picks change nothing: it's theirs to talk over.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import OutboxResult, Priority
from themi.core import keys
from themi.core.prompts import OpenItem
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import in_quiet_hours, start_of_local_day, to_local, to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.prompt import PromptFragment
from themi.standard.tasks import clock_words

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

KIND = "relay"  # the outbox kind; the "notes" pause topic holds it
URGENCIES = ("urgent", "today", "whenever")
RANK = {"whenever": 0, "today": 1, "urgent": 2}
SEND_NOW = "relay_now"  # the button kind: a held note sent now (idea #156)
SEND_NOW_LABEL = "Send now"
HURRIED_TEXT = "Sent it to {name} now."
GONE_TEXT = "Passed on to {name}."
EARLY_EVENING = time(18, 0)  # a "today" note goes by then at the latest
SAME_NOTE = timedelta(minutes=30)  # the same note asked for again this soon: already done
MAX_BODY = 1000
ALIGNMENT = "alignment"  # the liaison kind, the outbox kind and the button kind
ALIGNMENT_WAIT = timedelta(days=7)  # a question that hasn't found a moment by then is dropped
MAX_OPTION = 60  # characters: it's a button label
QUESTION_TEXT = "A quick one for you both: {question}"
PICKED_TEXT = "{name} picked: {option}. Waiting on {waiting}."
AGREED_TEXT = "You both picked: {option}."
AGREED_ALL_TEXT = "You all picked: {option}."
RULE_TEXT = " I've put it forward as a household rule below; a YES locks it in."
DIFFERENT_TEXT = (
    "You picked differently ({picks}). Nothing changes for now; it's yours to talk over "
    "whenever suits."
)

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
    hurried: bool = False  # F29c: a note waiting to go, sent now when asked again sooner


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
        self.services.provide(keys.liaison, self)
        self.services.tools.register(relay_to_partner)
        self.services.tools.register(flag_expectation_conflict)
        self.services.button_handlers[ALIGNMENT] = self.on_alignment_button
        self.services.button_handlers[SEND_NOW] = self.on_send_now
        self.outbox.after_sent.append(self.after_sent)
        self.services.add_command(
            "/familygroup", self.on_family_group_command, "Set up the family group"
        )
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
        if not recipient.reachable:
            raise ToolFailed(
                f"Not passed on: {recipient.name} isn't connected to Themi on Telegram yet."
            )
        if (same := self._same_note(sender, recipient, body)) is not None:
            if same.delivered_at is None and RANK[urgency] > RANK[same.urgency]:
                # Bug #155: "Tell her urgently" after it was held for the morning
                hurried = await self.hurry(same, sender, recipient, urgency)
                if hurried is not None:
                    return hurried
            state = "already went" if self.get(same.id).delivered_at else "is already waiting to go"
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

    async def hurry(
        self,
        relay: Relay,
        sender: Member,
        recipient: Member,
        urgency: str,
        label: str | None = None,
    ) -> tuple[Relay, OutboxResult] | None:
        """A note still waiting goes sooner: its queued message is taken back and sent
        again at the new urgency (F29c). None if it went meanwhile. `label` is the urgency
        its words say, when that isn't the one it's sent with ("Send now", F31b)."""
        if relay.outbox_id is not None and not self.outbox.cancel(relay.outbox_id):
            self._delivered(relay.id)
            return None
        self.db.execute("UPDATE liaison_items SET urgency = ? WHERE id = ?", (urgency, relay.id))
        priority, deadline = timing(urgency, clock.now(), self.timezone)
        result = await self.outbox.send(
            recipient,
            delivery_text(sender, relay.body, label or urgency),
            priority=priority,
            kind=KIND,
            deadline=deadline,
            dedupe_key=f"relay:{relay.id}",
        )
        self.db.execute(
            "UPDATE liaison_items SET outbox_id = ? WHERE id = ?", (result.outbox_id, relay.id)
        )
        if result.status == "sent":
            self._delivered(relay.id)
        log.info("Relay %s sent sooner (%s): %s", relay.id, urgency, result.status)
        return replace(self.get(relay.id), hurried=True), result

    def held_because(self, recipient: Member) -> str | None:
        """Why a note for them waits, in a few words, when it's plain (F29c)."""
        now = clock.now()
        name = recipient.name
        if in_quiet_hours(recipient, now, self.timezone):
            return f"{name}'s in quiet hours until {clock_words(recipient.quiet_end)}"
        if self.outbox.sent_today(recipient.id, now) >= recipient.daily_limit:
            return f"{name} has had today's messages already"
        blocks = self.outbox.calendar_blocks
        if blocks is not None and blocks(recipient, now, now + timedelta(minutes=1)):
            return f"{name}'s busy right now"
        return None

    def can_send_now(self, recipient: Member) -> bool:
        """The button isn't offered in burnout mode, whose holds still apply (F22d)."""
        burnout = self.services.maybe(keys.burnout)
        return burnout is None or burnout.current(recipient) is None

    async def offer_send_now(self, sender: Member, relay: Relay, said: str) -> str:
        """The confirmation of a held note, with a "Send now" button (idea #156)."""
        result = await self.outbox.send(
            sender,
            said,
            priority=Priority.REPLY,
            buttons=[Button(SEND_NOW_LABEL, SEND_NOW, {"relay": relay.id})],
        )
        self.db.execute(
            "UPDATE liaison_items SET card_outbox_id = ? WHERE id = ?", (result.outbox_id, relay.id)
        )
        return said

    async def on_send_now(self, event: InboundEvent) -> None:
        assert event.button is not None
        row = self.db.one(
            "SELECT * FROM liaison_items WHERE id = ? AND kind = 'relay' AND from_member_id = ?",
            (int(event.button.payload.get("relay", 0)), event.member.id),
        )
        if row is None:
            return
        relay = _relay(row)
        recipient = self.store.get_member(relay.to_member_id)
        text = GONE_TEXT.format(name=recipient.name)
        if relay.delivered_at is None:
            hurried = await self.hurry(
                relay, event.member, recipient, "urgent", label=relay.urgency
            )
            if hurried is not None:
                text = HURRIED_TEXT.format(name=recipient.name)
        if event.button.message_id is not None:
            await self.outbox.edit(event.member, event.button.message_id, text)

    async def after_sent(self, row: dict[str, Any]) -> None:
        """A held note went: its confirmation loses the button."""
        if row["kind"] != KIND:
            return
        relay = self.db.one(
            "SELECT * FROM liaison_items WHERE outbox_id = ? AND card_outbox_id IS NOT NULL",
            (row["id"],),
        )
        if relay is None:
            return
        message_id = self.outbox.message_id(relay["card_outbox_id"])
        if message_id is not None:
            sender = self.store.get_member(relay["from_member_id"])
            recipient = self.store.get_member(relay["to_member_id"])
            await self.outbox.edit(sender, message_id, GONE_TEXT.format(name=recipient.name))
        self.db.execute(
            "UPDATE liaison_items SET card_outbox_id = NULL WHERE id = ?", (relay["id"],)
        )

    def said_back(self, recipient: Member, relay: Relay, result: OutboxResult) -> str:
        """What to tell whoever asked: when it goes, in plain words."""
        name = recipient.name
        if relay.hurried and result.status == "sent":
            return HURRIED_TEXT.format(name=name)
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
        why = self.held_because(recipient)
        if why is not None:  # F29c: said once, why it waits
            return f"I'll pass that on to {name} when I can: {why} (likely {when})."
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
            "WHERE l.from_member_id = ? AND l.kind = 'relay' AND l.delivered_at IS NULL "
            "AND o.status = 'queued' ORDER BY l.id",
            (member.id,),
        )
        return [_relay(r) for r in rows]

    def on_sent(self, row: dict[str, Any], message_id: int | None) -> None:
        """Outbox listener: a note went out."""
        if row["kind"] not in (KIND, ALIGNMENT):
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
        for row in self._alignments_waiting(member):
            items.append(
                OpenItem(
                    "A question for you both in the family group, not asked yet: "
                    + row["body"][:80]
                )
            )
        return items

    # ----- alignment prompts (34b) ------------------------------------------------------

    async def on_family_group_command(self, member: Member, argument: str) -> None:
        """/familygroup in someone's own chat: how to set the group up (the command itself
        works in the group, where the channel handles it)."""
        group = self.outbox.family_group.get()
        if group is not None:
            text = (
                f"The family group is linked{f' ({group.title})' if group.title else ''}. "
                "To change it, an admin sends /familygroup in the new group "
                "(or /familygroup off in the linked group to unlink it)."
            )
        else:
            text = (
                "To set up a family group: make a Telegram group with the family, add me to "
                "it, and "
                + (
                    "send /familygroup there."
                    if member.is_admin
                    else "ask an admin to send /familygroup there."
                )
            )
        await self.outbox.send(member, text, priority=Priority.REPLY)

    def _alignments_waiting(self, member: Member) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT l.* FROM liaison_items l JOIN outbox o ON o.id = l.outbox_id "
            "WHERE l.from_member_id = ? AND l.kind = 'alignment' AND l.delivered_at IS NULL "
            "AND o.status = 'queued' ORDER BY l.id",
            (member.id,),
        )

    async def flag_conflict(
        self, member: Member, topic: str, question: str, options: tuple[str, str]
    ) -> tuple[int, OutboxResult]:
        topic, question = topic.strip()[:120], question.strip()[:MAX_BODY]
        choices = tuple(o.strip()[:MAX_OPTION] for o in options)
        if not topic or not question:
            raise ToolFailed("Not asked: it needs a topic and a question.")
        if not all(choices) or choices[0].lower() == choices[1].lower():
            raise ToolFailed("Not asked: it needs two different options.")
        if self.outbox.family_group.chat_id() is None:
            raise ToolFailed(
                "Not asked: there's no family group yet. An admin can add the Themi bot to a "
                "Telegram group with the family and send /familygroup there."
            )
        if len(self.outbox.group_members()) < 2:
            raise ToolFailed("Not asked: only one person in the family uses Themi so far.")
        if self._open_alignment(topic) is not None:
            raise ToolDeclined(f"There's already a question for you both about {topic}.")
        now = clock.now()
        item_id = self.db.execute(
            "INSERT INTO liaison_items (kind, from_member_id, body, urgency, topic, options, "
            "created_at) VALUES ('alignment', ?, ?, 'whenever', ?, ?, ?)",
            (member.id, question, topic, json.dumps(choices), to_utc_iso(now)),
        )
        result = await self.outbox.send(
            member,
            QUESTION_TEXT.format(question=question),
            priority=Priority.NORMAL,
            kind=ALIGNMENT,
            buttons=[
                Button(choice, ALIGNMENT, {"item": item_id, "choice": i})
                for i, choice in enumerate(choices)
            ],
            dedupe_key=f"alignment:{item_id}",
            expires=now + ALIGNMENT_WAIT,
            to_group=True,
        )
        if result.status == "failed":
            self.db.execute("DELETE FROM liaison_items WHERE id = ?", (item_id,))
            raise ToolFailed("Not asked: the family group couldn't be reached.")
        self.db.execute(
            "UPDATE liaison_items SET outbox_id = ? WHERE id = ?", (result.outbox_id, item_id)
        )
        if result.status == "sent":
            self._delivered(item_id)
        log.info("Alignment question %s from member %s: %s", item_id, member.id, result.status)
        return item_id, result

    def _open_alignment(self, topic: str) -> dict[str, Any] | None:
        """An unsettled question on this topic (still waiting to go, or not answered yet)."""
        return self.db.one(
            "SELECT l.* FROM liaison_items l LEFT JOIN outbox o ON o.id = l.outbox_id "
            "WHERE l.kind = 'alignment' AND l.resolved_at IS NULL AND lower(l.topic) = lower(?) "
            "AND (o.status IS NULL OR o.status != 'failed') "
            "AND (l.delivered_at IS NOT NULL OR o.status = 'queued')",
            (topic,),
        )

    def alignment_said_back(self, result: OutboxResult) -> str:
        if result.status == "sent":
            return "I've asked you both in the family group."
        if result.send_after is not None:
            return (
                "I'll ask you both in the family group when it's a good moment for you both "
                f"(likely {self._when(result.send_after)})."
            )
        return "I'll ask you both in the family group when it's a good moment for you both."

    def answers(self, item_id: int) -> dict[int, int]:
        rows = self.db.query(
            "SELECT member_id, choice FROM alignment_answers WHERE item_id = ?", (item_id,)
        )
        return {r["member_id"]: r["choice"] for r in rows}

    async def on_alignment_button(self, event: InboundEvent) -> None:
        """Someone tapped an option on an alignment question in the group."""
        assert event.button is not None
        payload = event.button.payload
        item = self.db.one(
            "SELECT * FROM liaison_items WHERE id = ? AND kind = 'alignment'",
            (int(payload.get("item", 0)),),
        )
        if item is None or item["resolved_at"] is not None:
            return
        choice = int(payload.get("choice", 0))
        member = event.member
        self.db.execute(
            "INSERT INTO alignment_answers (item_id, member_id, choice, answered_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(item_id, member_id) DO UPDATE SET "
            "choice = excluded.choice, answered_at = excluded.answered_at",
            (item["id"], member.id, choice, to_utc_iso(clock.now())),
        )
        options: list[str] = json.loads(item["options"])
        everyone = self.outbox.group_members()
        answers = self.answers(item["id"])
        question = QUESTION_TEXT.format(question=item["body"])
        owner = self.store.get_member(item["from_member_id"])
        message_id = event.button.message_id
        waiting = [m for m in everyone if m.id not in answers]
        if waiting:
            picked = PICKED_TEXT.format(
                name=member.name,
                option=options[choice],
                waiting=" and ".join(m.name for m in waiting),
            )
            buttons = [
                Button(o, ALIGNMENT, {"item": item["id"], "choice": i})
                for i, o in enumerate(options)
            ]
            if message_id is not None:
                await self.outbox.edit(
                    owner,
                    message_id,
                    f"{question}\n\n{picked}",
                    buttons,
                    in_group=True,
                    anyone=True,
                )
            return
        picks = {answers[m.id] for m in everyone}
        now = to_utc_iso(clock.now())
        if len(picks) == 1:
            agreed = options[picks.pop()]
            words = (AGREED_TEXT if len(everyone) == 2 else AGREED_ALL_TEXT).format(option=agreed)
            rule_id = await self._propose_rule(member, item["topic"], agreed)
            self.db.execute(
                "UPDATE liaison_items SET resolved_at = ?, outcome = 'agreed', rule_id = ? "
                "WHERE id = ?",
                (now, rule_id, item["id"]),
            )
            if rule_id is not None:
                words += RULE_TEXT
        else:
            listed = "; ".join(f"{m.name}: {options[answers[m.id]]}" for m in everyone)
            words = DIFFERENT_TEXT.format(picks=listed)
            self.db.execute(
                "UPDATE liaison_items SET resolved_at = ?, outcome = 'different' WHERE id = ?",
                (now, item["id"]),
            )
        log.info("Alignment question %s settled", item["id"])
        if message_id is not None:
            await self.outbox.edit(owner, message_id, f"{question}\n\n{words}", in_group=True)

    async def _propose_rule(self, member: Member, topic: str, agreed: str) -> int | None:
        """The agreed choice as a household rule draft, its card to the person whose tap
        settled it (in the group, answering their tap), who can lock it in."""
        from themi.core.rules import RuleError

        rulebook = self.services.rulebook
        if rulebook is None:
            return None
        summary = f"{topic.rstrip('.?')}: {agreed}"
        text = f"{summary} (agreed by everyone in the family group)"
        try:
            rule = await rulebook.propose(member, summary, text, priority=Priority.REPLY)
        except RuleError as exc:
            log.info("An agreed alignment couldn't become a rule (%s)", exc)
            return None
        return rule.id


def _liaison(ctx: ToolContext) -> Liaison:
    liaison = ctx.services.maybe(keys.liaison)
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
    if result.status == "queued" and relay.urgency != "urgent" and liaison.can_send_now(recipient):
        ctx.cards.append(await liaison.offer_send_now(ctx.member, relay, said))
        return f"{said} They have a Send now button on that message. (note {relay.id})"
    ctx.replies.append(said)
    return f"{said} (note {relay.id})"


@tool(
    "flag_expectation_conflict",
    "When two family members' expectations about the same household thing conflict (one "
    "wants the feeders topped up when half empty, the other only when nearly empty), ask "
    "them both a short two-option question in the family group. It goes when it's a good "
    "moment for both. topic: what it settles, a few words ('How full the feeders should "
    "be'). question: one short, neutral line to both of them. option_a, option_b: the two "
    "choices, a few words each (button labels). Only for a real conflict between them, "
    "never to settle something one person can decide alone.",
    {
        "topic": {"type": "string"},
        "question": {"type": "string"},
        "option_a": {"type": "string"},
        "option_b": {"type": "string"},
    },
)
async def flag_expectation_conflict(ctx: ToolContext, args: dict[str, Any]) -> str:
    liaison = _liaison(ctx)
    item_id, result = await liaison.flag_conflict(
        ctx.member, args["topic"], args["question"], (args["option_a"], args["option_b"])
    )
    said = liaison.alignment_said_back(result)
    ctx.replies.append(said)
    return f"{said} (question {item_id})"


# CR8a: the system prompt's rules about this module's feature.
PROMPT_RULES = (
    PromptFragment(
        "liaison.when-someone-asks-how",
        "act",
        150,
        """\
- When someone asks how to deal with a household problem ("how can we stop losing the
  pacifiers?"), talk it through: offer two to four short ideas and let them pick, then ask
  whether any action would help (buying something, a task or routine, raising it with their
  partner) and do only what they agree to. Advice for the family is never a rule for Themi.
  When it's settled, keep a short summary with remember_fact.""",
    ),
    PromptFragment(
        "liaison.nicknames-are-household-notes",
        "act",
        170,
        """\
- Nicknames are household notes that say who calls whom ('Erin calls Michael "Hundo"'), so
  both partners' conversations know them; read a nickname from the speaker's side.""",
    ),
    PromptFragment(
        "liaison.asking-themi-to-have",
        "act",
        200,
        """\
- Asking Themi to have the other partner do something ("can you have my husband get the
  pacifier under the ottoman?", "ask him to take the bins out") is a task for them:
  create_task with assign_to their name, so it reaches them as a nudge.""",
    ),
    PromptFragment(
        "liaison.passing-a-message-on",
        "act",
        210,
        """\
- Passing a message on ("tell Hundo I love her", "let my husband know I'm running late",
  "ask Erin if she wants takeout") is relay_to_partner, never a note. Its reply says when
  it'll reach them; don't promise a time of your own.""",
    ),
)


class LiaisonModule(Module):
    """Passing notes between partners."""

    name = "liaison"
    title = "Passing notes"
    summary = "Passes a note from one partner to the other, at a good moment."

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*PROMPT_RULES)
        ctx.provide(Liaison(ctx.services)).install()
