"""The oven: what Themi tells and does with the range's two ovens (OV3, the Oven Module Plan).

The connector (`themi_home.connectors.smarthq`) reads and writes the ovens; this decides who
hears what and puts every write through the trust tiers:

- `oven_heat` (preheat, proof, a new temperature): never automatic (capped). The tap on the
  cook screen or a card is the person's yes: Themi stages it and approves it as them, so the
  audit has it and no second card asks again (approvals hold the category). A heat card
  older than `STALE` is refused, and the oven as it is now is said instead.
- `oven_timer` (the oven's kitchen timer): asked by default, a rule may make it automatic.
  A tap is the request.
- `oven_off`: automatic from the start, so turning an oven off never waits on anyone. It's
  still staged, so it's in the audit. If staging ever left it waiting (an anomaly
  escalation), the person is told to turn it off at the range.

What people hear, through the outbox, once per heat-up (`oven_heatups`):

- "The lower oven's preheated to 400°F.", to whoever started it through Themi.
- "The oven timer's done.", to whoever set it through Themi, unless a cook-screen timer
  covers it (OV5): then that one says it.
- The probe nearing its target and reaching it, to whoever's cooking with that oven, else
  everyone.
- Left on: still on when the first person's quiet hours begin, or 30 minutes after a cook
  session ended. Everyone hears it, with [Turn it off] [It's fine]. [It's fine] holds it
  until the next heat-up.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.autonomy import Decision
from themi.channels.events import Button
from themi.channels.outbox import Priority
from themi.core.services import Services
from themi.localtime import in_quiet_hours, quiet_hours_start, to_utc_iso
from themi_home.connectors.smarthq import (
    LOWER,
    UPPER,
    Oven,
    OvenReading,
    OvenRefused,
    OvenWatcher,
    SmartHQError,
)
from themi_home.connectors.smarthq import events as ov

if TYPE_CHECKING:
    from themi.autonomy.engine import ExecutionContext
    from themi.core.approvals import ApprovalsUI

log = logging.getLogger(__name__)

HEAT_CATEGORY, HEAT = "oven_heat", "devices.oven_heat"
TIMER_CATEGORY, TIMER = "oven_timer", "devices.oven_timer"
OFF_CATEGORY, OFF = "oven_off", "devices.oven_off"
BUTTON = "oven"
STALE = timedelta(minutes=10)  # a heat card older than this is refused, and refreshed
LEFT_ON_AFTER = timedelta(minutes=30)  # after a cook session ended
PROBE_NEAR_F = 5
STARTED_WITHIN = timedelta(minutes=5)  # a heat-up begun this soon after Themi's write is its


@dataclass(frozen=True)
class Said:
    """What a tap did, in words for the person."""

    ok: bool
    words: str


class OvenControl:
    def __init__(self, services: Services, watcher: OvenWatcher, approvals: ApprovalsUI) -> None:
        self.services = services
        self.watcher = watcher
        self.approvals = approvals
        self.db = services.store.db
        self.autonomy = services.autonomy
        self._why: dict[int, str] = {}  # action id -> why the oven refused, for the person
        self._following = False  # OV5: syncing the oven's timer (its own reads come back here)

    def install(self) -> None:
        # The tap is the yes (or the request): no card in the chat for these.
        self.approvals.held.update({HEAT_CATEGORY, TIMER_CATEGORY})
        self.autonomy.executors.register(HEAT)(self._heat)
        self.autonomy.executors.register(TIMER)(self._timer)
        self.autonomy.executors.register(OFF)(self._off)
        self.watcher.listeners.append(self.on_reading)
        self.watcher.lost_listeners.append(self.on_lost)
        self.services.button_handlers[BUTTON] = self.on_button

    # ----- what the cook screen and the cards call -------------------------------------

    def linked(self) -> bool:
        return self.watcher.account.linked() and bool(self.watcher.ovens())

    def oven(self, cavity: str) -> Oven | None:
        return self.watcher.oven(cavity)

    def for_mode(self, mode: int) -> Oven | None:
        """The oven that does this mode (the lower for convection; the upper for Proof); for
        Bake, the lower oven, the bigger one."""
        if mode == ov.PROOF:
            return self.oven(UPPER)
        return self.oven(LOWER) if mode in ov.OFFERS[LOWER] else self.oven(UPPER)

    async def heat(
        self,
        member: Member,
        oven: Oven,
        mode: int,
        temp_f: int,
        *,
        offered_at: datetime | None = None,
        session_id: int | None = None,
    ) -> Said:
        """Preheat (or proof): staged in `oven_heat` and approved by this tap."""
        if offered_at is not None and clock.now() - offered_at > STALE:
            return Said(False, f"That was a while ago, so I've left it. {await self.now(oven)}")
        why = self.watcher.can_heat(oven, mode, temp_f)
        if why:
            return Said(False, why)
        last = self.watcher.last(oven)
        if last is not None and last.on and last.mode == mode and last.set_f == temp_f:
            return Said(True, f"The {oven.name} is already on {ov.state_words(last)}.")
        doing = f"{ov.mode_words(mode)} at {temp_f}°F" if mode != ov.PROOF else "Proof (85°F)"
        payload = {"oven": oven.cavity, "mode": mode, "temp_f": temp_f, "session": session_id}
        staged = await self.autonomy.stage(
            HEAT_CATEGORY, member, f"Start the {oven.name} on {doing}", payload, HEAT,
            interactive=True,
        )  # fmt: skip
        outcome = staged
        if staged.action.status == "pending":  # capped: always asks, and this tap answered
            outcome = await self.autonomy.resolve(staged.action.id, Decision.APPROVE, by=member)
        return self._said(outcome.action.id, outcome.action.status, outcome.message)

    async def set_timer(self, member: Member, minutes: int, *, link: int | None = None) -> Said:
        """The upper oven's kitchen timer (`link`: the cook-screen timer it goes with, OV5)."""
        oven = self.oven(ov.TIMER_OVEN)
        if oven is None:
            return Said(False, "Themi can't see the oven.")
        what = f"Set the oven's timer for {minutes} minutes" if minutes else "Clear the oven timer"
        outcome = await self.autonomy.stage(
            TIMER_CATEGORY, member, what, {"minutes": minutes, "link": link}, TIMER,
            interactive=True, requested=True,
        )  # fmt: skip
        if outcome.action.status == "pending":
            return Said(False, f"Waiting on your yes: {what}.")
        return self._said(outcome.action.id, outcome.action.status, outcome.message)

    async def off(self, member: Member, oven: Oven) -> Said:
        """Turn it off: `oven_off`, automatic, so it never waits."""
        outcome = await self.autonomy.stage(
            OFF_CATEGORY, member, f"Turn the {oven.name} off", {"oven": oven.cavity}, OFF,
            interactive=True, requested=True,
        )  # fmt: skip
        if outcome.action.status == "pending":  # escalated: don't leave it to a card
            return Said(False, f"I couldn't turn the {oven.name} off. Turn it off on the range.")
        return self._said(outcome.action.id, outcome.action.status, outcome.message)

    async def now(self, oven: Oven) -> str:
        """The oven as it is, in a sentence."""
        try:
            reading = await self.watcher.read(oven)
        except SmartHQError:
            return f"I can't read the {oven.name} right now."
        return f"The {oven.name} is {ov.state_words(reading)}."

    def _said(self, action_id: int, status: str, message: str) -> Said:
        if status == "done":
            return Said(True, message)
        why = self._why.pop(action_id, None)
        return Said(False, why or message)

    # ----- the executors ------------------------------------------------------------------

    async def _heat(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        oven = self._oven(payload)
        try:
            reading = await self.watcher.heat(
                oven, int(payload["mode"]), int(payload["temp_f"]), ctx.member
            )
        except OvenRefused as exc:
            self._why[ctx.action_id] = str(exc)
            raise
        self._heatup(oven, reading, ctx.member, payload.get("session"))
        if reading.state == ov.STATE_PROOF:
            return f"The {oven.name} is on Proof (85°F)."
        return f"The {oven.name} is preheating to {reading.set_f}°F."

    async def _timer(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        oven = self.oven(ov.TIMER_OVEN)
        if oven is None:
            raise SmartHQError("no oven")
        minutes = int(payload["minutes"])
        try:
            await self.watcher.set_timer(oven, minutes, ctx.member)
        except OvenRefused as exc:
            self._why[ctx.action_id] = str(exc)
            raise
        self.db.execute(
            "INSERT INTO oven_timers (oven_id, member_id, minutes, cooking_timer_id, set_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (oven.id, ctx.member.id, minutes, payload.get("link"), to_utc_iso(clock.now())),
        )
        if not minutes:
            return "The oven timer's cleared."
        return f"The oven's timer is set for {_minutes(minutes)}."

    async def _off(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        oven = self._oven(payload)
        try:
            await self.watcher.off(oven, ctx.member)
        except OvenRefused as exc:
            self._why[ctx.action_id] = str(exc)
            raise
        return f"The {oven.name} is off."

    def _oven(self, payload: dict[str, Any]) -> Oven:
        oven = self.oven(str(payload["oven"]))
        if oven is None:
            raise SmartHQError("That oven isn't linked any more.")
        return oven

    # ----- heat-ups -------------------------------------------------------------------------

    def _heatup(
        self, oven: Oven, reading: OvenReading, member: Member | None, session: Any = None
    ) -> int:
        """The open heat-up for this oven, started now if there's none; Themi's write names
        who started it."""
        row = self.open_heatup(oven)
        if row is not None:
            if member is not None and row["member_id"] is None:
                self.db.execute(
                    "UPDATE oven_heatups SET member_id = ?, session_id = ? WHERE id = ?",
                    (member.id, session, row["id"]),
                )
            return int(row["id"])
        return self.db.execute(
            "INSERT INTO oven_heatups (oven_id, member_id, session_id, mode, set_f, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                oven.id,
                member.id if member else None,
                session,
                reading.mode,
                reading.set_f,
                to_utc_iso(clock.now()),
            ),
        )

    def open_heatup(self, oven: Oven) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM oven_heatups WHERE oven_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (oven.id,),
        )

    def started_by(self, oven: Oven) -> Member | None:
        """Who started the oven's current heat-up through Themi, if anyone did."""
        row = self.open_heatup(oven)
        if row is None or row["member_id"] is None:
            return None
        return self.services.store.get_member(int(row["member_id"]))

    # ----- what the oven says ------------------------------------------------------------

    async def on_reading(self, oven: Oven, before: OvenReading | None, now: OvenReading) -> None:
        if now.on:
            self._heatup(oven, now, None)
        else:
            self.db.execute(
                "UPDATE oven_heatups SET ended_at = ? WHERE oven_id = ? AND ended_at IS NULL",
                (to_utc_iso(clock.now()), oven.id),
            )
        if before is None:
            return  # the starting point: nothing to tell
        heatup = self.open_heatup(oven)
        if heatup is not None and before.preheating and now.heated and now.state in ov.COOKING:
            await self._preheated(oven, now, heatup)
        if before.timer_minutes and not now.timer_minutes:
            await self._timer_done(oven)
        if oven.cavity == ov.TIMER_OVEN:
            await self._follow_cook_timers(oven)
        if heatup is not None and now.probe_f is not None and now.probe_target_f:
            await self._probe(oven, now, heatup)

    async def _preheated(self, oven: Oven, now: OvenReading, heatup: dict[str, Any]) -> None:
        if heatup["preheated_at"] or heatup["member_id"] is None:
            return  # started at the range: whoever did is standing at it
        self.db.execute(
            "UPDATE oven_heatups SET preheated_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), heatup["id"]),
        )
        member = self.services.store.get_member(int(heatup["member_id"]))
        await self.services.outbox.send(
            member,
            f"The {oven.name}'s preheated to {now.set_f}°F.",
            priority=Priority.URGENT,  # they asked for it
            kind="oven",
            dedupe_key=f"oven-preheated-{heatup['id']}",
        )

    async def _timer_done(self, oven: Oven) -> None:
        row = self.db.one(
            "SELECT * FROM oven_timers WHERE oven_id = ? AND minutes > 0 AND done_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (oven.id,),
        )
        if row is None:
            return  # set at the range: it beeps there
        self.db.execute(
            "UPDATE oven_timers SET done_at = ? WHERE id = ?", (to_utc_iso(clock.now()), row["id"])
        )
        if row["cooking_timer_id"] is not None:  # OV5: the cook screen's own timer says it
            early = datetime.fromisoformat(row["set_at"]) + timedelta(minutes=row["minutes"])
            if early - clock.now() > timedelta(minutes=1):  # cleared at the range: both go
                self.db.execute(
                    "UPDATE cooking_timers SET cancelled_at = ? WHERE id = ? "
                    "AND fired_at IS NULL AND cancelled_at IS NULL",
                    (to_utc_iso(clock.now()), row["cooking_timer_id"]),
                )
            return
        member = self.services.store.get_member(int(row["member_id"]))
        await self.services.outbox.send(
            member,
            "The oven timer's done.",
            priority=Priority.URGENT,
            kind="oven",
            dedupe_key=f"oven-timer-{row['id']}",
        )

    async def _follow_cook_timers(self, oven: Oven) -> None:
        """OV5: a cook-screen timer cancelled clears the oven's; one given more time moves
        the oven's to match."""
        if self._following:
            return
        self._following = True
        try:
            for row in self.db.query(
                "SELECT t.*, c.cancelled_at AS c_cancelled, c.fired_at AS c_fired, "
                "c.ends_at AS c_ends FROM oven_timers t JOIN cooking_timers c "
                "ON c.id = t.cooking_timer_id WHERE t.oven_id = ? AND t.minutes > 0 "
                "AND t.done_at IS NULL",
                (oven.id,),
            ):
                member = self.services.store.get_member(int(row["member_id"]))
                if row["c_fired"]:
                    continue  # it ended: the oven's ends with it
                expected = datetime.fromisoformat(row["set_at"]) + timedelta(minutes=row["minutes"])
                if row["c_cancelled"]:
                    minutes = 0
                elif datetime.fromisoformat(row["c_ends"]) - expected >= timedelta(minutes=1):
                    left = datetime.fromisoformat(row["c_ends"]) - clock.now()
                    minutes = max(1, math.ceil(left.total_seconds() / 60))
                else:
                    continue
                self.db.execute(
                    "UPDATE oven_timers SET done_at = ? WHERE id = ?",
                    (to_utc_iso(clock.now()), row["id"]),
                )
                await self.set_timer(member, minutes, link=row["cooking_timer_id"] or None)
        finally:
            self._following = False

    async def _probe(self, oven: Oven, now: OvenReading, heatup: dict[str, Any]) -> None:
        assert now.probe_f is not None and now.probe_target_f
        target = now.probe_target_f
        if now.probe_f >= target and not heatup["probe_done_at"]:
            column, text = "probe_done_at", f"The probe's reached {target}°F."
        elif now.probe_f >= target - PROBE_NEAR_F and not heatup["probe_near_at"]:
            column, text = (
                "probe_near_at",
                f"The probe's at {now.probe_f}°F; the target is {target}°F.",
            )
        else:
            return
        if column == "probe_done_at" and not heatup["probe_near_at"]:
            self.db.execute(
                "UPDATE oven_heatups SET probe_near_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), heatup["id"]),
            )
        self.db.execute(
            f"UPDATE oven_heatups SET {column} = ? WHERE id = ?",
            (to_utc_iso(clock.now()), heatup["id"]),
        )
        for member in self._cooks(oven, heatup):
            await self.services.outbox.send(
                member, text, priority=Priority.URGENT, kind="oven",
                dedupe_key=f"oven-{column}-{heatup['id']}-{member.id}",
            )  # fmt: skip

    def _cooks(self, oven: Oven, heatup: dict[str, Any]) -> list[Member]:
        """Whoever's cooking with this oven: who started it through Themi, else everyone."""
        if heatup["member_id"] is not None:
            return [self.services.store.get_member(int(heatup["member_id"]))]
        return self.services.store.list_members()

    # ----- left on ------------------------------------------------------------------------

    async def left_on(self) -> int:
        """Scheduler job: an oven still on when the first person's quiet hours begin, or 30
        minutes after a cook session ended, is told to everyone, once per heat-up."""
        told = 0
        for oven in self.watcher.ovens():
            heatup = self.open_heatup(oven)
            last = self.watcher.last(oven)
            if heatup is None or last is None or not last.on:
                continue
            if heatup["warned_at"] or heatup["fine_at"]:
                continue
            started = datetime.fromisoformat(heatup["started_at"])
            if not (self._bedtime_since(started) or self._session_ended_since(started)):
                continue
            await self._warn(oven, last, heatup)
            told += 1
        return told

    def _bedtime_since(self, started: datetime) -> bool:
        family = self.services.store.get_family()
        zone = family.timezone if family else "UTC"
        now = clock.now()
        for member in self.services.store.list_members():
            if in_quiet_hours(member, now, zone) and quiet_hours_start(member, now, zone) > started:
                return True
        return False

    def _session_ended_since(self, started: datetime) -> bool:
        ended = self.db.scalar(
            "SELECT MAX(ended_at) FROM cooking_sessions WHERE ended_at IS NOT NULL "
            "AND ended_at >= ?",
            (to_utc_iso(started),),
        )
        return bool(ended) and clock.now() - datetime.fromisoformat(str(ended)) >= LEFT_ON_AFTER

    async def _warn(self, oven: Oven, last: OvenReading, heatup: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE oven_heatups SET warned_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), heatup["id"]),
        )
        tap = {"heatup": heatup["id"], "oven": oven.cavity}
        buttons = [
            Button("Turn it off", BUTTON, {**tap, "do": "off"}),
            Button("It's fine", BUTTON, {**tap, "do": "fine"}),
        ]
        text = f"The {oven.name} is still on ({ov.state_words(last)})."
        for member in self.services.store.list_members():
            await self.services.outbox.send(
                member, text, priority=Priority.URGENT, buttons=buttons, kind="oven",
                dedupe_key=f"oven-left-on-{heatup['id']}-{member.id}",
            )  # fmt: skip

    async def on_button(self, event: Any) -> None:
        payload = event.button.payload
        member = self.services.store.get_member(event.member.id)
        oven = self.oven(str(payload.get("oven", "")))
        if oven is None:
            return
        if payload.get("do") == "off":
            said = await self.off(member, oven)
            result = said.words
        else:
            self.db.execute(
                "UPDATE oven_heatups SET fine_at = ? WHERE id = ? AND fine_at IS NULL",
                (to_utc_iso(clock.now()), int(payload.get("heatup") or 0)),
            )
            result = f"Okay, leaving the {oven.name} on."
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, result)
        else:
            await self.services.outbox.send(member, result, priority=Priority.REPLY, kind="oven")

    async def on_lost(self, why: str) -> None:
        for member in self.services.store.list_members():
            if member.is_admin:
                await self.services.outbox.send(
                    member,
                    "SmartHQ stopped accepting Themi's sign-in, so Themi can't see or turn off "
                    "the oven. Sign in again on the website's Accounts page.",
                    priority=Priority.NORMAL,
                    kind="oven",
                    dedupe_key="oven-sign-in-lost",
                )


def _minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    return f"{hours} hour{'s' if hours != 1 else ''}" + (f" {rest} minutes" if rest else "")
