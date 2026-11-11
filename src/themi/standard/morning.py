"""The morning message (MM1-MM4; the Themi Morning Message Plan).

One message starts the day, at the person's `morning_summary` time: a greeting, the date
and today's calendar events, nothing else, with up to four buttons for the rest:

    Good morning, Erin.
    Wed 21 Oct:
    - 10-11 am: Dentist (at Smile Dental)

    [Today's tasks] [Email]
    [Everything else] [Just one thing]

- It's one proactive message and counts once toward the daily limit. Its time is its
  deadline, so the daily limit and good windows don't hold it (bug #57's rule); quiet hours
  and a pause still do. It's built again as it goes, so it's true when it's read.
- The morning tray (MM2): from the start of the day until the morning message goes, the
  outbox holds proactive `normal` and `low` messages in a tray instead of sending them:
  task nudges in "tasks", email (approval cards from email, the email audit, inbox notes)
  in "email", the rest in "other". Never held: urgent messages and replies, reminders the
  person set for a time, a task nudge for a time today or a medicine, a message meant to go
  at once (its deadline as it was made), answers (praise, an update's result), questions
  to the family group.
- A tap is answered as a reply (sent now, not counted): Today's tasks sends the morning
  list (today's due tasks and any held nudges, a tick each); Email and Everything else send
  what waits in their tray, each brought up to date; Just one thing is `focus_now` with one.
  The message is then edited to drop that button. A button with nothing behind it isn't
  shown. A tap on an older day's message says so and answers with today's.
- Nothing tapped by noon: one message, with the same buttons for what still waits (or at
  5 pm when a busy time covers noon). It counts once; there's no other push. What's still in
  a tray after that waits for tomorrow's morning message.
- No morning message (the setting's off, or Themi was down past `SEND_WITHIN`): no tray;
  anything left in one goes back to the normal flow.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member, NotFound
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.localtime import free_from, to_utc_iso
from themi.standard.day_summary import DaySummary, DaySummaryPreferences
from themi.standard.tasks import TaskBoard

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

SEND_WITHIN = timedelta(hours=3)  # a morning missed by more than this (Themi was down) is skipped
TIMELY = timedelta(minutes=5)  # a deadline this close to when it was made: meant to go at once
RECAP_AT = time(12)
RECAP_BUSY_AT = time(17)  # when a busy time covers noon

KIND = "morning"
RECAP_KIND = "morning_recap"
TASKS, EMAIL, OTHER, ONE = "tasks", "email", "other", "one"
LABELS = {
    TASKS: "Today's tasks",
    EMAIL: "Email",
    OTHER: "Everything else",
    ONE: "Just one thing",
}
ORDER = (TASKS, EMAIL, OTHER, ONE)

TASK_KINDS = frozenset({"task", "task_summary"})
EMAIL_KINDS = frozenset({"email", "email_audit"})
# Never held: Themi's own morning messages, what the person set for a time, what answers
# them, and notices that are about this very moment.
NEVER_TRAYED = frozenset(
    {
        KIND,
        RECAP_KIND,
        "summary",
        "reminder",
        "routine",
        "break",
        "focus",
        "system",
        "slow_notice",
    }
)

GREETINGS = ("Good morning, {name}.", "Morning, {name}.")
NOTHING_ON_TEXT = "Nothing on the calendar today."
RECAP_TEXT = "A few things from this morning are still here, whenever you want them."
STALE_TEXT = "That one was from {day:%a %d %b}; here's today."
NO_TASKS_TEXT = "Nothing due today."
NO_EMAIL_TEXT = "Nothing waiting from email."
NO_OTHER_TEXT = "Nothing else waiting."


class MorningMessage:
    def __init__(self, services: Services, summary: DaySummary, board: TaskBoard) -> None:
        self.services = services
        self.summary = summary
        self.board = board
        self.db = services.store.db
        self.outbox = services.outbox

    def install(self) -> None:
        self.outbox.tray = self
        self.outbox.refreshers[KIND] = self._refresh
        self.services.button_handlers[KIND] = self.on_button

    # ----- whose mornings ------------------------------------------------------------------

    def _at(self, member: Member) -> time | None:
        return self.services.store.preferences(member.id, DaySummaryPreferences).morning_summary

    def morning_on(self, member: Member) -> bool:
        return member.reachable and self._at(member) is not None

    def _today(self) -> date:
        return clock.now().astimezone(self.summary._tz()).date()

    def _on(self, day: date, at: time) -> datetime:
        return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=self.summary._tz())

    def _record(self, member: Member, day: date) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM morning_summaries WHERE member_id = ? AND day = ?",
            (member.id, day.isoformat()),
        )

    def holding(self, member: Member, now: datetime) -> bool:
        """Whether the morning's messages wait in the tray for this person now: from the
        start of the day until their morning message has gone."""
        at = self._at(member)
        if at is None or not member.reachable:
            return False
        day = now.astimezone(self.summary._tz()).date()
        record = self._record(member, day)
        if record is None:
            return now < self._on(day, at) + SEND_WITHIN
        if record["outbox_id"] is None:
            return False  # nothing to say this morning, or too late: the usual flow
        status = self.db.scalar("SELECT status FROM outbox WHERE id = ?", (record["outbox_id"],))
        return status == "queued"

    # ----- the tray ------------------------------------------------------------------------

    def tray_for(self, member: Member, row: dict[str, Any], now: datetime) -> str | None:
        kind = row["kind"]
        if kind in NEVER_TRAYED or not self.holding(member, now):
            return None
        if (
            row["deadline"]
            and datetime.fromisoformat(row["deadline"])
            <= datetime.fromisoformat(row["created_at"]) + TIMELY
        ):
            return None  # meant to go at once (a timely approval, a bundle already made)
        if kind in TASK_KINDS:
            task_id = _task_id(row)
            if task_id is not None and self._audit_task(task_id):
                return EMAIL  # the email audit's nudge (E2)
            if task_id is not None and self._timed(task_id, now):
                return None
            return TASKS
        if kind in EMAIL_KINDS or (kind == "approval" and self._from_email(row["id"])):
            return EMAIL
        return OTHER

    def _audit_task(self, task_id: int) -> bool:
        return bool(self.db.one("SELECT 1 FROM email_audits WHERE task_id = ?", (task_id,)))

    def _timed(self, task_id: int, now: datetime) -> bool:
        """A medicine, or a task for a time today: its nudge goes at its time."""
        try:
            task = self.board.get(task_id)
        except NotFound:
            return False
        today = now.astimezone(self.summary._tz()).date()
        return task.medicine or (
            task.due_on == today and (task.due_time or task.from_time) is not None
        )

    def _from_email(self, outbox_id: int) -> bool:
        """An approval card staged from an email: one of an email thread's messages (F26b),
        or a single card for an email action."""
        if self.db.one("SELECT 1 FROM approval_groups WHERE outbox_id = ?", (outbox_id,)):
            return True
        return bool(
            self.db.one(
                "SELECT 1 FROM approval_messages m JOIN pending_actions a ON a.id = m.action_id "
                "WHERE m.outbox_id = ? AND (a.category LIKE 'email%' "
                "OR a.category = 'calendar_from_email')",
                (outbox_id,),
            )
        )

    # ----- the message ---------------------------------------------------------------------

    def text(self, member: Member, day: date) -> str:
        """The greeting, then the day's calendar (MM1), without the AI."""
        greeting = GREETINGS[day.toordinal() % len(GREETINGS)].format(name=member.name)
        events = self.summary.items(member, day, partner=True, tasks=False)
        if not events:
            return f"{greeting} {NOTHING_ON_TEXT}"
        lines = "\n".join(f"- {e}" for e in events)
        return f"{greeting}\n{day:%a %d %b}:\n{lines}"

    def has_events(self, member: Member, day: date) -> bool:
        return bool(self.summary.items(member, day, partner=True, tasks=False))

    def offers(self, member: Member, day: date, tapped: set[str] | None = None) -> list[str]:
        """The buttons with something behind them, in their order, less those tapped."""
        tapped = tapped or set()
        trays = {r["tray"] for r in self.outbox.trayed(member.id)}
        due = bool(self.summary.due(member, day))
        shown = {
            TASKS: due or TASKS in trays,
            EMAIL: EMAIL in trays,
            OTHER: OTHER in trays,
            ONE: due and self.services.maybe(keys.focus) is not None,
        }
        return [o for o in ORDER if shown[o] and o not in tapped]

    def buttons(self, offers: list[str], day: date) -> list[Button]:
        return [Button(LABELS[o], KIND, {"action": o, "day": day.isoformat()}) for o in offers]

    def _tapped(self, record: dict[str, Any] | None) -> set[str]:
        return {t for t in (record or {}).get("tapped", "").split(",") if t}

    def _refresh(self, member: Member, row: dict[str, Any]) -> tuple[str, list[Button]] | None:
        """As it goes: today's calendar and what's behind the buttons now. An older day's
        is dropped (it also expires)."""
        day = date.fromisoformat(_day(row))
        if day != self._today():
            return None
        offers = self.offers(member, day)
        if not offers and not self.has_events(member, day) and not self._empty_ok(member):
            return None
        return self.text(member, day), self.buttons(offers, day)

    def _empty_ok(self, member: Member) -> bool:
        return self.services.store.preferences(
            member.id, DaySummaryPreferences
        ).morning_summary_empty

    # ----- the scheduler jobs --------------------------------------------------------------

    async def morning(self) -> int:
        """Send each morning message that's due. Returns how many went (or were queued)."""
        tz = self.summary._tz()
        now = clock.now().astimezone(tz)
        today = now.date()
        sent = 0
        for member in self.services.store.list_members():
            at = self._at(member)
            if at is None or not member.reachable:
                self.outbox.untray(member.id)  # turned off with things held: the usual flow
                continue
            due_at = self._on(today, at)
            if now < due_at or self._record(member, today) is not None:
                continue
            self.db.execute(
                "INSERT INTO morning_summaries (member_id, day) VALUES (?, ?)",
                (member.id, today.isoformat()),
            )
            if now >= due_at + SEND_WITHIN:
                self.outbox.untray(member.id)  # Themi was down: nothing is lost, it all goes
                continue
            self.outbox.tray_waiting(member.id)
            offers = self.offers(member, today)
            if not offers and not self.has_events(member, today) and not self._empty_ok(member):
                continue
            result = await self.outbox.send(
                member,
                self.text(member, today),
                priority=Priority.NORMAL,
                kind=KIND,
                buttons=self.buttons(offers, today),
                dedupe_key=f"morning-{member.id}-{today.isoformat()}",
                deadline=due_at,  # the time they chose: the daily limit doesn't hold it (#57)
                expires=datetime(today.year, today.month, today.day, tzinfo=tz) + timedelta(days=1),
            )
            self.db.execute(
                "UPDATE morning_summaries SET outbox_id = ? WHERE member_id = ? AND day = ?",
                (result.outbox_id, member.id, today.isoformat()),
            )
            sent += 1
        return sent

    async def recap(self) -> int:
        """Noon (5 pm when a busy time covers noon): one message for what still waits from
        the morning, with its buttons. Once a day at most. Returns how many went."""
        tz = self.summary._tz()
        now = clock.now().astimezone(tz)
        today = now.date()
        sent = 0
        for member in self.services.store.list_members():
            if not self.morning_on(member):
                continue
            record = self._record(member, today)
            if record is None or record["outbox_id"] is None or record["recap_at"]:
                continue
            status = self.db.scalar(
                "SELECT status FROM outbox WHERE id = ?", (record["outbox_id"],)
            )
            noon = self._on(today, RECAP_AT)
            if status != "sent" or now < noon:
                continue
            if not self.outbox.trayed(member.id):
                self._recapped(member, today)  # all looked at: nothing to come back to
                continue
            when = noon
            if self._busy(member, noon):
                when = self._on(today, RECAP_BUSY_AT)
                if now < when:
                    continue
            offers = self.offers(member, today, self._tapped(record))
            self._recapped(member, today)
            if not offers:
                continue
            await self.outbox.send(
                member,
                RECAP_TEXT,
                priority=Priority.NORMAL,
                kind=RECAP_KIND,
                buttons=self.buttons(offers, today),
                dedupe_key=f"morning-recap-{member.id}-{today.isoformat()}",
                deadline=when,
                expires=datetime(today.year, today.month, today.day, tzinfo=tz) + timedelta(days=1),
            )
            sent += 1
        return sent

    def _busy(self, member: Member, moment: datetime) -> bool:
        source = self.outbox.calendar_blocks
        blocks = source(member, moment, moment + timedelta(hours=6)) if source else []
        return free_from(member, moment, str(self.summary._tz()), blocks) != moment

    def _recapped(self, member: Member, day: date) -> None:
        self.db.execute(
            "UPDATE morning_summaries SET recap_at = ? WHERE member_id = ? AND day = ?",
            (to_utc_iso(clock.now()), member.id, day.isoformat()),
        )

    # ----- the buttons ---------------------------------------------------------------------

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        member = self.services.store.get_member(event.member.id)
        action = str(event.button.payload.get("action"))
        day = date.fromisoformat(str(event.button.payload.get("day")))
        today = self._today()
        if day != today:
            await self.outbox.send(member, STALE_TEXT.format(day=day), priority=Priority.REPLY)
            await self._edit(member, event.button.message_id, [], day)
        else:
            tapped = self._tap(member, today, action)
            await self._edit(
                member, event.button.message_id, self.offers(member, today, tapped), today
            )
        if action == TASKS:
            await self._tasks(member, today)
        elif action == EMAIL:
            if not await self.outbox.release(member, EMAIL):
                await self.outbox.send(member, NO_EMAIL_TEXT, priority=Priority.REPLY)
        elif action == OTHER:
            if not await self.outbox.release(member, OTHER):
                await self.outbox.send(member, NO_OTHER_TEXT, priority=Priority.REPLY)
        elif action == ONE:
            focus = self.services.maybe(keys.focus)
            if focus is None:
                await self._tasks(member, today)
            else:
                await focus.send(member, count=1)

    def _tap(self, member: Member, day: date, action: str) -> set[str]:
        tapped = self._tapped(self._record(member, day)) | {action}
        self.db.execute(
            "UPDATE morning_summaries SET tapped = ? WHERE member_id = ? AND day = ?",
            (",".join(o for o in ORDER if o in tapped), member.id, day.isoformat()),
        )
        return tapped

    async def _edit(
        self, member: Member, message_id: int | None, offers: list[str], day: date
    ) -> None:
        """The tapped message again, without the button just tapped (or any, for an older
        day's): it shows what's been looked at."""
        if message_id is None:
            return
        row = self.db.one(
            "SELECT text FROM outbox WHERE member_id = ? AND telegram_message_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (member.id, message_id),
        )
        if row is None:
            return
        await self.outbox.edit(member, message_id, row["text"], self.buttons(offers, day))

    async def _tasks(self, member: Member, today: date) -> None:
        """Today's tasks, and any task nudge held this morning, as the morning list."""
        tasks = list(self.summary.due(member, today))
        seen = {t.id for t in tasks}
        for row in self.outbox.trayed(member.id, TASKS):
            task_id = _task_id(row)
            self.outbox.cancel(row["id"])  # the list is their nudge now
            if task_id is None or task_id in seen:
                continue
            try:
                task = self.board.get(task_id)
            except NotFound:
                continue
            if task.status == "open":
                seen.add(task.id)
                tasks.append(task)
        if not tasks:
            await self.outbox.send(member, NO_TASKS_TEXT, priority=Priority.REPLY)
            return
        await self.board.send_list(member, tasks)


def _task_id(row: dict[str, Any]) -> int | None:
    """The task a queued nudge is for, from its dedupe key ("task-12-ab12cd34")."""
    parts = str(row.get("dedupe_key") or "").split("-")
    return int(parts[1]) if len(parts) > 2 and parts[0] == "task" and parts[1].isdigit() else None


def _day(row: dict[str, Any]) -> str:
    """The day a morning message is for, from its dedupe key ("morning-3-2026-10-21")."""
    return str(row["dedupe_key"])[-10:]
