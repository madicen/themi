"""The wall's routines, and Themi's check-ins on them (C3).

Routines are one person's repeating "did you...?" for a part of the day
(Morning, Afternoon, Evening): walk the dog, cycle the dishwasher, take meds.
The family decided (2026-10-26) that Themi should say when a whole part of
the day's routine isn't done. Each sync (the `cozyla.routines` job):

- Morning and evening checks: after the morning (from noon) and in the
  evening (from an hour before quiet hours), if any of a person's routines
  for that part of the day are still open, one message lists them, with a
  button per routine that ticks it on the wall. All done: nothing is sent.
  Each check also feeds the energy model (as device activity, which the
  person can switch off): a part of the day done is a small lift, one left
  undone a small dip. That's Erin's idea #4 ("are we falling behind?")
  without a dishwasher sensor; people see words, never scores.
- Themi's check-ins (F8: a repeating task made with check_in, on fixed
  days) are that person's routine on the wall, for the part of the day of
  their time, kept by Themi like the chore chart (C2b): put back if changed
  there, made again if deleted. A tick on the wall closes the round; a round
  done in Themi ticks the wall. They're left out of the checks, since Themi
  nudges for them itself.

Wall routines that aren't Themi's stay the wall's: Themi reads them, ticks
them from a button, and never changes them.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.connectors.cozyla import CozylaClient, CozylaError, Routine, RoutineRecord
from themi.connectors.cozyla.schedule import to_wall
from themi.core.cozyla_chores import LOOK_BACK, is_routine
from themi.core.cozyla_todos import backoff, member_map
from themi.core.groceries import and_list
from themi.core.services import Services
from themi.core.tasks import TaskBoard
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

MORNING_CHECK = time(12)
EVENING_BEFORE_QUIET = timedelta(hours=1)
CHECKED_PARTS = ("Morning", "Evening")
CHECK_TEXT = "{part} routine: {items} still open. Done already?"
ALL_DONE_TEXT = "{part} routine: all done."
ROUTINE_SIGNAL = 0.5  # a part of the day done, or not: a small lift or dip


def part_of_day(at: time | None) -> str:
    """The wall's part of the day for a time: no time counts as the morning."""
    if at is None or at < time(12):
        return "Morning"
    return "Afternoon" if at < time(17) else "Evening"


