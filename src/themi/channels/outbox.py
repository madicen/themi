"""The only way anything is sent to a person.

Priorities:
- `reply`: answers to something the person just said. Sent now, not counted.
- `urgent`: sent now, even in quiet hours (a tenant emergency, a missing bill).
- `normal`, `low`: Themi starting a conversation. These wait out quiet hours
  and busy times,
  respect the member's daily limit, and ask the receptivity provider whether
  now is a good moment. `low` is for things that can wait for a strong window
  (the energy engine tells them apart from prompt 19).

A `deadline` means "by then at the latest": once it passes, the receptivity
provider and daily limit stop holding the message back, but quiet hours
still do.

Messages are stored as written and shielded (PDA) at the moment they go out.
A failed send stays queued and is retried with backoff, so a Telegram outage
loses nothing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol

from themi import clock
from themi.accounts import AccountStore, Member
from themi.ai.types import CallKind
from themi.channels.events import Button
from themi.channels.pauses import PauseBook
from themi.channels.pda import PdaShield
from themi.localtime import (
    free_from,
    next_waking_start,
    start_of_local_day,
    to_utc_iso,
)

log = logging.getLogger(__name__)

RETRY_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)
# Someone is waiting on a reply, so it's tried again within seconds, and for longer.
REPLY_RETRY_BACKOFF = (
    timedelta(seconds=15),
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)
MAX_ATTEMPTS = 5
MAX_REPLY_ATTEMPTS = 8
DEDUPE_WINDOW = timedelta(hours=24)


class Priority(StrEnum):
    REPLY = "reply"
    URGENT = "urgent"
    NORMAL = "normal"
    LOW = "low"


PROACTIVE = (Priority.URGENT, Priority.NORMAL, Priority.LOW)
IMMEDIATE = (Priority.REPLY, Priority.URGENT)
_PRIORITY_ORDER = {Priority.REPLY: 0, Priority.URGENT: 1, Priority.NORMAL: 2, Priority.LOW: 3}


class Sender(Protocol):
    async def send_text(
        self,
        member: Member,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        kind: str = "chat",
        link_preview: bool = True,
    ) -> int: ...

    async def edit_text(
        self, member: Member, message_id: int, text: str, buttons: Sequence[Button] = ()
    ) -> None: ...


BlockSource = Callable[["Member", datetime, datetime], list[tuple[datetime, datetime]]]
# A feature's own hold on a kind of message: (member, when) -> hold until, or None.
Gate = Callable[["Member", datetime], datetime | None]
# A feature's order for its own kind of message when several are due at once (T1): a
# queued row -> a sort key, lower first.
Order = Callable[[dict[str, Any]], tuple[Any, ...]]


class ReceptivityProvider(Protocol):
    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        """The earliest good moment to reach `member` (return `now` when it's fine)."""
        ...


class AlwaysReceptive:
    """Until the energy engine exists (prompt 19): any time outside quiet hours is fine."""

    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        return now


@dataclass(frozen=True)
class OutboxResult:
    status: Literal["sent", "queued", "duplicate", "failed"]
    outbox_id: int | None
    message_id: int | None = None
    send_after: datetime | None = None


class Outbox:
    def __init__(
        self,
        store: AccountStore,
        sender: Sender,
        shield: PdaShield,
        receptivity: ReceptivityProvider | None = None,
        pauses: PauseBook | None = None,
    ) -> None:
        self.store = store
        self.sender = sender
        self.shield = shield
        self.receptivity = receptivity or AlwaysReceptive()
        self.pauses = pauses or PauseBook(store.db)
        # Called after each successful delivery with (outbox row, telegram message id).
        self.sent_listeners: list[Callable[[dict[str, Any], int | None], None]] = []
        # Busy events from someone's calendar (S2), which hold messages like busy times:
        # (member, start, end) -> [(starts, ends)]. None without Google.
        self.calendar_blocks: BlockSource | None = None
        # Rows on their way out, so a flush running meanwhile doesn't send them again.
        self._sending: set[int] = set()
        # Holds a feature puts on its own kind ("task": one nudge at a time, idea #11).
        self.gates: dict[str, Gate] = {}
        self.orders: dict[str, Order] = {}

    @property
    def _tz(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    # ----- sending ------------------------------------------------------------

    async def send(
        self,
        member: Member,
        text: str,
        *,
        priority: Priority,
        buttons: Sequence[Button] = (),
        kind: str = "chat",
        dedupe_key: str | None = None,
        deadline: datetime | None = None,
        link_preview: bool = True,
        not_before: datetime | None = None,
    ) -> OutboxResult:
        """`not_before` holds a proactive message until then at the earliest (replies and
        urgent messages never wait); after that, the usual timing rules apply."""
        now = clock.now()
        priority = Priority(priority)
        if dedupe_key and self._is_duplicate(member.id, dedupe_key, now):
            return OutboxResult("duplicate", None)
        when = self.send_time(
            member, priority, deadline=deadline, kind=kind, not_before=not_before, now=now
        )
        # A gate (one task nudge at a time) is checked again at every flush, not stored:
        # answering the nudge before it lets this one go at once.
        stored = self.send_time(
            member,
            priority,
            deadline=deadline,
            kind=kind,
            not_before=not_before,
            now=now,
            gated=False,
        )
        outbox_id = self.store.db.execute(
            "INSERT INTO outbox (member_id, text, buttons, priority, kind, dedupe_key, "
            "send_after, deadline, created_at, link_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                member.id,
                text,
                json.dumps([_button_json(b) for b in buttons]),
                priority.value,
                kind,
                dedupe_key,
                to_utc_iso(stored),
                to_utc_iso(deadline) if deadline else None,
                to_utc_iso(now),
                int(link_preview),
            ),
        )
        if when > now:
            log.info(
                "Queued %s message %s for member %s until %s",
                priority.value,
                outbox_id,
                member.id,
                when.isoformat(),
            )
            return OutboxResult("queued", outbox_id, send_after=when)
        return await self._deliver(self._row(outbox_id))

    def send_time(
        self,
        member: Member,
        priority: Priority,
        *,
        deadline: datetime | None = None,
        kind: str = "chat",
        not_before: datetime | None = None,
        now: datetime | None = None,
        gated: bool = True,
    ) -> datetime:
        """When a message queued now would go out, for wording that depends on the day."""
        now = now or clock.now()  # send() passes its own reading, so "now" is one moment
        priority = Priority(priority)
        start = now
        if not_before is not None and priority not in IMMEDIATE:
            start = max(now, not_before)
        return self._earliest(member, priority, start, deadline, kind, gated=gated)

    async def flush(self) -> int:
        """Send whatever is due. Returns how many went out. Run it from the scheduler."""
        now = clock.now()
        rows = self.store.db.query(
            "SELECT * FROM outbox WHERE status = 'queued' AND send_after <= ?",
            (to_utc_iso(now),),
        )
        rows.sort(key=lambda r: (_PRIORITY_ORDER[Priority(r["priority"])], r["id"]))
        rows = self._in_their_order(rows)
        sent = 0
        for row in rows:
            if row["id"] in self._sending:
                continue
            member = self.store.get_member(row["member_id"])
            deadline = datetime.fromisoformat(row["deadline"]) if row["deadline"] else None
            priority = Priority(row["priority"])
            when = self._earliest(member, priority, now, deadline, row["kind"], gated=False)
            if when > now:
                self.store.db.execute(
                    "UPDATE outbox SET send_after = ? WHERE id = ?", (to_utc_iso(when), row["id"])
                )
                continue
            if self._gated(member, row["kind"], now, priority):
                continue  # waits its turn; looked at again next flush
            if (await self._deliver(row)).status == "sent":
                sent += 1
        return sent

    def _in_their_order(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rows of a kind with its own order (task nudges: urgent and important first) are
        put in that order among the places they hold; everything else stays put."""
        for kind, order in self.orders.items():
            places = [i for i, r in enumerate(rows) if r["kind"] == kind]
            ordered = sorted(
                (rows[i] for i in places),
                key=lambda r: (_PRIORITY_ORDER[Priority(r["priority"])], order(r), r["id"]),
            )
            for i, row in zip(places, ordered, strict=True):
                rows[i] = row
        return rows

    async def _deliver(self, row: dict[str, Any]) -> OutboxResult:
        if row["id"] in self._sending:
            return OutboxResult("queued", row["id"])
        self._sending.add(row["id"])
        try:
            return await self._deliver_now(row)
        finally:
            self._sending.discard(row["id"])

    async def _deliver_now(self, row: dict[str, Any]) -> OutboxResult:
        member = self.store.get_member(row["member_id"])
        buttons = tuple(_button_from_json(b) for b in json.loads(row["buttons"]))
        priority = Priority(row["priority"])
        kind = CallKind.INTERACTIVE if priority in IMMEDIATE else CallKind.BACKGROUND
        try:
            shielded = await self.shield.apply(row["text"], member, buttons=buttons, kind=kind)
            message_id = await self.sender.send_text(
                member,
                shielded.text,
                shielded.buttons,
                kind=row["kind"],
                link_preview=bool(row["link_preview"]),
            )
        except Exception as exc:
            return self._record_failure(row, exc)
        self.store.db.execute(
            "UPDATE outbox SET status = 'sent', sent_at = ?, sent_text = ?, "
            "telegram_message_id = ?, attempts = attempts + 1 WHERE id = ?",
            (to_utc_iso(clock.now()), shielded.text, message_id, row["id"]),
        )
        for listener in self.sent_listeners:
            try:
                listener(row, message_id)
            except Exception:
                log.exception("An outbox sent-listener failed for message %s", row["id"])
        return OutboxResult("sent", row["id"], message_id)

    async def edit(
        self, member: Member, message_id: int, text: str, buttons: Sequence[Button] = ()
    ) -> bool:
        """Change a message already sent (e.g. to show an approval's result).

        Edits are shielded like any message. A failed edit is logged and
        reported as False; it's never worth retrying.
        """
        try:
            shielded = await self.shield.apply(text, member, buttons=buttons)
            await self.sender.edit_text(member, message_id, shielded.text, shielded.buttons)
        except Exception as exc:
            log.info("Couldn't edit message %s (%s)", message_id, type(exc).__name__)
            return False
        return True

    def cancel(self, outbox_id: int) -> bool:
        """Withdraw a message that hasn't gone out yet. False if it already went."""
        return bool(
            self.store.db.update(
                "DELETE FROM outbox WHERE id = ? AND status = 'queued'", (outbox_id,)
            )
        )

    def message_id(self, outbox_id: int) -> int | None:
        """The Telegram message id of a sent outbox message (None if not sent yet)."""
        row = self.store.db.one(
            "SELECT telegram_message_id FROM outbox WHERE id = ? AND status = 'sent'",
            (outbox_id,),
        )
        return row["telegram_message_id"] if row else None

    def _record_failure(self, row: dict[str, Any], exc: Exception) -> OutboxResult:
        attempts = row["attempts"] + 1
        reply = Priority(row["priority"]) == Priority.REPLY
        backoff = REPLY_RETRY_BACKOFF if reply else RETRY_BACKOFF
        if attempts >= (MAX_REPLY_ATTEMPTS if reply else MAX_ATTEMPTS):
            log.error(
                "Giving up on outbox message %s after %d attempts (%s)",
                row["id"],
                attempts,
                type(exc).__name__,
            )
            self.store.db.execute(
                "UPDATE outbox SET status = 'failed', attempts = ?, last_error = ? WHERE id = ?",
                (attempts, type(exc).__name__, row["id"]),
            )
            return OutboxResult("failed", row["id"])
        retry_at = clock.now() + backoff[min(attempts - 1, len(backoff) - 1)]
        log.warning(
            "Sending outbox message %s failed (%s); retrying at %s",
            row["id"],
            type(exc).__name__,
            retry_at.isoformat(),
        )
        self.store.db.execute(
            "UPDATE outbox SET attempts = ?, last_error = ?, send_after = ? WHERE id = ?",
            (attempts, type(exc).__name__, to_utc_iso(retry_at), row["id"]),
        )
        return OutboxResult("queued", row["id"], send_after=retry_at)

    # ----- timing -------------------------------------------------------------

    def _earliest(
        self,
        member: Member,
        priority: Priority,
        now: datetime,
        deadline: datetime | None,
        kind: str = "chat",
        *,
        gated: bool = True,
    ) -> datetime:
        if priority in IMMEDIATE:
            return now
        tz = self._tz
        overdue = deadline is not None and deadline <= now
        blocks = (
            self.calendar_blocks(member, now, now + timedelta(days=8))
            if self.calendar_blocks
            else []
        )
        when = free_from(member, now, tz, blocks)
        if not overdue and self.sent_today(member.id, now) >= member.daily_limit:
            when = max(when, next_waking_start(member, now, tz))
        if not overdue:
            when = max(when, self.receptivity.not_before(member, priority, when))
            if deadline is not None and when > deadline:
                when = max(deadline, now)
        held = self.pauses.held_until(member, kind)  # the person asked: outranks a deadline
        if held is not None:
            when = max(when, held)
        if gated:
            gate = self.gates.get(kind)
            until = gate(member, when) if gate is not None else None
            if until is not None:
                when = max(when, until)
        # Whatever was chosen, it can't land inside quiet hours or a busy time.
        return free_from(member, when, tz, blocks)

    def _gated(self, member: Member, kind: str, now: datetime, priority: Priority) -> bool:
        if priority in IMMEDIATE:
            return False
        gate = self.gates.get(kind)
        until = gate(member, now) if gate is not None else None
        return until is not None and until > now

    def release_held(self, member: Member) -> int:
        """After a pause ends early, let held messages be reconsidered at the next flush."""
        return self.store.db.update(
            "UPDATE outbox SET send_after = ? WHERE member_id = ? AND status = 'queued' "
            "AND send_after > ? AND attempts = 0",
            (to_utc_iso(clock.now()), member.id, to_utc_iso(clock.now())),
        )

    def sent_today(self, member_id: int, now: datetime | None = None) -> int:
        """Proactive messages already sent to the member since local midnight."""
        midnight = start_of_local_day(now or clock.now(), self._tz)
        return self.store.db.scalar(
            "SELECT COUNT(*) FROM outbox WHERE member_id = ? AND status = 'sent' "
            "AND priority IN ('urgent', 'normal', 'low') AND sent_at >= ?",
            (member_id, to_utc_iso(midnight)),
        )

    def _is_duplicate(self, member_id: int, key: str, now: datetime) -> bool:
        return bool(
            self.store.db.one(
                "SELECT 1 FROM outbox WHERE member_id = ? AND dedupe_key = ? AND "
                "(status = 'queued' OR (status = 'sent' AND sent_at >= ?))",
                (member_id, key, to_utc_iso(now - DEDUPE_WINDOW)),
            )
        )

    # ----- inspection ---------------------------------------------------------

    def _row(self, outbox_id: int) -> dict[str, Any]:
        row = self.store.db.one("SELECT * FROM outbox WHERE id = ?", (outbox_id,))
        assert row is not None
        return row

    def queued(self, member_id: int) -> list[dict[str, Any]]:
        return self.store.db.query(
            "SELECT * FROM outbox WHERE member_id = ? AND status = 'queued' ORDER BY send_after",
            (member_id,),
        )


def _button_json(button: Button) -> dict[str, Any]:
    return {"label": button.label, "kind": button.kind, "payload": button.payload}


def _button_from_json(data: dict[str, Any]) -> Button:
    return Button(data["label"], data["kind"], data.get("payload") or {})
