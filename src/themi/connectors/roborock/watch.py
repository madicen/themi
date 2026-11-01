"""The family's robot vacuum, watched (V1).

`devices.vacuum`, every minute: reads each robot while it's cleaning, heading home or has a
problem, and every 5 minutes otherwise; its parts' counters every 6 hours.

What it last saw is kept (`device_states` for the state in words, `vacuum_states` for its
problems and worn parts), and only a change becomes a `VacuumEvent` for the listeners (the
vacuum's chores, `themi.core.vacuum`). The first read of a robot only sets the starting
point, as with the washer (30), so linking doesn't announce an old alert. A stuck robot,
or one that didn't get home, is looked up on its map once, for the room it's in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import AccountStore, Device, Member
from themi.connectors.roborock.client import (
    LoginExpired,
    RoborockAccount,
    RoborockError,
    RoborockSession,
    RobotOffline,
)
from themi.connectors.roborock.events import (
    NOT_DOCKED,
    PART,
    STUCK,
    VacuumEvent,
    VacuumStatus,
    low_parts,
    problems,
    read_status,
    state_word,
    unknown_codes,
)
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

PROVIDER = "roborock"
CALM_EVERY = timedelta(minutes=5)  # docked and fine; busy or in trouble: every run (1 minute)
PARTS_EVERY = timedelta(hours=6)
WHERE_KINDS = (STUCK, NOT_DOCKED)  # the problems worth a room

VacuumListener = Callable[[VacuumEvent], Awaitable[None]]


class RoborockWatcher:
    def __init__(self, store: AccountStore, account: RoborockAccount) -> None:
        self.store = store
        self.db = store.db
        self.account = account
        self.listeners: list[VacuumListener] = []
        # Told once when the sign-in stops working (the vacuum's chores tell the admins).
        self.expired_listeners: list[Callable[[str], Awaitable[None]]] = []
        self._read_at: dict[int, datetime] = {}
        self._parts_at: dict[int, datetime] = {}
        self._logged: set[str] = set()

    # ----- linking (the Family page) ---------------------------------------------------

    async def send_code(self, email: str) -> str:
        return await self.account.send_code(email)

    async def link(self, by: Member, email: str, code: str) -> list[Device]:
        """Keep the sign-in and add the robots it can see (new ones only)."""
        found = await self.account.link(by, email, code)
        known = {d.external_id for d in self.devices()}
        self._read_at.clear()
        return [
            self.store.add_device(by, PROVIDER, robot.duid, robot.name, "vacuum")
            for robot in found
            if robot.duid not in known
        ]

    async def unlink(self) -> None:
        await self.account.unlink()
        self._read_at.clear()
        self._parts_at.clear()

    def devices(self) -> list[Device]:
        return [d for d in self.store.list_devices() if d.provider == PROVIDER]

    def states(self) -> dict[int, str]:
        ids = {d.id for d in self.devices()}
        rows = self.db.query("SELECT device_id, state FROM device_states")
        return {r["device_id"]: r["state"] for r in rows if r["device_id"] in ids}

    # ----- the job --------------------------------------------------------------------

    async def poll(self) -> int:
        """Scheduler job: read each robot that's due. Returns how many events."""
        if not self.account.linked() or self.account.problem():
            return 0
        events = 0
        for device in self.devices():
            if device.appliance != "vacuum" or not self._due(device):
                continue
            try:
                session = await self.account.session()
                status = read_status(await session.status(device.external_id))
                self._read_at[device.id] = clock.now()
                events += await self._saw(device, status, session)
                if self._parts_due(device):
                    counters = await session.consumables(device.external_id)
                    self._parts_at[device.id] = clock.now()
                    events += await self._parts(device, counters)
            except LoginExpired as exc:
                await self._expired(str(exc))
                return events
            except RobotOffline:
                self._read_at[device.id] = clock.now()
                self._keep_word(device, "offline")
            except RoborockError as exc:
                log.warning("Couldn't read the vacuum %s: %s", device.name, exc)
        return events

    async def read(self, device: Device) -> VacuumStatus:
        """Asked how it's doing: its status read now (and kept, as a poll would; its
        events go out too). RoborockError when it can't be read."""
        try:
            session = await self.account.session()
            status = read_status(await session.status(device.external_id))
        except LoginExpired as exc:
            await self._expired(str(exc))
            raise
        self._read_at[device.id] = clock.now()
        await self._saw(device, status, session)
        return status

    async def resolve(self, device: Device, code: int) -> None:
        session = await self.account.session()
        await session.resolve(device.external_id, code)
        self._read_at.pop(device.id, None)  # read it again on the next run

    async def send_home(self, device: Device) -> None:
        session = await self.account.session()
        await session.send_home(device.external_id)
        self._read_at.pop(device.id, None)

    def problems(self, device: Device) -> dict[str, str]:
        """The problems it had when last read."""
        row = self._row(device)
        return dict(json.loads(row["problems"])) if row else {}

    # ----- what changed -----------------------------------------------------------------

    async def _saw(self, device: Device, status: VacuumStatus, session: RoborockSession) -> int:
        self._keep_word(device, state_word(status))
        for code in unknown_codes(status):
            if code not in self._logged:
                self._logged.add(code)
                log.warning("The vacuum reported %s, which Themi has no words for", code)
        now = clock.now()
        current = problems(status)
        row = self._row(device)
        if row is None:  # the starting point
            self.db.execute(
                "INSERT INTO vacuum_states (device_id, problems, parts, seen_at) "
                "VALUES (?, ?, '{}', ?)",
                (device.id, json.dumps(current), to_utc_iso(now)),
            )
            return 0
        before: dict[str, str] = json.loads(row["problems"])
        self.db.execute(
            "UPDATE vacuum_states SET problems = ?, seen_at = ? WHERE device_id = ?",
            (json.dumps(current), to_utc_iso(now), device.id),
        )
        events = []
        for kind, detail in before.items():
            if kind not in current:
                events.append(VacuumEvent(device.id, kind, detail, now, gone=True))
        for kind, detail in current.items():
            if kind not in before:
                room = await self._room(session, device) if kind in WHERE_KINDS else None
                events.append(VacuumEvent(device.id, kind, detail, now, room=room))
        for event in events:
            await self._tell(event)
        return len(events)

    async def _parts(self, device: Device, counters: dict[str, int]) -> int:
        row = self._row(device)
        if row is None:
            return 0
        before: dict[str, str] = json.loads(row["parts"])
        low = low_parts(counters)
        self.db.execute(
            "UPDATE vacuum_states SET parts = ? WHERE device_id = ?", (json.dumps(low), device.id)
        )
        if row["parts_read"] == 0:  # the parts' starting point
            self.db.execute(
                "UPDATE vacuum_states SET parts_read = 1 WHERE device_id = ?", (device.id,)
            )
            return 0
        now = clock.now()
        events = [
            VacuumEvent(device.id, PART, part, now, gone=True)
            for name, part in before.items()
            if name not in low
        ] + [
            VacuumEvent(device.id, PART, part, now)
            for name, part in low.items()
            if name not in before
        ]
        for event in events:
            await self._tell(event)
        return len(events)

    async def _room(self, session: RoborockSession, device: Device) -> str | None:
        try:
            return await session.room(device.external_id)
        except RoborockError as exc:
            log.info("Couldn't find which room the vacuum is in: %s", exc)
            return None

    async def _tell(self, event: VacuumEvent) -> None:
        for listener in self.listeners:
            try:
                await listener(event)
            except Exception:
                log.exception("A vacuum listener failed for %s", event)

    async def _expired(self, why: str) -> None:
        log.warning("The Roborock sign-in stopped working: %s", why)
        await self.account.close()
        if self.account.expired(why):
            for listener in self.expired_listeners:
                try:
                    await listener(why)
                except Exception:
                    log.exception("Telling about the Roborock sign-in failed")

    # ----- small things -------------------------------------------------------------------

    def _due(self, device: Device) -> bool:
        last = self._read_at.get(device.id)
        if last is None:
            return True
        # On its dock (a dock alert or not) or offline, it can wait; moving, or stopped
        # somewhere, it's read every run.
        word = self.states().get(device.id)
        busy = word not in (None, "on its dock", "charging on its dock", "offline")
        return busy or clock.now() >= last + CALM_EVERY

    def _parts_due(self, device: Device) -> bool:
        last = self._parts_at.get(device.id)
        return last is None or clock.now() >= last + PARTS_EVERY

    def _keep_word(self, device: Device, word: str) -> None:
        self.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET state = excluded.state, "
            "seen_at = excluded.seen_at",
            (device.id, word, to_utc_iso(clock.now())),
        )

    def _row(self, device: Device) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM vacuum_states WHERE device_id = ?", (device.id,))
