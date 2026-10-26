"""Themi's chores on the wall's chore chart, Themi in charge (C2b).

The family decided (2026-10-26) that Themi's calendar, the more flexible one,
runs the chart. Each sync (the `cozyla.chores` job) works out what the chart
should hold and makes it so; nothing is queued, so a change on either side is
simply compared with what Themi has:

- Each Themi chore has one wall chore: repeating with the same schedule when
  the wall can say it, otherwise a one-off on the current round's day, moved
  when the round moves (`themi.connectors.cozyla.schedule`). Its name, people
  and schedule are put back if they were changed on the wall, and it's made
  again if it was deleted there; a chore is stopped in Themi.
- A chore for one person is the wall's "Everyone" with them; one either of
  you can do ("either", or escalated to both) is "AnyOne" with both.
- Chores only on the wall come in first: active ones are linked by title to a
  Themi chore with small words ignored ("Clean bird cage", "Clean the bird
  cage"), or become Themi chores with their schedule, people and end. Ended
  ones are left alone. From then on Themi owns them.
- A tick on the wall for the current round's day closes the round in Themi,
  as whoever ticked it; a round done in Themi ticks the doer's day on the wall.
  Ticks already acted on are remembered, so none counts twice.

Wall reminders stay off (C2a creates chores without them): Themi does the
reminding. A failed read waits and backs off, as the to-do sync does.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.connectors.cozyla import Chore, CozylaClient, CozylaError, WallSchedule
from themi.connectors.cozyla.schedule import from_wall, to_wall
from themi.core.cozyla_todos import backoff, member_map
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

CHORE_KIND, CHORE_EFFORT = "physical", 2
LOOK_BACK = timedelta(days=7)  # how far back a round's tick on the wall is looked for
REPEATS = "(t.times_per_week IS NOT NULL OR t.repeat IS NOT NULL OR t.due_before_task IS NOT NULL)"
SMALL_WORDS = frozenset({"the", "a", "an", "my", "our", "your"})
Desired = tuple[str, list[str], str, WallSchedule]  # name, people, kind, schedule


def title_key(title: str) -> str:
    """A chore's title for matching: "Clean the bird cage" and "Clean bird cage" agree."""
    words = re.findall(r"[a-z0-9']+", title.casefold())
    return " ".join(w for w in words if w not in SMALL_WORDS)


def _same_schedule(a: WallSchedule, b: WallSchedule) -> bool:
    if a.repeats != b.repeats or a.due_time != b.due_time:
        return False
    if not a.repeats:
        return (a.start, a.end) == (b.start, b.end)
    days = {d.strip() for d in a.days.split(",") if d.strip()}
    same = (a.every, a.count, a.start, a.forever) == (b.every, b.count, b.start, b.forever)
    same = same and days == {d.strip() for d in b.days.split(",") if d.strip()}
    return same and (a.forever or a.end == b.end)  # a forever chore's end means nothing


