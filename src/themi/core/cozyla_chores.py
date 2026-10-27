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
- Someone who sees only so many chores at a time (C2d, `themi.core.chore_chart`):
  their waiting chores are off the wall (or there only for the other person), and a
  chore that's up shows as a one-off for today. Deleting it on the wall completes it.

Wall reminders stay off (C2a creates chores without them): Themi does the
reminding. A failed read waits and backs off, as the to-do sync does.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.connectors.cozyla import Chore, CozylaClient, CozylaError, WallSchedule
from themi.connectors.cozyla.emoji import better_icon, chore_icon
from themi.connectors.cozyla.schedule import from_wall, to_wall
from themi.core.chore_chart import ChartQueue, is_routine, on_chart
from themi.core.cozyla_todos import backoff, member_map
from themi.core.reminders import MEDICINE
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

CHORE_KIND, CHORE_EFFORT = "physical", 2
LOOK_BACK = timedelta(days=7)  # how far back a round's tick on the wall is looked for
REPEATS = (
    "(t.times_per_week IS NOT NULL OR t.repeat IS NOT NULL OR t.due_before_task IS NOT NULL "
    "OR t.on_chart = 1)"
)  # what belongs on the chart: chores, and one-offs put there
SMALL_WORDS = frozenset({"the", "a", "an", "my", "our", "your"})
Desired = tuple[str, list[str], str, WallSchedule]  # name, people, kind, schedule


def day_words(day: date) -> str:
    """ "Sunday 1 Nov": the day a chore shows on the wall, which is what people ask about."""
    return f"{day:%A} {day.day} {day:%b}"


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


