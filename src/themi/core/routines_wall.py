"""Themi's routines on the Cozyla wall, both ways (R1b).

Themi owns the routines (R1a); the wall shows each item under the part of the
day its routine's window starts in (Morning, Afternoon or Evening), with its
days. The family can change them in either place. Each sync (the
`routines.wall` job, every 5 minutes):

- The wall's changes come in, by comparing it with the last sync
  (`routine_wall_seen`). An item made there goes to that person's first routine
  starting in its part; this is also how the wall's routines came into Themi
  the first time. Renamed, given other days, moved to another part, or
  deleted there: the same in Themi.
- Then Themi's changes go out (made, changed or removed in chat, or a routine
  re-timed into another part). A change Themi hasn't sent yet wins over one
  made on the wall.
- Ticks go both ways, for today.

Themi's check-ins (F8, C3) stay as C3 keeps them, and aren't routine items.
While this sync runs, C3's own checks stop, since Themi checks the routines.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.connectors.cozyla import CozylaClient, CozylaError, Routine, WallSchedule
from themi.core import praise
from themi.core.cozyla_routines import CozylaRoutines, part_of_day
from themi.core.cozyla_todos import backoff, member_map
from themi.core.repeat import DAY_NAMES
from themi.core.routines import DEFAULTS, Item, Routines
from themi.core.routines import Routine as ThemiRoutine
from themi.core.services import Services

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Seen:
    title: str
    part: str
    days: tuple[int, ...]


def days_from(schedule: WallSchedule) -> tuple[int, ...]:
    """The days a wall routine applies: set weekdays, or every day (anything else the wall
    can say, like monthly, comes in as every day)."""
    if schedule.every != "Weekly" or not schedule.days:
        return ()
    names = [d.strip() for d in schedule.days.split(",") if d.strip()]
    return tuple(sorted({DAY_NAMES.index(n) for n in names if n in DAY_NAMES}))


def schedule_for(days: tuple[int, ...], start: date) -> WallSchedule:
    if not days:
        return WallSchedule(True, "Daily", 1, "", start=start)
    return WallSchedule(True, "Weekly", 1, ",".join(DAY_NAMES[d] for d in days), start=start)


class RoutinesWall:
    def __init__(
        self, services: Services, routines: Routines, wall: CozylaRoutines, client: CozylaClient
    ) -> None:
        self.services = services
        self.routines = routines
        self.wall = wall
        self.client = client
        self.store = services.store
        self.db = services.store.db
        self._failures = 0
        self._wait_until: datetime | None = None

    def install(self) -> None:
        self.wall.checks_by_themi = True  # Themi's routines are checked by R1a now
        self.routines.tick_listeners.append(self.on_tick)

    async def on_tick(self, item: Item, day: date) -> None:
        """Ticked in Themi: ticked on the wall now, not at the next sync."""
        link = self.db.one(
            "SELECT wall_id FROM routine_item_links WHERE item_id = ? AND wall_id IS NOT NULL",
            (item.id,),
        )
        if link is not None:
            try:
                await self.client.check_routine(link["wall_id"], day, True)
            except CozylaError as exc:  # the next sync carries it over
                log.warning("Couldn't tick routine %s on the wall yet: %s", link["wall_id"], exc)

    async def sync(self) -> int:
        """Scheduler job. Returns how many of Themi's changes were sent."""
        if self._wait_until is not None and clock.now() < self._wait_until:
            return 0
        today = self.routines.today()
        try:
            members = await self.client.members()
            on_wall = await self.client.routines()
            records = await self.client.routine_records(today)
            to_member = member_map(members, self.store.list_members())
            checkins = {
                r["routine_id"] for r in self.db.query("SELECT routine_id FROM cozyla_routines")
            }
            mine = {r.id: r for r in on_wall if r.id not in checkins and r.member in to_member}
            self._pull(mine, to_member, today)
            sent = await self._push(mine, {m: u for u, m in to_member.items()}, today)
            await self._ticks(records, today)
        except CozylaError as exc:
            log.warning("Routines on the wall wait: %s", exc)
            self._failures += 1
            self._wait_until = clock.now() + backoff(self._failures)
            return 0
        self._failures, self._wait_until = 0, None
        return sent

    # ----- the wall's changes -------------------------------------------------------------

    def _pull(self, on_wall: dict[int, Routine], to_member: dict[str, int], today: date) -> None:
        for wall_routine in on_wall.values():
            link = self.db.one(
                "SELECT * FROM routine_item_links WHERE wall_id = ?", (wall_routine.id,)
            )
            now = Seen(wall_routine.title, wall_routine.part, days_from(wall_routine.schedule))
            if link is None:
                member = self.store.get_member(to_member[wall_routine.member])
                routine = self._routine_for(member, wall_routine.part)
                item = self.routines.add_item(routine, wall_routine.title, now.days)
                self._linked(item.id, wall_routine.id, now)
                continue
            if link["state"] == "pending":
                continue  # Themi's change wins
            before = self._seen(wall_routine.id)
            if before == now:
                continue
            item = self._item(link["item_id"])
            if item is None:
                continue
            routine = self.routines.get(item.routine_id)
            target = routine
            if part_of_day(routine.starts) != now.part:
                member = self.store.get_member(routine.member_id)
                target = self._routine_for(member, now.part)
            self.db.execute(
                "UPDATE routine_items SET title = ?, days = ?, routine_id = ? WHERE id = ?",
                (now.title[:50], json.dumps(list(now.days)), target.id, item.id),
            )
            self._linked(item.id, wall_routine.id, now)  # as the wall has it: nothing to send
        gone = self.db.query(
            "SELECT l.item_id, l.wall_id FROM routine_item_links l WHERE l.wall_id IS NOT NULL "
            "AND l.state = 'done'"
        )
        for row in gone:
            if row["wall_id"] in on_wall:
                continue
            # Deleted on the wall: deleted here, without telling the wall again.
            self.db.execute(
                "UPDATE routine_item_links SET wall_id = NULL WHERE item_id = ?", (row["item_id"],)
            )
            self.db.execute("DELETE FROM routine_items WHERE id = ?", (row["item_id"],))
            self.db.execute("DELETE FROM routine_wall_seen WHERE wall_id = ?", (row["wall_id"],))

    def _routine_for(self, member: Member, part: str) -> ThemiRoutine:
        """The person's first routine starting in that part of the day; if none does, one
        named for it, with its default window."""
        theirs = self.routines.of(member)
        found = next((r for r in theirs if part_of_day(r.starts) == part), None)
        if found is not None:
            return found
        name, starts, ends = next(d for d in DEFAULTS if d[0] == part)
        existing = self.routines.find(member, name)
        if existing is not None:
            return existing
        return self.routines.set(member, name, starts, ends)[0]

    # ----- Themi's changes ----------------------------------------------------------------

    async def _push(self, on_wall: dict[int, Routine], to_wall: dict[int, str], today: date) -> int:
        sent = 0
        for row in self.db.query("SELECT wall_id FROM routine_wall_deletes"):
            if row["wall_id"] in on_wall:
                await self.client.delete_routine(row["wall_id"], today)
            self.db.execute("DELETE FROM routine_wall_deletes WHERE wall_id = ?", (row["wall_id"],))
            self.db.execute("DELETE FROM routine_wall_seen WHERE wall_id = ?", (row["wall_id"],))
            sent += 1
        for link in self.db.query("SELECT * FROM routine_item_links WHERE state = 'pending'"):
            item = self._item(link["item_id"])
            if item is None:
                continue
            routine = self.routines.get(item.routine_id)
            uid = to_wall.get(routine.member_id)
            if uid is None:
                continue  # not a member on the wall
            part = part_of_day(routine.starts)
            days = () if item.only_on else item.days
            schedule = schedule_for(days, today)
            existing = on_wall.get(link["wall_id"]) if link["wall_id"] else None
            if existing is None:
                wall_id = await self.client.create_routine(uid, item.title, part, schedule)
            else:
                wall_id = existing.id
                await self.client.update_routine(existing, item.title, part, schedule, today)
            if item.only_on is not None:  # C3 deletes a just-for-today item the day after
                self.db.execute(
                    "INSERT OR REPLACE INTO wall_routine_once (routine_id, member_id, day) "
                    "VALUES (?, ?, ?)",
                    (wall_id, routine.member_id, item.only_on.isoformat()),
                )
            self.db.execute(
                "UPDATE routine_item_links SET wall_id = ?, state = CASE WHEN version = ? "
                "THEN 'done' ELSE 'pending' END WHERE item_id = ?",
                (wall_id, link["version"], item.id),
            )
            self._remember(wall_id, Seen(item.title, part, days))
            sent += 1
        return sent

    # ----- ticks ------------------------------------------------------------------------

    async def _ticks(self, records: list[Any], today: date) -> None:
        done_on_wall = {r.routine_id for r in records if r.completed}
        for link in self.db.query(
            "SELECT * FROM routine_item_links WHERE wall_id IS NOT NULL AND state = 'done'"
        ):
            item = self._item(link["item_id"])
            if item is None or not item.applies(today):
                continue
            ticked = self.routines.ticked(item, today)
            if link["wall_id"] in done_on_wall and not ticked:
                self.routines.tick(item, today)
                member = self.store.get_member(self.routines.get(item.routine_id).member_id)
                await praise.from_wall(self.services.outbox, member, item.title, f"r{item.id}")
            elif ticked and link["wall_id"] not in done_on_wall:
                await self.client.check_routine(link["wall_id"], today, True)

    # ----- small things -------------------------------------------------------------------

    def _item(self, item_id: int) -> Item | None:
        return self.routines.item(item_id)

    def _seen(self, wall_id: int) -> Seen | None:
        row = self.db.one("SELECT * FROM routine_wall_seen WHERE wall_id = ?", (wall_id,))
        if row is None:
            return None
        return Seen(row["title"], row["part"], tuple(json.loads(row["days"])))

    def _linked(self, item_id: int, wall_id: int, seen: Seen) -> None:
        self.db.execute(
            "UPDATE routine_item_links SET wall_id = ?, state = 'done' WHERE item_id = ?",
            (wall_id, item_id),
        )
        self._remember(wall_id, seen)

    def _remember(self, wall_id: int, seen: Seen) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO routine_wall_seen (wall_id, title, part, days) "
            "VALUES (?, ?, ?, ?)",
            (wall_id, seen.title, seen.part, json.dumps(list(seen.days))),
        )