class CozylaChores:
    def __init__(self, services: Services, board: TaskBoard, client: CozylaClient) -> None:
        self.services = services
        self.board = board
        self.client = client
        self.db = services.store.db
        self._read_failures = 0
        self._read_after: datetime | None = None
        self._to_member: dict[str, int] = {}
        self._to_cozyla: dict[int, str] = {}

    async def sync(self) -> int:
        """Scheduler job: bring in the wall's chores and ticks, then make the chart match
        Themi. Returns how many wall chores were made, changed or removed."""
        if self._read_after is not None and clock.now() < self._read_after:
            return 0
        try:
            chores = await self.client.chores()
            members = await self.client.members()
        except CozylaError as exc:
            log.warning("Cozyla chore sync waits: %s", exc)
            self._read_failures += 1
            self._read_after = clock.now() + backoff(self._read_failures)
            return 0
        self._read_failures, self._read_after = 0, None
        self._to_member = member_map(members, self.services.store.list_members())
        self._to_cozyla = {mid: uid for uid, mid in self._to_member.items()}
        by_uid = {c.uid: c for c in chores}
        try:
            await self._bring_in(chores)
            await self._ticks_from_wall()
            await self._ticks_to_wall(by_uid)
            changed = await self._push(by_uid)
        except CozylaError as exc:
            log.warning("Cozyla chore sync stopped partway; next time it carries on: %s", exc)
            return 0
        self.db.execute(
            "INSERT INTO cozyla_chore_sync (id, synced_at) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET synced_at = excluded.synced_at",
            (to_utc_iso(clock.now()),),
        )
        return changed

    # ----- from the wall ------------------------------------------------------------------

    async def _bring_in(self, chores: list[Chore]) -> None:
        """Chores only on the wall: linked to a Themi chore by title, or brought in."""
        today = self._today()
        linked = {r["chore_uid"] for r in self.db.query("SELECT chore_uid FROM cozyla_chores")}
        for chore in chores:
            if chore.uid in linked or not chore.active_on(today):
                continue
            repeat = from_wall(chore.schedule, today)
            if repeat is None:
                log.info("Cozyla chore %s isn't a schedule Themi can keep; left alone", chore.uid)
                continue
            match = self._unlinked(chore.name)
            if match is not None:
                self._link(match.id, chore.uid)  # Themi's schedule is written to the wall
                continue
            people = [self._to_member[m] for m in chore.members if m in self._to_member]
            if not people:
                log.info("Cozyla chore %s is for nobody Themi knows; left alone", chore.uid)
                continue
            owner = self.services.store.get_member(people[0])
            task = await self.board.create(
                owner, chore.name, CHORE_KIND, CHORE_EFFORT, nudge=False, assignee=owner
            )
            # From the wall: nobody is known to have added it, so its nudges name no one.
            self.db.execute("UPDATE tasks SET created_by = NULL WHERE id = ?", (task.id,))
            await self.board.set_schedule(
                task.id, self._admin(), repeat=repeat, either=len(people) > 1
            )
            self._link(task.id, chore.uid)
            linked.add(chore.uid)
            log.info("Brought in Cozyla chore %s as task %s", chore.uid, task.id)

    async def _ticks_from_wall(self) -> None:
        """A tick on the wall for an open round's day closes the round, as whoever ticked."""
        today = self._today()
        rounds: dict[date, list[tuple[Task, str]]] = {}
        for link in self.db.query(
            "SELECT c.* FROM cozyla_chores c JOIN tasks t ON t.id = c.task_id "
            "WHERE t.status IN ('open', 'snoozed')"
        ):
            task = self.board.get(link["task_id"])
            day = self._round_day(task, today)
            if today - LOOK_BACK <= day <= today:
                rounds.setdefault(day, []).append((task, link["chore_uid"]))
        for day, items in rounds.items():
            records = await self.client.chore_records(day)
            for task, uid in items:
                for record in records:
                    if record.chore_uid != uid or record.status != "completed":
                        continue
                    if not self._first_time(f"{uid}_{record.member}_{record.day}"):
                        continue
                    member_id = self._to_member.get(record.member)
                    doer = self.services.store.get_member(member_id) if member_id else self._admin()
                    await self.board.complete(task.id, doer)
                    self._caught_up(task.id)  # that run came from the wall: no tick back
                    break

    # ----- to the wall --------------------------------------------------------------------

    async def _ticks_to_wall(self, by_uid: dict[str, Chore]) -> None:
        """A round done in Themi ticks the doer's day on the wall."""
        for link in self.db.query("SELECT * FROM cozyla_chores"):
            chore = by_uid.get(link["chore_uid"])
            runs = self.db.query(
                "SELECT * FROM task_runs WHERE task_id = ? AND id > ? ORDER BY id",
                (link["task_id"], link["last_run"]),
            )
            for run in runs:
                member = self._to_cozyla.get(run["done_by"]) if run["done_by"] else None
                if chore is not None and not run["missed"] and run["due_on"] and member:
                    day = date.fromisoformat(run["due_on"])
                    who = member if member in chore.members else chore.members[0]
                    await self.client.check_chore(chore.uid, who, day, True)
                    self._first_time(f"{chore.uid}_{who}_{day}")
                self.db.execute(
                    "UPDATE cozyla_chores SET last_run = ? WHERE task_id = ?",
                    (run["id"], link["task_id"]),
                )

    async def _push(self, by_uid: dict[str, Chore]) -> int:
        """Make each Themi chore's wall chore match it; Themi wins."""
        changed = 0
        rows = self.db.query(
            "SELECT t.id FROM tasks t LEFT JOIN cozyla_chores c ON c.task_id = t.id "
            f"WHERE c.task_id IS NOT NULL OR (t.status IN ('open', 'snoozed') AND {REPEATS})"
        )
        for row in rows:
            task = self.board.get(row["id"])
            link = self.db.one("SELECT * FROM cozyla_chores WHERE task_id = ?", (task.id,))
            chore = by_uid.get(link["chore_uid"]) if link else None
            if task.status == "cancelled" or not task.repeats:
                if chore is not None:
                    await self.client.delete_chore(chore.uid)
                    changed += 1
                self.db.execute("DELETE FROM cozyla_chores WHERE task_id = ?", (task.id,))
                continue
            if task.status == "done":  # a course that's over ends on the wall by itself
                self.db.execute("DELETE FROM cozyla_chores WHERE task_id = ?", (task.id,))
                continue
            desired = self._desired(task)
            if desired is None:
                continue
            if chore is None:
                made = await self.client.create_chore(*desired)
                self._link(task.id, made.uid)
                changed += 1
            elif not self._matches(chore, desired):
                await self.client.update_chore(chore, *desired)
                changed += 1
        return changed

    @staticmethod
    def _round_day(task: Task, today: date) -> date:
        """The current round's day: its due date, or today for a chore that's due whenever
        (a "twice a week" chore before its first round is done)."""
        return task.due_on or today

    def _desired(self, task: Task) -> Desired | None:
        if task.either or task.shared:
            people = list(self._to_cozyla.values())
        elif task.assignee is not None and task.assignee in self._to_cozyla:
            people = [self._to_cozyla[task.assignee]]
        else:
            return None
        if not people:
            return None
        kind = "AnyOne" if len(people) > 1 else "Everyone"
        day = self._round_day(task, self._today())
        return task.title[:50], people, kind, to_wall(task.repeat, day)

    @staticmethod
    def _matches(chore: Chore, desired: Desired) -> bool:
        name, people, kind, schedule = desired
        return (
            chore.name == name
            and set(chore.members) == set(people)
            and chore.kind == kind
            and _same_schedule(chore.schedule, schedule)
        )

    # ----- small things -------------------------------------------------------------------

    def _unlinked(self, name: str) -> Task | None:
        key = title_key(name)
        for row in self.db.query(
            "SELECT t.id, t.title FROM tasks t LEFT JOIN cozyla_chores c ON c.task_id = t.id "
            f"WHERE c.task_id IS NULL AND t.status IN ('open', 'snoozed') AND {REPEATS}"
        ):
            if title_key(row["title"]) == key:
                return self.board.get(row["id"])
        return None

    def _link(self, task_id: int, chore_uid: str) -> None:
        """Link a task to its wall chore. Runs before now are history, not ticks to send;
        a link made again (the wall chore was deleted) keeps its place."""
        last = self._last_run(task_id)
        self.db.execute(
            "INSERT INTO cozyla_chores (task_id, chore_uid, last_run) VALUES (?, ?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET chore_uid = excluded.chore_uid",
            (task_id, chore_uid, last),
        )

    def _caught_up(self, task_id: int) -> None:
        self.db.execute(
            "UPDATE cozyla_chores SET last_run = ? WHERE task_id = ?",
            (self._last_run(task_id), task_id),
        )

    def _last_run(self, task_id: int) -> int:
        return self.db.scalar(
            "SELECT COALESCE(MAX(id), 0) FROM task_runs WHERE task_id = ?", (task_id,)
        )

    def _first_time(self, record: str) -> bool:
        """Remember a wall tick; False if it was already seen."""
        seen = self.db.one("SELECT 1 FROM cozyla_chore_ticks WHERE record = ?", (record,))
        if seen:
            return False
        self.db.execute(
            "INSERT INTO cozyla_chore_ticks (record, seen_at) VALUES (?, ?)",
            (record, to_utc_iso(clock.now())),
        )
        return True

    def _today(self) -> date:
        family = self.services.store.get_family()
        return clock.now().astimezone(ZoneInfo(family.timezone if family else "UTC")).date()

    def _admin(self) -> Member:
        return next(m for m in self.services.store.list_members() if m.is_admin)
