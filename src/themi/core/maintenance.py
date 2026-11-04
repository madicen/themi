"""Seasonal and long-term maintenance (33): filter changes, gutters, fertilizing the trees.

Each item keeps its interval in days, its active months, a step-by-step guide and a
history of past runs with notes. It's due its interval after it was last done (or on its
first due date), and only in its active months: one due out of season waits for the
season's first day.

The offer (the `maintenance.offer` job, every 15 minutes): at most one new item a day for
the household, and only while the person it's for is in a good window (receptive or
better, and not in quiet hours or a busy time). It's for the item's owner, or whoever has
the most room right now. It becomes an effort-2 hands-on task with the guide as its
steps, nudged as the outbox kind `maintenance` ("/pause maintenance" holds it) with Done
and Later; Later asks again the next day. While one offer is open, no other is made,
unless it's sat a week. Done (the button, chat, the wall) records a run; the
`log_maintenance` tool records one with notes, done or not offered yet. Taken off the list
(cancelled), the item waits a week.

Due dates go on the family calendar (26): an item's next due date is an all-day event,
staged once as `calendar_write`; that yes covers moving it along each time it's done, and
removing it with the item.

Managed in chat (set_maintenance, remove_maintenance, get_maintenance_guide,
log_maintenance) and on the website's Maintenance page. All of it is the household's own
record inside Themi, so only the calendar goes through the trust tiers.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button
from themi.channels.outbox import Priority
from themi.connectors.gcal import CalendarSync, event_id
from themi.core.events import title_matches
from themi.core.groceries import and_list
from themi.core.lists import name_key
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard, TaskChange, clean_steps, day_arg
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.energy.matching import Assignment
from themi.energy.model import SOURCE_INPUT
from themi.energy.windows import RECEPTIVE, Projection
from themi.localtime import to_utc_iso
from themi.scheduler import Scheduler

log = logging.getLogger(__name__)

MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip
ALL_YEAR = "All year"
KIND = "maintenance"  # the outbox kind: "/pause maintenance" holds these
TASK_KIND, EFFORT = "physical", 2
LATER_FOR = 24 * 60  # minutes: Later on a maintenance nudge asks again the next day
STALE_AFTER = timedelta(days=7)  # an offer open this long no longer holds the others back
SKIP_DAYS = 7  # taken off the list: not offered again for a week
MAX_INTERVAL = 3650
LEAD = "Maintenance: {name} ({every}; {last})"
ASK = "Done already, or later?"
NOTE_TEXT = "Last time ({on}): {notes}"
CATEGORY = "calendar_write"  # the family calendar's category (26)
EXECUTOR = "maintenance.calendar_write"
JOB = "maintenance.calendar"
OPEN = ("pending", "snoozed", "failed")


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    interval_days: int
    active_months: tuple[int, ...]  # 1-12; empty: all year
    guide: tuple[str, ...]
    owner: int | None  # None: whoever has room
    first_due: date
    task_id: int | None
    offered_at: datetime | None
    skip_until: date | None
    created_by: int | None


@dataclass(frozen=True)
class Run:
    id: int
    done_on: date
    done_by: int | None
    notes: str | None


def _item(row: dict[str, Any]) -> Item:
    return Item(
        row["id"],
        row["name"],
        row["interval_days"],
        tuple(json.loads(row["active_months"])),
        tuple(json.loads(row["guide"])),
        row["owner"],
        date.fromisoformat(row["first_due"]),
        row["task_id"],
        datetime.fromisoformat(row["offered_at"]) if row["offered_at"] else None,
        date.fromisoformat(row["skip_until"]) if row["skip_until"] else None,
        row["created_by"],
    )


def _run(row: dict[str, Any]) -> Run:
    return Run(row["id"], date.fromisoformat(row["done_on"]), row["done_by"], row["notes"])


# ----- when it's due -----------------------------------------------------------------


def in_season(day: date, months: Sequence[int]) -> date:
    """`day`, or the first day of the next active month after it."""
    if not months or day.month in months:
        return day
    year, month = day.year, day.month
    for _ in range(12):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        if month in months:
            return date(year, month, 1)
    return day  # unreachable: months are 1-12


def due_on(item: Item, last_done: date | None, today: date) -> date:
    """The day it's next due: its interval after it was last done (or its first due date),
    in its active months. Overdue as the season ends, it waits for the next one."""
    due = last_done + timedelta(days=item.interval_days) if last_done else item.first_due
    if due < today and item.active_months and today.month not in item.active_months:
        due = today
    return in_season(due, item.active_months)


def every_words(days: int) -> str:
    if days == 1:
        return "every day"
    if days in (365, 366):
        return "once a year"
    if days % 7 == 0 and days <= 56:
        return "every week" if days == 7 else f"every {days // 7} weeks"
    return f"every {days} days"


def months_words(months: Sequence[int]) -> str:
    """ "all year", "March to October", or "March, June and September"."""
    chosen = sorted(set(months))
    if not chosen or len(chosen) == 12:
        return "all year"
    # A run that may wrap the year's end (November to February) reads as one span.
    for start in chosen:
        span = [(start - 1 + i) % 12 + 1 for i in range(len(chosen))]
        if sorted(span) == chosen and len(chosen) > 2:
            return f"{MONTHS[span[0] - 1]} to {MONTHS[span[-1] - 1]}"
    return and_list([MONTHS[m - 1] for m in chosen])


def month_numbers(names: Sequence[str]) -> tuple[int, ...]:
    numbers: set[int] = set()
    for name in names:
        said = str(name).strip().lower()
        if said == ALL_YEAR.lower():
            return ()
        found = [i + 1 for i, m in enumerate(MONTHS) if m.lower().startswith(said[:3])]
        if len(said) < 3 or not found:
            raise ValueError(f"{name} isn't a month")
        numbers.add(found[0])
    return tuple(sorted(numbers)) if len(numbers) < 12 else ()


def _day_words(day: date, today: date) -> str:
    if day == today:
        return "today"
    if day == today + timedelta(days=1):
        return "tomorrow"
    return f"{day:%a %-d %b}" if day.year == today.year else f"{day:%a %-d %b %Y}"


class Maintenance:
    def __init__(
        self,
        services: Services,
        board: TaskBoard,
        sync: CalendarSync | None = None,
        jobs: Scheduler | None = None,
    ) -> None:
        self.services = services
        self.board = board
        self.sync = sync
        self.jobs = jobs
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.maintenance = self
        for each in (set_maintenance, remove_maintenance, get_maintenance_guide,
                     log_maintenance):  # fmt: skip
            self.services.tools.register(each)
        self.board.own_nudges.append(self._nudge)
        self.board.done_hooks.append(self._task_done)
        self.board.change_listeners.append(self._task_changed)
        if self.sync is not None and self.jobs is not None:
            self.services.autonomy.executors.register(EXECUTOR)(self._execute)
            self.jobs.handler(JOB)(self.run_job)

    # ----- reading --------------------------------------------------------------------

    def today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def items(self) -> list[Item]:
        return [_item(r) for r in self.db.query("SELECT * FROM maintenance_items ORDER BY id")]

    def get(self, item_id: int) -> Item | None:
        row = self.db.one("SELECT * FROM maintenance_items WHERE id = ?", (item_id,))
        return _item(row) if row else None

    def find(self, said: str) -> Item | None:
        """By name: the same words, else every word they used in its name."""
        key = name_key(said)
        items = self.items()
        same = [i for i in items if name_key(i.name) == key]
        if same:
            return same[0]
        matching = [i for i in items if title_matches(said, i.name)]
        return matching[0] if len(matching) == 1 else None

    def runs(self, item: Item, limit: int = 5) -> list[Run]:
        rows = self.db.query(
            "SELECT * FROM maintenance_runs WHERE item_id = ? ORDER BY done_on DESC, id DESC "
            "LIMIT ?",
            (item.id, limit),
        )
        return [_run(r) for r in rows]

    def last_done(self, item: Item) -> date | None:
        last = self.db.scalar(
            "SELECT MAX(done_on) FROM maintenance_runs WHERE item_id = ?", (item.id,)
        )
        return date.fromisoformat(last) if last else None

    def next_due(self, item: Item, today: date | None = None) -> date:
        return due_on(item, self.last_done(item), today or self.today())

    def describe(self, item: Item) -> str:
        """One line: "Change the furnace filter: every 90 days, all year; next due Thu 5
        Feb; last done Fri 7 Nov"."""
        today = self.today()
        last = self.last_done(item)
        parts = [
            f"{every_words(item.interval_days)}, {months_words(item.active_months)}",
            f"next due {_day_words(self.next_due(item, today), today)}",
            f"last done {_day_words(last, today)}" if last else "not done here yet",
        ]
        if item.owner is not None:
            parts.append(f"{self.store.get_member(item.owner).name} looks after it")
        if self.open_task(item) is not None:
            parts.append("offered and still open")
        return f"{item.name}: {'; '.join(parts)}"

    def guide_words(self, item: Item) -> str:
        """For get_maintenance_guide: the line, the steps and the notes from past runs."""
        lines = [self.describe(item) + "."]
        if item.guide:
            lines += ["Steps:", *(f"{n}. {step}" for n, step in enumerate(item.guide, 1))]
        else:
            lines.append("No steps written down yet.")
        noted = [r for r in self.runs(item) if r.notes]
        if noted:
            lines.append("Notes from past runs:")
            lines += [f"- {r.done_on:%-d %b %Y}: {r.notes}" for r in noted]
        return "\n".join(lines)

    # ----- changing ---------------------------------------------------------------------

    async def set(
        self,
        by: Member,
        name: str,
        *,
        interval_days: int | None = None,
        months: Sequence[int] | None = None,
        guide: Sequence[str] | None = None,
        owner: Member | bool | None = False,  # False: as it is (a new one: whoever has room)
        last_done: date | None = None,
        new_name: str = "",
        interactive: bool = False,
    ) -> tuple[Item, bool]:
        """Add an item, or change one found by `name`. Raises ValueError for bad values."""
        name = " ".join(name.split()).strip().rstrip(".")
        if not name:
            raise ValueError("a maintenance item needs a name")
        if interval_days is not None and not 1 <= interval_days <= MAX_INTERVAL:
            raise ValueError(f"the interval is 1 to {MAX_INTERVAL} days")
        found = self.find(name)
        steps = json.dumps(clean_steps(guide)) if guide is not None else None
        if found is None:
            if interval_days is None:
                raise ValueError("a new maintenance item needs its interval in days")
            item_id = self.db.execute(
                "INSERT INTO maintenance_items (name, interval_days, active_months, guide, "
                "owner, first_due, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    interval_days,
                    json.dumps(list(months or ())),
                    steps or "[]",
                    owner.id if isinstance(owner, Member) else None,
                    self.today().isoformat(),
                    by.id,
                    to_utc_iso(clock.now()),
                ),
            )
        else:
            item_id = found.id
            changes: dict[str, Any] = {}
            if new_name.strip():
                changes["name"] = " ".join(new_name.split()).rstrip(".")
            if interval_days is not None:
                changes["interval_days"] = interval_days
            if months is not None:
                changes["active_months"] = json.dumps(list(months))
            if steps is not None:
                changes["guide"] = steps
            if owner is not False:
                changes["owner"] = owner.id if isinstance(owner, Member) else None
            if changes:
                assignments = ", ".join(f"{c} = :{c}" for c in changes)
                self.db.execute(
                    f"UPDATE maintenance_items SET {assignments} WHERE id = :id",
                    {**changes, "id": item_id},
                )
        item = self.get(item_id)
        assert item is not None
        if last_done is not None and last_done != self.last_done(item):
            self._record(item, None, last_done, None, None)
        await self.on_calendar(item, by, interactive=interactive)
        return item, found is None

    async def remove(self, item: Item, by: Member) -> None:
        task = self.open_task(item)
        if task is not None:
            await self.board.cancel(task.id, by)
        self.db.execute("DELETE FROM maintenance_items WHERE id = ?", (item.id,))
        self._queue(item.id)  # its calendar event goes too

    async def log(
        self, item: Item, by: Member, on: date, notes: str = "", *, interactive: bool = False
    ) -> str:
        """Done on `on`, with what they noted. Done again the same day only adds the notes.
        An open offer of it is done too."""
        notes = " ".join(notes.split())[:500]
        last = self.runs(item, 1)
        if last and last[0].done_on == on:
            if notes:
                joined = f"{last[0].notes} {notes}" if last[0].notes else notes
                self.db.execute(
                    "UPDATE maintenance_runs SET notes = ? WHERE id = ?", (joined, last[0].id)
                )
                return f"Added that to the notes for {item.name}."
            return f"{item.name} was already down as done that day."
        task = self.open_task(item)
        self._record(item, by, on, notes or None, task.id if task else None)
        if task is not None:
            await self.board.complete(task.id, by, interactive=interactive)
        self._settled(item)
        await self.on_calendar(item, by, interactive=interactive)
        fresh = self.get(item.id)
        assert fresh is not None
        today = self.today()
        return (
            f"Noted {item.name} as done{' with your notes' if notes else ''}. Next due "
            f"{_day_words(self.next_due(fresh, today), today)}."
        )

    def _record(
        self, item: Item, by: Member | None, on: date, notes: str | None, task_id: int | None
    ) -> None:
        self.db.execute(
            "INSERT INTO maintenance_runs (item_id, done_on, done_by, notes, task_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.id,
                on.isoformat(),
                by.id if by else None,
                notes,
                task_id,
                to_utc_iso(clock.now()),
            ),
        )

    def _settled(self, item: Item) -> None:
        self.db.execute(
            "UPDATE maintenance_items SET task_id = NULL, skip_until = NULL WHERE id = ?",
            (item.id,),
        )

    # ----- the offer ----------------------------------------------------------------------

    def due(self, today: date | None = None) -> list[Item]:
        """Due now, in season, not put off and not already offered, soonest due first."""
        today = today or self.today()
        found = []
        for item in self.items():
            if self.open_task(item) is not None:
                continue
            if item.skip_until is not None and item.skip_until > today:
                continue
            if self.next_due(item, today) <= today:
                found.append(item)
        return sorted(found, key=lambda i: (self.next_due(i, today), i.id))

    async def offer(self) -> int:
        """Scheduler job: offer one due item, at most one a day, in a good window. Returns
        how many were offered (0 or 1)."""
        today = self.today()
        now = clock.now()
        if self._offered_today(today) or self._waiting_on_one(now):
            return 0
        for item in self.due(today):
            assignment = self._who(item, now)
            if assignment is None:
                continue  # theirs, and not a good moment for them (or resting)
            await self._offer(item, assignment)
            return 1
        return 0

    def _who(self, item: Item, now: datetime) -> Assignment | None:
        if item.owner is not None:
            owner = self.store.get_member(item.owner)
            assignment = Assignment(owner, owner, f"{owner.name} looks after it.")
        else:
            assignment = self.board.matcher.roomiest(TASK_KIND, EFFORT, now)
        member = assignment.assignee
        burnout = self.services.burnout
        if burnout is not None and burnout.current(member) is not None:
            return None
        return assignment if self.in_window(member, now) else None

    def in_window(self, member: Member, now: datetime) -> bool:
        """A good window right now: receptive or better, outside quiet hours and busy times.
        Someone with every energy input off is never held back, as with the outbox."""
        member = self.store.get_member(member.id)
        if not any(member.tracks(toggle) for toggle in SOURCE_INPUT.values()):
            return True
        projection = Projection(self.board.matcher.model, member, now)
        return not projection.quiet(now) and projection.at(now) >= RECEPTIVE

    async def _offer(self, item: Item, assignment: Assignment) -> None:
        member = assignment.assignee
        task = await self.board.create(
            member,  # theirs to do: nobody "added this for" them
            item.name,
            TASK_KIND,
            EFFORT,
            nudge=False,
            steps=item.guide,
            assignment=assignment,
        )
        self.db.execute(
            "UPDATE maintenance_items SET task_id = ?, offered_at = ?, skip_until = NULL "
            "WHERE id = ?",
            (task.id, to_utc_iso(clock.now()), item.id),
        )
        await self.board.prompt(task)  # now it's known as the item's: its own nudge
        log.info("Offered maintenance item %s to member %s", item.id, member.id)

    def _offered_today(self, today: date) -> bool:
        tz = self._tz()
        start = datetime(today.year, today.month, today.day, tzinfo=tz)
        return bool(
            self.db.one(
                "SELECT 1 FROM maintenance_items WHERE offered_at >= ?", (to_utc_iso(start),)
            )
        )

    def _waiting_on_one(self, now: datetime) -> bool:
        """An offer still open, made within the week: one at a time."""
        cutoff = now - STALE_AFTER
        return any(
            item.offered_at is not None
            and item.offered_at > cutoff
            and self.open_task(item) is not None
            for item in self.items()
        )

    def open_task(self, item: Item) -> Task | None:
        if item.task_id is None:
            return None
        task = self.board.get(item.task_id)
        return task if task.status in ("open", "snoozed") else None

    def _by_task(self, task_id: int) -> Item | None:
        row = self.db.one("SELECT * FROM maintenance_items WHERE task_id = ?", (task_id,))
        return _item(row) if row else None

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        item = self._by_task(task.id)
        if item is None:
            return False
        today = self.today()
        last = self.last_done(item)
        lead = LEAD.format(
            name=item.name,
            every=every_words(item.interval_days),
            last=f"last done {_day_words(last, today)}" if last else "not done here before",
        )
        parts = [lead + "."]
        if item.guide:
            parts.append("\n".join(f"> - {step}" for step in item.guide))  # kept word for word
        noted = next((r for r in self.runs(item) if r.notes), None)
        if noted is not None:
            parts.append(NOTE_TEXT.format(on=f"{noted.done_on:%-d %b %Y}", notes=noted.notes))
        parts.append(ASK)
        self.board.withdraw_prompt(task)  # one nudge for it waiting at a time
        result = await self.services.outbox.send(
            member,
            "\n\n".join(parts),
            priority=Priority.NORMAL,
            kind=KIND,
            buttons=[
                Button("Done", "task", {"task": task.id, "action": "done"}),
                Button("Later", "task", {"task": task.id, "action": "later", "minutes": LATER_FOR}),
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

    async def _task_done(self, task: Task, by: Member, interactive: bool) -> None:
        """Done from its nudge, in chat or on the wall: a run, unless log() wrote it."""
        item = self._by_task(task.id)
        if item is None:
            return
        if not self.db.one("SELECT 1 FROM maintenance_runs WHERE task_id = ?", (task.id,)):
            self._record(item, by, self.today(), None, task.id)
        self._settled(item)
        await self.on_calendar(item, by, interactive=interactive)

    async def _task_changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        """Taken off the list: not this time. It's offered again in a week."""
        if change != "cancelled":
            return
        item = self._by_task(task.id)
        if item is None:
            return
        self.db.execute(
            "UPDATE maintenance_items SET task_id = NULL, skip_until = ? WHERE id = ?",
            ((self.today() + timedelta(days=SKIP_DAYS)).isoformat(), item.id),
        )

    # ----- the family calendar ------------------------------------------------------------

    def _event(self, item_id: int) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM calendar_events WHERE source = 'maintenance' AND source_id = ?",
            (item_id,),
        )

    def _waiting(self, item_id: int) -> bool:
        rows = self.db.query(
            f"SELECT payload FROM pending_actions WHERE category = ? AND executor = ? "
            f"AND status IN ({', '.join('?' for _ in OPEN)})",
            (CATEGORY, EXECUTOR, *OPEN),
        )
        return any(json.loads(r["payload"]).get("item") == item_id for r in rows)

    async def on_calendar(self, item: Item, by: Member, *, interactive: bool = False) -> None:
        """Keep its next due date on the family calendar: asked once, then kept true."""
        if self.sync is None or self.jobs is None:
            return
        if self._event(item.id) is not None:
            self._queue(item.id)
            return
        if self._waiting(item.id):
            return
        if self.sync.account() is None:
            log.info("Maintenance %s has a due date, but there's no calendar yet", item.id)
            return
        due = self.next_due(item)
        await self.services.autonomy.stage(
            CATEGORY,
            by,
            f"For the family calendar: {item.name}, due {due:%a %b %-d}, moved along each "
            "time it's done",
            {"item": item.id},
            EXECUTOR,
            interactive=interactive,
        )

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        item_id = int(payload["item"])
        if self.get(item_id) is None:
            return "That maintenance item has been removed since."
        family = self.store.get_family()
        seed = family.created_at.isoformat() if family else "themi"
        self.db.execute(
            "INSERT INTO calendar_events (source, source_id, event_id, created_at) "
            "VALUES ('maintenance', ?, ?, ?) ON CONFLICT (source, source_id) DO NOTHING",
            (item_id, event_id("maintenance", item_id, seed), to_utc_iso(clock.now())),
        )
        self._queue(item_id)
        return "Its due dates will show on the family calendar in a few minutes."

    def _queue(self, item_id: int) -> None:
        if self.jobs is not None and self._event(item_id) is not None:
            self.jobs.enqueue(JOB, {"id": item_id}, dedupe_key=f"{JOB}:{item_id}")

    async def run_job(self, payload: dict[str, Any]) -> str:
        """Queued job: the event shows the item's next due date, or goes with the item.
        Raises (and is retried) on errors."""
        assert self.sync is not None
        item_id = int(payload["id"])
        row = self._event(item_id)
        if row is None:
            return "not approved"
        item = self.get(item_id)
        if item is None:
            if row["state"] != "deleted" and row["calendar_id"] and row["account_id"]:
                await self.sync.delete(row["account_id"], row["calendar_id"], row["event_id"])
            self._mark(row["id"], "deleted")
            return "removed"
        account_id, calendar_id = row["account_id"], row["calendar_id"]
        if account_id is None or calendar_id is None:
            target = await self.sync.target()
            account_id, calendar_id = target.account.id, target.calendar_id
            self.db.execute(
                "UPDATE calendar_events SET account_id = ?, calendar_id = ? WHERE id = ?",
                (account_id, calendar_id, row["id"]),
            )
        await self.sync.upsert(account_id, calendar_id, row["event_id"], self.event_body(item))
        self._mark(row["id"], "synced")
        return "written"

    def event_body(self, item: Item) -> dict[str, Any]:
        due = self.next_due(item)
        who = f"{self.store.get_member(item.owner).name} looks after it. " if item.owner else ""
        steps = "".join(f"\n- {step}" for step in item.guide)
        return {
            "summary": item.name,
            "description": (
                f"{who}Due {every_words(item.interval_days)}, "
                f"{months_words(item.active_months)}. From Themi's maintenance list.{steps}"
            ),
            "start": {"date": due.isoformat()},
            "end": {"date": (due + timedelta(days=1)).isoformat()},
            "transparency": "transparent",  # a reminder, not a busy block
            "extendedProperties": {"private": {"themi": f"maintenance:{item.id}"}},
        }

    def _mark(self, row_id: int, state: str) -> None:
        self.db.execute(
            "UPDATE calendar_events SET state = ?, synced_at = ? WHERE id = ?",
            (state, to_utc_iso(clock.now()), row_id),
        )

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


# ----- tools -----------------------------------------------------------------------------


def _maintenance(ctx: ToolContext) -> Maintenance:
    if ctx.services.maintenance is None:
        raise ToolFailed("Maintenance isn't set up.")
    return ctx.services.maintenance


def _found(ctx: ToolContext, said: str) -> Item:
    item = _maintenance(ctx).find(said)
    if item is None:
        names = and_list([i.name for i in _maintenance(ctx).items()]) or "none yet"
        raise ToolFailed(f"No maintenance item called {said}. The items: {names}.")
    return item


def _owner(ctx: ToolContext, said: str) -> Member | bool | None:
    said = said.strip()
    if not said:
        return False
    if said.lower() in ("anyone", "either", "whoever", "both", "nobody"):
        return None
    if said.lower() in ("me", "i", "myself"):
        return ctx.member
    found = next(
        (m for m in ctx.services.store.list_members() if name_key(m.name) == name_key(said)),
        None,
    )
    if found is None:
        raise ToolFailed(f"There's nobody called {said} in the family.")
    return found


ITEM_ARG = {"type": "string", "description": "The item's name, e.g. 'Change the furnace filter'."}


@tool(
    "set_maintenance",
    "Add a seasonal or long-term upkeep job for the house, garden or car, or change one: "
    "filter changes, gutters, fertilizing trees, the smoke alarms. Themi offers each when "
    "it's due, at most one a day, at a good moment, and puts due dates on the family "
    "calendar. interval_days: how often (90 for every three months, 365 yearly; 0 keeps "
    "it). active_months: the months it's done in, or ['All year']; [] keeps them (a new "
    "one: all year). steps: the step-by-step guide in their words; [] keeps it. "
    "last_done: YYYY-MM-DD if they said, else ''. owner: 'me', a name, 'anyone', or '' "
    "to keep. new_name: a new name, or ''. Not a weekly or daily chore (set_task_schedule).",
    {
        "name": ITEM_ARG,
        "interval_days": {"type": "integer"},
        "active_months": {
            "type": "array",
            "items": {"type": "string", "enum": [*MONTHS, ALL_YEAR]},
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "last_done": {"type": "string"},
        "owner": {"type": "string"},
        "new_name": {"type": "string"},
    },
)
async def set_maintenance(ctx: ToolContext, args: dict[str, Any]) -> str:
    maintenance = _maintenance(ctx)
    try:
        months = month_numbers(args["active_months"]) if args["active_months"] else None
        last = str(args["last_done"]).strip()
        item, new = await maintenance.set(
            ctx.member,
            str(args["name"]),
            interval_days=int(args["interval_days"]) or None,
            months=months,
            guide=list(args["steps"]) or None,
            owner=_owner(ctx, str(args["owner"])),
            last_done=min(day_arg(last, maintenance.today()), maintenance.today())
            if last
            else None,
            new_name=str(args["new_name"]),
            interactive=True,
        )
    except ValueError as exc:
        raise ToolFailed(f"{str(exc).capitalize()}.") from exc
    return f"{'Added' if new else 'Changed'} {maintenance.describe(item)}."


@tool(
    "remove_maintenance",
    "Remove a maintenance item, with its history and its calendar event.",
    {"name": ITEM_ARG},
)
async def remove_maintenance(ctx: ToolContext, args: dict[str, Any]) -> str:
    item = _found(ctx, str(args["name"]))
    await _maintenance(ctx).remove(item, ctx.member)
    return f"Removed {item.name} from the maintenance list."


@tool(
    "get_maintenance_guide",
    "Read a maintenance item's step-by-step guide, when it's next due, and the notes from "
    "past runs ('how do I change the furnace filter?', 'what did we use on the trees last "
    "time?'). name: '' for every item, with their next due dates.",
    {"name": {"type": "string"}},
)
async def get_maintenance_guide(ctx: ToolContext, args: dict[str, Any]) -> str:
    maintenance = _maintenance(ctx)
    said = str(args["name"]).strip()
    if not said:
        items = maintenance.items()
        if not items:
            return "No maintenance items yet; set_maintenance adds one."
        return "\n".join(f"- {maintenance.describe(i)}" for i in items)
    return maintenance.guide_words(_found(ctx, said))


@tool(
    "log_maintenance",
    "Mark a maintenance item done, with any notes for next time ('changed the furnace "
    "filter, used the 16x25 from the shed'), whether or not Themi offered it. day: "
    "YYYY-MM-DD if they said an earlier day, else ''. Said again the same day, it adds the "
    "notes. notes: '' for none.",
    {"name": ITEM_ARG, "notes": {"type": "string"}, "day": {"type": "string"}},
)
async def log_maintenance(ctx: ToolContext, args: dict[str, Any]) -> str:
    maintenance = _maintenance(ctx)
    item = _found(ctx, str(args["name"]))
    today = maintenance.today()
    said = str(args["day"]).strip()
    try:
        on = min(day_arg(said, today), today) if said else today
    except ValueError as exc:
        raise ToolFailed("day is a date like 2026-11-04.") from exc
    return await maintenance.log(item, ctx.member, on, str(args["notes"]), interactive=True)
