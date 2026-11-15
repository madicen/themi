"""The family's range, watched and written (OV2).

The range is one SmartHQ appliance with two ovens, kept in `ovens` (one row each, by its
cavity). `devices.oven`, every 30 seconds, reads both from what the range last pushed and
keeps the newest in `oven_readings`; what changed goes to the listeners (OV3's notices).

Writes (`heat`, `set_timer`, `off`) send the raw ERD, then wait up to `CONFIRM_WITHIN` for
the oven's own state to show it took. A refused write still echoes its cook mode for a
while (OV1), so `CURRENT_STATE` is what counts. Each write is kept in `oven_actions`, with
who asked and what the oven showed after.

Nothing here decides whether a write may happen: that's the trust tiers' job, in
`themi_home.oven`. This only refuses what the oven can't do (a mode the oven doesn't offer,
a temperature out of its range, Proof at anything but 85°F).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi_home.connectors.smarthq import events
from themi_home.connectors.smarthq.client import (
    RangeOffline,
    SignInLost,
    SmartHQAccount,
    SmartHQError,
    SmartHQSession,
)
from themi_home.connectors.smarthq.events import (
    CAVITIES,
    COOK_MODE,
    KITCHEN_TIMER,
    NAMES,
    OFFERS,
    PROOF,
    PROOF_F,
    TIMER_OVEN,
    OvenReading,
)

log = logging.getLogger(__name__)

CONFIRM_WITHIN = 30.0  # seconds for the oven's state to show a write took
CONFIRM_EVERY = 2.0
MAX_TIMER_MINUTES = 9 * 60 + 59

ReadingListener = Callable[["Oven", OvenReading | None, OvenReading], Awaitable[None]]


@dataclass(frozen=True)
class Oven:
    id: int
    mac: str
    cavity: str  # upper / lower
    model: str

    @property
    def name(self) -> str:
        return NAMES[self.cavity]

    @property
    def title(self) -> str:
        return self.name[0].upper() + self.name[1:]


class OvenRefused(SmartHQError):
    """The oven can't do that (not this oven's mode, out of its range, Remote Enable off),
    or didn't show it took. The words are for the person."""