@tool(
    "put_task_on_chore_chart",
    "Put a one-off task on the Cozyla wall's chore chart instead of its to-do list ('move it "
    "to chores'). Repeating chores are on the chart already; the chart isn't one of the to-do "
    "lists. To take it back to the to-do list, use put_task_on_wall_list.",
    {"task_id": {"type": "integer"}},
)
async def put_task_on_chore_chart(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = ctx.services.taskboard
    assert board is not None
    try:
        task = await board.put_on_chart(args["task_id"], ctx.member)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    day = day_words(task.due_on or board._today())
    return (
        f"Task {task.id} ({task.title}) is moving to the wall's chore chart, where it shows on "
        f"{day} (its day). It's off the to-do list, and the chart has it within a few minutes. "
        f"Tell them the day it shows."
    )


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
        self.queue = ChartQueue(services, board)

    def install(self) -> None:
        self.services.tools.register(put_task_on_chore_chart)
        self.board.wall_notes.append(self.where)
        self.queue.install()

    def where(self, task: Task) -> str | None:
        """The day a task shows on the chart, for the model; None if it isn't for the chart."""
        if task.status not in ("open", "snoozed") or not on_chart(task) or is_routine(task):
            return None
        limited = [m for m in self.queue.limited() if self.queue.counts(task, m)]
        up = next((m for m in limited if self.queue.is_up(task, m)), None)
        if up is not None:
            return f"Up now on {up.name}'s chore chart ({up.chart_limit} at a time)."
        if limited and not self._wall_members(task):
            charts = " and ".join(
                f"{m.name}'s chore chart ({m.chart_limit} at a time)" for m in limited
            )
            return f"Waiting its turn for {charts}; not on the wall yet."
        day = day_words(self._round_day(task, self._today()))
        linked = self.db.one("SELECT 1 FROM cozyla_chores WHERE task_id = ?", (task.id,))
        return f"Shows on the wall's chore chart on {day}{'' if linked else ' (being added now)'}."

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
            await self._ticks_from_wall(by_uid)
            await self._ticks_to_wall(by_uid)
            await self._bring_up()
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
            # Medicine-like chores start as important (C2c).
            importance = "high" if MEDICINE.search(chore.name) else "normal"
            self.db.execute(
                "UPDATE tasks SET created_by = NULL, importance = ? WHERE id = ?",
                (importance, task.id),
            )
            await self.board.set_schedule(
                task.id, self._admin(), repeat=repeat, either=len(people) > 1
            )
            self._link(task.id, chore.uid)
            linked.add(chore.uid)
            log.info("Brought in Cozyla chore %s as task %s", chore.uid, task.id)

    async def _ticks_from_wall(self, by_uid: dict[str, Chore]) -> None:
        """A tick on the wall for an open round's day closes the round, as whoever ticked."""
        today = self._today()
        rounds: dict[date, list[tuple[Task, str]]] = {}
        for link in self.db.query(
            "SELECT c.* FROM cozyla_chores c JOIN tasks t ON t.id = c.task_id "
            "WHERE t.status IN ('open', 'snoozed')"
        ):
            task = self.board.get(link["task_id"])
            one_off = self._wall_day(by_uid.get(link["chore_uid"]))
            # An either-day round's tick can be on either day (F9a).
            days = [one_off] if one_off else self.board.round_days(task) or [today]
            for day in days:
                if today - LOOK_BACK <= day <= today:
                    rounds.setdefault(day, []).append((task, link["chore_uid"]))
        closed: set[int] = set()
        for day, items in rounds.items():
            records = await self.client.chore_records(day)
            for task, uid in items:
                if task.id in closed:
                    continue
                for record in records:
                    if record.chore_uid != uid or record.status != "completed":
                        continue
                    if not self._first_time(f"{uid}_{record.member}_{record.day}"):
                        continue
                    member_id = self._to_member.get(record.member)
                    doer = self.services.store.get_member(member_id) if member_id else self._admin()
                    await self.board.complete(task.id, doer)
                    self._caught_up(task.id)  # that run came from the wall: no tick back
                    closed.add(task.id)
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
                    day = self._wall_day(chore) or self.board.done_day(
                        date.fromisoformat(run["due_on"]),
                        datetime.fromisoformat(run["done_at"]),
                        self.board.get(link["task_id"]),
                    )
                    who = member if member in chore.members else chore.members[0]
                    await self.client.check_chore(chore.uid, who, day, True)
                    self._first_time(f"{chore.uid}_{who}_{day}")
                self.db.execute(
                    "UPDATE cozyla_chores SET last_run = ? WHERE task_id = ?",
                    (run["id"], link["task_id"]),
                )

    async def _bring_up(self) -> None:
        """Fill the charts of people who see a few at a time; a chore that comes up gets its
        nudge then (it was held back while it waited)."""
        for member, task in self.queue.refresh():
            queued = self.db.one(
                "SELECT 1 FROM outbox WHERE status = 'queued' AND member_id = ? "
                "AND dedupe_key LIKE ?",
                (member.id, f"task-{task.id}-%"),
            )
            if not queued:
                await self.board.prompt(task, member=member)
            self.queue.prompted(member, task)

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
            if link is not None and chore is None and task.status in ("open", "snoozed"):
                doer = self.queue.done_on_wall(task)
                if doer is not None:  # deleted on the wall while up: done (C2d)
                    self.db.execute("DELETE FROM cozyla_chores WHERE task_id = ?", (task.id,))
                    await self.board.complete(task.id, doer)
                    self._caught_up(task.id)
                    continue
            off_wall = self._waiting(task) and not self._wall_members(task)
            if task.status == "cancelled" or not on_chart(task) or is_routine(task) or off_wall:
                # A check-in on fixed days is a routine on the wall (C3), not a chore; a chore
                # waiting its turn for someone's chart is off the wall (C2d).
                if chore is not None:
                    await self.client.delete_chore(chore.uid)
                    changed += 1
                self.db.execute("DELETE FROM cozyla_chores WHERE task_id = ?", (task.id,))
                continue
            if task.status == "done":  # a course that's over ends on the wall by itself
                if chore is not None and not task.repeats:
                    await self._tick_one_off(task, chore)  # done in Themi: ticked there too
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

    async def _tick_one_off(self, task: Task, chore: Chore) -> None:
        member = self._to_cozyla.get(task.assignee) if task.assignee else None
        day = chore.schedule.start
        if member is None or day is None:
            return
        who = member if member in chore.members else chore.members[0]
        if self._first_time(f"{chore.uid}_{who}_{day}"):
            await self.client.check_chore(chore.uid, who, day, True)

    def _desired(self, task: Task) -> Desired | None:
        people = self._wall_people(task)
        if not people:
            return None
        kind = "AnyOne" if len(people) > 1 else "Everyone"
        today = self._today()
        if any(self.queue.is_up(task, m) for m in self.queue.limited()):
            # Up on a limited chart: a one-off for today, whatever its round's day (C2d).
            at = task.repeat.at if task.repeat else None
            once = WallSchedule(False, start=today, end=today, forever=False, due_time=at)
            return task.title[:50], people, kind, once
        return task.title[:50], people, kind, to_wall(task.repeat, self._round_day(task, today))

    def _wall_members(self, task: Task) -> list[int]:
        """Whose chart a chore is on: its person, or both for either of you, less anyone it's
        waiting its turn for (C2d)."""
        if task.either or task.shared:
            members = self.services.store.list_members()
        elif task.assignee is not None:
            members = [self.services.store.get_member(task.assignee)]
        else:
            members = []
        return [m.id for m in members if not self.queue.held(task, m)]

    def _waiting(self, task: Task) -> bool:
        return any(self.queue.held(task, m) for m in self.queue.limited())

    def _wall_people(self, task: Task) -> list[str]:
        """The same, as the wall's member ids, for those the wall knows."""
        return [self._to_cozyla[i] for i in self._wall_members(task) if i in self._to_cozyla]

    @staticmethod
    def _wall_day(chore: Chore | None) -> date | None:
        """A one-off wall chore's own day, which is where its tick lands."""
        if chore is None or chore.schedule.repeats:
            return None
        return chore.schedule.start

    @staticmethod
    def _matches(chore: Chore, desired: Desired) -> bool:
        name, people, kind, schedule = desired
        icon = str(chore.raw.get("icon") or "")
        return (
            chore.name == name
            and set(chore.members) == set(people)
            and chore.kind == kind
            and _same_schedule(chore.schedule, schedule)
            and not better_icon(icon, chore_icon(name))  # idea #25
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