class CozylaRoutines:
    def __init__(self, services: Services, board: TaskBoard, client: CozylaClient) -> None:
        self.services = services
        self.board = board
        self.client = client
        self.store = services.store
        self.db = services.store.db
        self._read_failures = 0
        self._read_after: datetime | None = None
        self._to_member: dict[str, int] = {}
        self._to_cozyla: dict[int, str] = {}

    def install(self) -> None:
        self.services.button_handlers["routine"] = self.on_button

    async def sync(self) -> int:
        """Scheduler job: ticks both ways, Themi's check-ins on the wall, then the morning
        and evening checks. Returns how many checks were sent."""
        if self._read_after is not None and clock.now() < self._read_after:
            return 0
        today = self._today()
        try:
            routines = await self.client.routines()
            members = await self.client.members()
            records = await self.client.routine_records(today)
        except CozylaError as exc:
            log.warning("Cozyla routine sync waits: %s", exc)
            self._read_failures += 1
            self._read_after = clock.now() + backoff(self._read_failures)
            return 0
        self._read_failures, self._read_after = 0, None
        self._to_member = member_map(members, self.store.list_members())
        self._to_cozyla = {mid: uid for uid, mid in self._to_member.items()}
        try:
            await self._ticks_from_wall(today, records)
            await self._ticks_to_wall()
            await self._push({r.id: r for r in routines}, today)
            return await self._checks(today, records)
        except CozylaError as exc:
            log.warning("Cozyla routine sync stopped partway; next time it carries on: %s", exc)
            return 0

    # ----- Themi's check-ins as routines ------------------------------------------------------

    async def _ticks_from_wall(self, today: date, records: list[RoutineRecord]) -> None:
        by_day: dict[date, list[RoutineRecord]] = {today: records}
        for link in self.db.query(
            "SELECT r.* FROM cozyla_routines r JOIN tasks t ON t.id = r.task_id "
            "WHERE t.status IN ('open', 'snoozed')"
        ):
            task = self.board.get(link["task_id"])
            if task.due_on is None or not today - LOOK_BACK <= task.due_on <= today:
                continue
            if task.due_on not in by_day:
                by_day[task.due_on] = await self.client.routine_records(task.due_on)
            for record in by_day[task.due_on]:
                if record.routine_id != link["routine_id"] or not record.completed:
                    continue
                if not self._first_time(f"{record.routine_id}_{record.day}"):
                    continue
                doer = self.store.get_member(task.assignee) if task.assignee else self._admin()
                await self.board.complete(task.id, doer)
                self._caught_up(task.id)

    async def _ticks_to_wall(self) -> None:
        for link in self.db.query("SELECT * FROM cozyla_routines"):
            for run in self.db.query(
                "SELECT * FROM task_runs WHERE task_id = ? AND id > ? ORDER BY id",
                (link["task_id"], link["last_run"]),
            ):
                if not run["missed"] and run["due_on"]:
                    day = date.fromisoformat(run["due_on"])
                    await self.client.check_routine(link["routine_id"], day, True)
                    self._first_time(f"{link['routine_id']}_{day}")
                self.db.execute(
                    "UPDATE cozyla_routines SET last_run = ? WHERE task_id = ?",
                    (run["id"], link["task_id"]),
                )

    async def _push(self, routines: dict[int, Routine], today: date) -> None:
        rows = self.db.query(
            "SELECT t.id FROM tasks t LEFT JOIN cozyla_routines r ON r.task_id = t.id "
            "WHERE r.task_id IS NOT NULL OR (t.status IN ('open', 'snoozed') AND t.check_in = 1)"
        )
        for row in rows:
            task = self.board.get(row["id"])
            link = self.db.one("SELECT * FROM cozyla_routines WHERE task_id = ?", (task.id,))
            routine = routines.get(link["routine_id"]) if link else None
            member = self._to_cozyla.get(task.assignee) if task.assignee else None
            keep = task.status in ("open", "snoozed") and is_routine(task) and member
            if not keep or (routine is not None and routine.member != member):
                if routine is not None:  # stopped, or someone else's now: made again below
                    await self.client.delete_routine(routine.id, today)
                self.db.execute("DELETE FROM cozyla_routines WHERE task_id = ?", (task.id,))
                link = routine = None
            if not keep or member is None or task.repeat is None:
                continue
            title, part = task.title[:50], part_of_day(task.repeat.at)
            schedule = to_wall(task.repeat, task.due_on or today)
            if routine is None:
                made = await self.client.create_routine(member, title, part, schedule)
                self.db.execute(
                    "INSERT INTO cozyla_routines (task_id, routine_id, last_run) VALUES (?, ?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET routine_id = excluded.routine_id",
                    (task.id, made, self._last_run(task.id)),
                )
                continue
            same = (routine.title, routine.part) == (title, part) and (
                routine.schedule.every,
                routine.schedule.count,
                {d.strip() for d in routine.schedule.days.split(",") if d.strip()},
            ) == (schedule.every, schedule.count, {d for d in schedule.days.split(",") if d})
            if not same:
                await self.client.update_routine(routine, title, part, schedule, today)

    # ----- the morning and evening checks -----------------------------------------------------

    async def _checks(self, today: date, records: list[RoutineRecord]) -> int:
        now = clock.now().astimezone(self._tz())
        mine = {r["routine_id"] for r in self.db.query("SELECT routine_id FROM cozyla_routines")}
        sent = 0
        for member in self.store.list_members():
            uid = self._to_cozyla.get(member.id)
            if uid is None or member.telegram_user_id is None:
                continue
            quiet = self._quiet_starts(member, now)
            for part in CHECKED_PARTS:
                start = (
                    now.replace(hour=MORNING_CHECK.hour, minute=0, second=0, microsecond=0)
                    if part == "Morning"
                    else quiet - EVENING_BEFORE_QUIET
                )
                if not start <= now < quiet or self._checked(member, today, part):
                    continue
                theirs = [
                    r
                    for r in records
                    if r.member == uid and r.part == part and r.routine_id not in mine
                ]
                if not theirs:
                    continue
                self.db.execute(
                    "INSERT INTO routine_checks_sent (member_id, day, part) VALUES (?, ?, ?)",
                    (member.id, today.isoformat(), part),
                )
                still = [r for r in theirs if not r.completed]
                lift = ROUTINE_SIGNAL if not still else -ROUTINE_SIGNAL
                words = (
                    "done" if not still else f"not finished ({and_list([r.title for r in still])})"
                )
                self.services.energy.record(
                    member, "device_activity", lift, f"{part.lower()} routine {words}"
                )
                if not still:
                    continue
                await self.services.outbox.send(
                    member,
                    CHECK_TEXT.format(part=part, items=and_list([r.title for r in still])),
                    priority=Priority.NORMAL,
                    kind="routine",
                    buttons=self._buttons(still, today),
                    deadline=quiet - timedelta(minutes=15),
                    dedupe_key=f"routine-{part}-{today}",
                )
                sent += 1
        return sent

    @staticmethod
    def _buttons(still: list[RoutineRecord], day: date) -> list[Button]:
        return [
            Button(
                f"✓ {r.title}"[:40], "routine", {"routine": r.routine_id, "day": day.isoformat()}
            )
            for r in still
        ]

    async def on_button(self, event: InboundEvent) -> None:
        """A routine's button: tick it on the wall, and show what's left."""
        assert event.button is not None
        routine_id = int(event.button.payload["routine"])
        day = date.fromisoformat(str(event.button.payload["day"]))
        try:
            await self.client.check_routine(routine_id, day, True)
            records = await self.client.routine_records(day)
        except CozylaError as exc:
            log.warning("Couldn't tick routine %s on the wall: %s", routine_id, exc)
            text = "The wall couldn't be reached, so that isn't ticked yet. Try again in a bit?"
            if event.button.message_id is not None:
                await self.services.outbox.edit(event.member, event.button.message_id, text)
            return
        self._first_time(f"{routine_id}_{day}")
        ticked = next((r for r in records if r.routine_id == routine_id), None)
        part = ticked.part if ticked else "Morning"
        uid = self._to_cozyla.get(event.member.id) or (ticked.member if ticked else "")
        mine = {r["routine_id"] for r in self.db.query("SELECT routine_id FROM cozyla_routines")}
        still = [
            r
            for r in records
            if r.member == uid and r.part == part and not r.completed and r.routine_id not in mine
        ]
        if event.button.message_id is None:
            return
        if still:
            text = CHECK_TEXT.format(part=part, items=and_list([r.title for r in still]))
            await self.services.outbox.edit(
                event.member, event.button.message_id, text, self._buttons(still, day)
            )
        else:
            await self.services.outbox.edit(
                event.member, event.button.message_id, ALL_DONE_TEXT.format(part=part)
            )

    # ----- small things -------------------------------------------------------------------

    def _checked(self, member: Member, day: date, part: str) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM routine_checks_sent WHERE member_id = ? AND day = ? AND part = ?",
                (member.id, day.isoformat(), part),
            )
        )

    @staticmethod
    def _quiet_starts(member: Member, now: datetime) -> datetime:
        at = member.quiet_start
        start = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        return start + timedelta(days=1) if at < time(12) else start

    def _caught_up(self, task_id: int) -> None:
        self.db.execute(
            "UPDATE cozyla_routines SET last_run = ? WHERE task_id = ?",
            (self._last_run(task_id), task_id),
        )

    def _last_run(self, task_id: int) -> int:
        return self.db.scalar(
            "SELECT COALESCE(MAX(id), 0) FROM task_runs WHERE task_id = ?", (task_id,)
        )

    def _first_time(self, record: str) -> bool:
        if self.db.one("SELECT 1 FROM cozyla_routine_ticks WHERE record = ?", (record,)):
            return False
        self.db.execute(
            "INSERT INTO cozyla_routine_ticks (record, seen_at) VALUES (?, ?)",
            (record, to_utc_iso(clock.now())),
        )
        return True

    def _today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _admin(self) -> Member:
        return next(m for m in self.store.list_members() if m.is_admin)