class OvenWatcher:
    def __init__(self, account: SmartHQAccount) -> None:
        self.account = account
        self.db = account.db
        self.listeners: list[ReadingListener] = []
        # Told once when the sign-in stops working (the oven's notices tell the admins).
        self.lost_listeners: list[Callable[[str], Awaitable[None]]] = []

    # ----- linking (the Accounts page) -------------------------------------------------

    async def sign_in(self, by: Member, email: str, password: str, region: str) -> bool:
        """True when it's linked; False when SmartHQ emailed a code to finish with."""
        step = await self.account.sign_in(by, email, password, region)
        if step.token is None:
            return False
        await self._find_ovens()
        return True

    async def submit_code(self, by: Member, email: str, code: str) -> None:
        await self.account.submit_code(by, email, code)
        await self._find_ovens()

    async def unlink(self) -> None:
        await self.account.unlink()

    async def _find_ovens(self) -> None:
        session = await self.account.session()
        known = {(o.mac, o.cavity) for o in self.ovens()}
        for found in await session.ranges():
            for cavity in CAVITIES:
                if (found.mac, cavity) not in known:
                    self.db.execute(
                        "INSERT INTO ovens (mac, cavity, model, created_at) VALUES (?, ?, ?, ?)",
                        (found.mac, cavity, found.model, to_utc_iso(clock.now())),
                    )

    def ovens(self) -> list[Oven]:
        rows = self.db.query("SELECT * FROM ovens ORDER BY id")
        return [Oven(r["id"], r["mac"], r["cavity"], r["model"]) for r in rows]

    def oven(self, cavity: str) -> Oven | None:
        return next((o for o in self.ovens() if o.cavity == cavity), None)

    # ----- reading ----------------------------------------------------------------------

    async def read(self, oven: Oven) -> OvenReading:
        """Read now (from what the range last pushed), and keep it as a poll would.
        SmartHQError when it can't be read."""
        reading = await self._read(oven)
        await self._saw(oven, reading)
        return reading

    def last(self, oven: Oven) -> OvenReading | None:
        """What the oven showed when last read, without reading it."""
        row = self.db.one("SELECT * FROM oven_readings WHERE oven_id = ?", (oven.id,))
        if row is None:
            return None
        return OvenReading(
            cavity=oven.cavity,
            state=row["state"],
            mode=row["mode"],
            set_f=row["set_f"],
            temp_f=row["temp_f"],
            timer_minutes=row["timer_minutes"],
            cook_minutes_left=row["cook_minutes_left"],
            remote=bool(row["remote"]),
            probe_f=row["probe_f"],
            read_at=datetime.fromisoformat(row["read_at"]),
        )

    async def poll(self) -> int:
        """Scheduler job: read both ovens. Returns how many were read."""
        if not self.account.linked() or self.account.problem():
            return 0
        count = 0
        for oven in self.ovens():
            try:
                reading = await self._read(oven)
            except SignInLost:
                return count
            except SmartHQError as exc:
                log.info("Couldn't read the %s: %s", oven.name, exc)
                continue
            await self._saw(oven, reading)
            count += 1
        return count

    async def _read(self, oven: Oven) -> OvenReading:
        session = await self._session()
        try:
            raw = await session.erds(oven.mac)
        except SignInLost as exc:
            await self._lost(str(exc))
            raise
        finally:
            self.account.keep_token()
        if events.code(oven.cavity, COOK_MODE) not in raw:
            raise RangeOffline("The range hasn't reported yet.")
        return events.read(oven.cavity, raw, clock.now())

    async def _saw(self, oven: Oven, reading: OvenReading) -> None:
        before = self.last(oven)
        self.db.execute(
            "INSERT INTO oven_readings (oven_id, state, mode, set_f, temp_f, timer_minutes, "
            "cook_minutes_left, remote, probe_f, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(oven_id) DO UPDATE SET state = excluded.state, mode = excluded.mode, "
            "set_f = excluded.set_f, temp_f = excluded.temp_f, "
            "timer_minutes = excluded.timer_minutes, "
            "cook_minutes_left = excluded.cook_minutes_left, remote = excluded.remote, "
            "probe_f = excluded.probe_f, read_at = excluded.read_at",
            (
                oven.id,
                reading.state,
                reading.mode,
                reading.set_f,
                reading.temp_f,
                reading.timer_minutes,
                reading.cook_minutes_left,
                int(reading.remote),
                reading.probe_f,
                to_utc_iso(reading.read_at or clock.now()),
            ),
        )
        for listener in self.listeners:
            try:
                await listener(oven, before, reading)
            except Exception:
                log.exception("An oven listener failed for the %s", oven.name)

    # ----- writing ----------------------------------------------------------------------

    def can_heat(self, oven: Oven, mode: int, temp_f: int) -> str | None:
        """Why the oven can't do this, in words for a person; None when it can."""
        if mode not in OFFERS[oven.cavity]:
            where = [o.name for o in self.ovens() if mode in OFFERS[o.cavity]]
            also = f" (the {where[0]} does)" if where else ""
            return f"The {oven.name} doesn't do {events.mode_words(mode)}{also}."
        if mode == PROOF:
            return None if temp_f == PROOF_F else "Proof only runs at 85°F."
        if not events.LOWEST_F <= temp_f <= events.HIGHEST_F:
            return f"The oven sets {events.LOWEST_F}°F to {events.HIGHEST_F}°F."
        return None

    async def heat(self, oven: Oven, mode: int, temp_f: int, by: Member) -> OvenReading:
        """Start the oven on a mode and temperature; the reading once it shows it took.
        OvenRefused when it can't, or doesn't (Remote Enable off: it says so)."""
        why = self.can_heat(oven, mode, temp_f)
        if why:
            raise OvenRefused(why)
        before = await self.read(oven)
        if not before.remote:
            raise OvenRefused(
                f"Remote Enable is off, so the {oven.name} won't start from here. Press and "
                "hold Remote Enable on the range, then try again."
            )
        value = events.cook_value(mode, temp_f)
        reading = await self._write(
            oven, "heat", COOK_MODE, value, by, lambda r: r.on and r.mode == mode
        )
        if reading is None:
            raise OvenRefused(
                f"The {oven.name} didn't start. Check Remote Enable on the range and try again."
            )
        return reading

    async def set_timer(self, oven: Oven, minutes: int, by: Member) -> OvenReading:
        """The oven's own kitchen timer (only the upper oven has one); 0 clears it."""
        if oven.cavity != TIMER_OVEN:
            raise OvenRefused(f"The {oven.name} has no kitchen timer.")
        if not 0 <= minutes <= MAX_TIMER_MINUTES:
            raise OvenRefused("The oven's timer goes up to 9 hours 59 minutes.")
        reading = await self._write(
            oven,
            "timer",
            KITCHEN_TIMER,
            events.timer_value(minutes),
            by,
            # it reads back in whole minutes, rounded up, and runs down meanwhile
            lambda r: (
                r.timer_minutes is not None
                and (r.timer_minutes == 0 if minutes == 0 else 0 < r.timer_minutes <= minutes)
            ),
        )
        if reading is None:
            raise OvenRefused("The oven's timer didn't take. Try again on the range.")
        return reading

    async def off(self, oven: Oven, by: Member | None) -> OvenReading:
        """Turn it off. Never refused for Remote Enable: a cooking oven takes a remote off."""
        reading = await self._write(
            oven, "off", COOK_MODE, events.OFF_VALUE, by, lambda r: not r.on
        )
        if reading is None:
            raise OvenRefused(f"The {oven.name} didn't turn off. Turn it off on the range, please.")
        return reading

    async def _write(
        self,
        oven: Oven,
        what: str,
        erd: int,
        value: str,
        by: Member | None,
        took: Callable[[OvenReading], bool],
    ) -> OvenReading | None:
        session = await self._session()
        await session.write(oven.mac, events.code(oven.cavity, erd), value)
        action = self.db.execute(
            "INSERT INTO oven_actions (oven_id, what, value, member_id, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (oven.id, what, value, by.id if by else None, to_utc_iso(clock.now())),
        )
        waited, reading = 0.0, None
        while True:
            reading = await self.read(oven)
            if took(reading):
                break
            if waited >= CONFIRM_WITHIN:
                reading = None
                break
            await self.account.login.settle(CONFIRM_EVERY)
            waited += CONFIRM_EVERY
        self.db.execute(
            "UPDATE oven_actions SET took = ?, state_after = ?, checked_at = ? WHERE id = ?",
            (
                int(reading is not None),
                reading.state if reading else None,
                to_utc_iso(clock.now()),
                action,
            ),
        )
        return reading

    # ----- small things -----------------------------------------------------------------

    async def _session(self) -> SmartHQSession:
        try:
            return await self.account.session()
        except SignInLost as exc:
            await self._lost(str(exc))
            raise

    async def _lost(self, why: str) -> None:
        log.warning("The SmartHQ sign-in stopped working: %s", why)
        await self.account.close()
        if self.account.lost(why):
            for listener in self.lost_listeners:
                try:
                    await listener(why)
                except Exception:
                    log.exception("Telling about the SmartHQ sign-in failed")

    def actions(self, oven: Oven) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM oven_actions WHERE oven_id = ? ORDER BY id", (oven.id,))
