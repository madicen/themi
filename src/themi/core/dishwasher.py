"""The dishwasher, read from Home Connect (H1, Erin's idea #4).

Each read (the `devices.dishwasher` job, every 5 minutes: about 290 of Home
Connect's 1000 calls a day):

- The dishwasher moving into Run starts a cycle; leaving it ends one.
- A cycle starting checks off today's dishwasher item on the wall's routines
  (C3) and any open Themi task about the dishwasher. Each goes through the
  `dishwasher_done` category, to whoever's item it is: a card to say yes to,
  until a rule makes it automatic.

Once a day (`devices.dishwasher_pace`), fewer runs this week than usual is a
gentle "running behind" sign for everyone, as device activity, which each
person can switch off. The words carry the counts; people never see a score.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Device, Member
from themi.autonomy import ExecutionContext
from themi.connectors.cozyla import CozylaError
from themi.connectors.homeconnect import (
    RUN,
    ApplianceOffline,
    HomeConnectAccount,
    HomeConnectError,
    RateLimited,
)
from themi.core.events import title_matches
from themi.core.services import Services
from themi.core.tasks import TaskBoard, clock_words
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

CATEGORY, EXECUTOR = "dishwasher_done", "devices.dishwasher_done"
WORDS = "dishwasher"  # the routine items and tasks a cycle checks off
APPLIANCES = {"Dishwasher": "dishwasher", "Washer": "washer", "Dryer": "dryer"}
RECENT = timedelta(days=7)
USUAL_OVER = timedelta(days=28)  # at most this much before the recent week
ENOUGH_HISTORY = timedelta(days=7)  # at least this much before it
BEHIND = 0.6  # fewer than this share of the usual runs is behind
MIN_USUAL = 2.0  # below this many a week, a quiet week says little
PACE_SIGNAL = -0.5
PACE_FROM = time(18)  # the day's read comes in the evening, once most runs would be in


class Dishwasher:
    def __init__(self, services: Services, board: TaskBoard, account: HomeConnectAccount) -> None:
        self.services = services
        self.board = board
        self.account = account
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.autonomy.executors.register(EXECUTOR)(self._execute)
        self.services.dishwasher = self

    # ----- linking --------------------------------------------------------------------

    async def add_appliances(self, by: Member) -> list[Device]:
        """After a link: Home Connect's appliances become devices (new ones only)."""
        known = {d.external_id for d in self.devices()}
        added = []
        for appliance in await self.account.appliances():
            if appliance.ha_id in known:
                continue
            added.append(
                self.store.add_device(
                    by,
                    "home_connect",
                    appliance.ha_id,
                    appliance.name,
                    APPLIANCES.get(appliance.kind),
                )
            )
        return added

    # ----- reading the dishwasher -----------------------------------------------------

    async def poll(self) -> int:
        """Scheduler job: read each dishwasher's state. Returns how many cycles started."""
        if not self.account.linked():
            return 0
        started = 0
        for device in self.devices("dishwasher"):
            try:
                state = await self.account.operation_state(device.external_id)
            except ApplianceOffline:
                state = "Offline"
            except RateLimited as exc:
                log.warning("Home Connect asked to wait %s; the dishwasher read waits", exc.wait)
                return started
            except HomeConnectError as exc:
                log.warning("Couldn't read the dishwasher: %s", exc)
                return started
            if await self._saw(device, state):
                started += 1
        return started

    async def _saw(self, device: Device, state: str) -> bool:
        """Note the state; True if a cycle started. Offline says nothing either way."""
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET state = excluded.state, "
            "seen_at = excluded.seen_at",
            (device.id, state, now),
        )
        if state == "Offline":
            return False
        running = self.db.one(
            "SELECT 1 FROM appliance_cycles WHERE device_id = ? AND ended_at IS NULL", (device.id,)
        )
        if state != RUN:
            if running:
                self.db.execute(
                    "UPDATE appliance_cycles SET ended_at = ? "
                    "WHERE device_id = ? AND ended_at IS NULL",
                    (now, device.id),
                )
            return False
        if running:
            return False
        self.db.execute(
            "INSERT INTO appliance_cycles (device_id, started_at) VALUES (?, ?)", (device.id, now)
        )
        await self._started()
        return True

    # ----- checking things off ---------------------------------------------------------

    async def _started(self) -> None:
        local = clock.now().astimezone(self._tz())
        at, today = clock_words(local), local.date()
        until = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        for title, member, payload in await self._to_check_off(today):
            await self.services.autonomy.stage(
                CATEGORY,
                member,
                f"The dishwasher started at {at}: check off {title}",
                payload,
                EXECUTOR,
                expires=until,
            )

    async def _to_check_off(self, today: date) -> list[tuple[str, Member, dict[str, Any]]]:
        found: list[tuple[str, Member, dict[str, Any]]] = []
        wall = self.services.wall_routines
        if wall is not None:
            try:
                items = await wall.open_matching(WORDS)
            except CozylaError as exc:
                log.warning("The wall's routines couldn't be read for the dishwasher: %s", exc)
                items = []
            for record, member in items:
                found.append(
                    (
                        f"{record.title} on the wall",
                        member or self._admin(),
                        {"routine": record.routine_id, "day": today.isoformat()},
                    )
                )
        rows = self.db.query(
            "SELECT id FROM tasks WHERE status IN ('open', 'snoozed') "
            "AND (due_on IS NULL OR due_on <= ?)",
            (today.isoformat(),),
        )
        for row in rows:
            task = self.board.get(row["id"])
            if not title_matches(WORDS, task.title):
                continue
            member = self.store.get_member(task.assignee) if task.assignee else self._admin()
            found.append((task.title, member, {"task": task.id}))
        return found

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        if "task" in payload:
            task = self.board.get(int(payload["task"]))
            await self.board.complete(task.id, ctx.member)
            return f"Checked off {task.title}."
        wall = self.services.wall_routines
        if wall is None:
            return "The wall's routines aren't connected any more, so nothing was ticked."
        await wall.tick(int(payload["routine"]), date.fromisoformat(str(payload["day"])))
        return "Ticked it on the wall."

    # ----- the pace -------------------------------------------------------------------

    async def pace(self) -> bool:
        """Scheduler job: once a day, from the evening, fewer runs than usual this week is
        a small dip for everyone. Returns whether it sent the signal."""
        now = clock.now()
        local = now.astimezone(self._tz())
        if local.time() < PACE_FROM:
            return False
        today = local.date().isoformat()
        if self.db.one("SELECT 1 FROM dishwasher_pace WHERE day = ?", (today,)):
            return False
        reading = self.reading(now)
        if reading is None:
            return False
        runs, usual = reading
        self.db.execute(
            "INSERT INTO dishwasher_pace (day, runs, usual) VALUES (?, ?, ?)", (today, runs, usual)
        )
        if usual < MIN_USUAL or runs >= usual * BEHIND:
            return False
        ran = f"ran {_times(runs)}" if runs else "hasn't run"
        note = f"the dishwasher {ran} this week, fewer than usual (about {_times(round(usual))})"
        for member in self.store.list_members():
            self.services.energy.record(member, "device_activity", PACE_SIGNAL, note)
        return True

    def reading(self, now: datetime) -> tuple[int, float] | None:
        """(runs in the last week, the usual runs a week before it), or None without a
        week of history before this one."""
        devices = self.devices("dishwasher")
        if not devices:
            return None
        week_start = now - RECENT
        known_since = min(d.created_at for d in devices)
        history = min(USUAL_OVER, week_start - known_since)
        if history < ENOUGH_HISTORY:
            return None
        ids = [d.id for d in devices]
        marks = ", ".join("?" for _ in ids)

        def count(start: datetime, end: datetime) -> int:
            return self.db.scalar(
                f"SELECT COUNT(*) FROM appliance_cycles WHERE device_id IN ({marks}) "
                "AND started_at >= ? AND started_at < ?",
                (*ids, to_utc_iso(start), to_utc_iso(end)),
            )

        before = count(week_start - history, week_start)
        return count(week_start, now), before * (RECENT / history)

    # ----- small things -------------------------------------------------------------------

    def devices(self, appliance: str | None = None) -> list[Device]:
        return [
            d
            for d in self.store.list_devices()
            if d.provider == "home_connect" and (appliance is None or d.appliance == appliance)
        ]

    def _today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _admin(self) -> Member:
        return next(m for m in self.store.list_members() if m.is_admin)


def _times(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")
