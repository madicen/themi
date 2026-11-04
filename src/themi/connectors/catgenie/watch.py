"""The family's litter box, watched (CG1a).

`devices.litter_box`, every 10 minutes: one call lists the litter boxes with all they
report, and one reads the app's notifications. About 290 calls a day, however many boxes.

Each box's raw report is kept (`catgenie_devices`), and each notification once
(`catgenie_notifications`), so they can be looked at and captured (`themi catgenie
capture`). What a box needs (`litter_states`) is kept too, and only a change becomes a
`LitterBoxEvent` for the listeners (its chores, `themi.core.litter_box`); the first read is
only the starting point, as with the washer (30) and the feeders (32). A notification that
names an error is a problem from then until the box is seen to clean again after it.

Every read is also handed to the reading listeners (the granules' count of cycles).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from themi import clock
from themi.accounts import AccountStore, Device, Member
from themi.connectors.catgenie.client import CatGenieAccount, CatGenieError, SignInLost
from themi.connectors.catgenie.events import (
    ALERT,
    CODES,
    Alert,
    LitterBoxEvent,
    LitterBoxReading,
    error_words,
    read_alert,
    read_device,
    state_word,
)
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

PROVIDER = "catgenie"
APPLIANCE = "litter_box"
# What a capture leaves out: who and where it is.
PRIVATE = frozenset(
    {
        "manufacturerId",
        "macAddress",
        "name",
        "deviceName",
        "deviceId",
        "parentDeviceId",
        "userId",
        "accountId",
        "tenantId",
        "id",
        "email",
        "phone",
        "ssid",
        "ip",
    }
)

LitterBoxListener = Callable[[LitterBoxEvent], Awaitable[None]]
ReadingListener = Callable[[Device, LitterBoxReading], Awaitable[None]]


class CatGenieWatcher:
    def __init__(self, store: AccountStore, account: CatGenieAccount) -> None:
        self.store = store
        self.db = store.db
        self.account = account
        self.listeners: list[LitterBoxListener] = []
        self.reading_listeners: list[ReadingListener] = []
        # Told once when the sign-in stops working (the chores tell the admins).
        self.broken_listeners: list[Callable[[str], Awaitable[None]]] = []
        self._logged: set[str] = set()

    # ----- linking (the Accounts page) -------------------------------------------------

    async def send_code(self, phone: str) -> str:
        return await self.account.send_code(phone)

    async def link(self, by: Member, phone: str, code: str) -> list[Device]:
        """Sign in and add the litter boxes it can see (new ones only)."""
        found = await self.account.link(by, phone, code)
        known = {d.external_id for d in self.devices()}
        added = []
        for raw in found:
            external = str(raw["manufacturerId"])
            if external not in known:
                name = str(raw.get("name") or "CatGenie")
                added.append(self.store.add_device(by, PROVIDER, external, name, APPLIANCE))
                known.add(external)
        return added

    async def unlink(self) -> None:
        await self.account.unlink()

    def devices(self) -> list[Device]:
        return [d for d in self.store.list_devices() if d.provider == PROVIDER]

    def states(self) -> dict[int, str]:
        ids = {d.id for d in self.devices()}
        rows = self.db.query("SELECT device_id, state FROM device_states")
        return {r["device_id"]: r["state"] for r in rows if r["device_id"] in ids}

    def raw(self, device: Device) -> dict[str, Any] | None:
        """What PetNovations last said about it, as it said it."""
        row = self.db.one("SELECT * FROM catgenie_devices WHERE device_id = ?", (device.id,))
        return json.loads(row["raw"]) if row else None

    def reading(self, device: Device) -> LitterBoxReading | None:
        raw = self.raw(device)
        return read_device(raw) if raw is not None else None

    # ----- the job --------------------------------------------------------------------

    async def poll(self) -> int:
        """Scheduler job: read every litter box, and the notifications. Returns how many
        events."""
        if not self.account.linked() or self.account.problem():
            return 0
        try:
            raws = await self.account.devices()
        except SignInLost as exc:
            await self._broken(str(exc))
            return 0
        except CatGenieError as exc:
            log.warning("Couldn't read the litter box: %s", exc)
            return 0
        try:
            await self._alerts(await self.account.notifications())
        except SignInLost as exc:
            await self._broken(str(exc))
            return 0
        except CatGenieError as exc:  # the boxes are still read
            log.warning("Couldn't read the litter box's notifications: %s", exc)
        events = 0
        found = {str(r["manufacturerId"]): r for r in raws}
        for device in self.devices():
            raw = found.get(device.external_id)
            if raw is None:  # gone from the account: not something a person can fix here
                self._keep_word(device, "not on the CatGenie account any more")
                continue
            events += await self._saw(device, raw)
        return events

    async def read(self, device: Device) -> LitterBoxReading:
        """Asked how it's doing: read now (and kept, as a poll would; its events go out too).
        CatGenieError when it can't be read."""
        try:
            raws = await self.account.devices()
        except SignInLost as exc:
            await self._broken(str(exc))
            raise
        raw = next((r for r in raws if str(r["manufacturerId"]) == device.external_id), None)
        if raw is None:
            raise CatGenieError("The litter box isn't on the CatGenie account any more.")
        await self._saw(device, raw)
        return read_device(raw)

    async def capture(self) -> dict[str, Any]:
        """Each box's report read now and the notifications, for fixtures: nothing that says
        who or where."""
        raws = await self.account.devices()
        notifications = await self.account.notifications()
        return {
            "captured_at": to_utc_iso(clock.now()),
            "devices": [
                {"report": _scrub(raw), "reading": _reading_words(read_device(raw))} for raw in raws
            ],
            "notifications": [_scrub_notification(n) for n in notifications],
        }

    # ----- what changed -----------------------------------------------------------------

    async def _saw(self, device: Device, raw: dict[str, Any]) -> int:
        now = clock.now()
        self.db.execute(
            "INSERT INTO catgenie_devices (device_id, raw, read_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET raw = excluded.raw, read_at = excluded.read_at",
            (device.id, json.dumps(raw), to_utc_iso(now)),
        )
        reading = read_device(raw)
        for code in reading.unknown:
            if code not in self._logged:
                self._logged.add(code)
                log.warning("The litter box reported %r, which Themi has no words for", code)
        self._keep_word(device, state_word(reading))
        for listener in self.reading_listeners:
            try:
                await listener(device, reading)
            except Exception:
                log.exception("A litter box reading listener failed")
        row = self.db.one("SELECT * FROM litter_states WHERE device_id = ?", (device.id,))
        current = dict(reading.problems)
        if row is not None and row["alert"]:
            since = datetime.fromisoformat(row["alert_at"])
            cleaned = reading.last_clean is not None and reading.last_clean > since
            if cleaned and not reading.cleaning:  # it cleaned again after: sorted
                self.db.execute(
                    "UPDATE litter_states SET alert = NULL, alert_at = NULL WHERE device_id = ?",
                    (device.id,),
                )
            else:
                current[ALERT] = str(row["alert"])
        if row is None:  # the starting point
            self.db.execute(
                "INSERT INTO litter_states (device_id, problems, sani_left, cycles, seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    device.id,
                    json.dumps(current),
                    reading.sani_left,
                    reading.cycles,
                    to_utc_iso(now),
                ),
            )
            return 0
        before: dict[str, str] = json.loads(row["problems"])
        self.db.execute(
            "UPDATE litter_states SET problems = ?, sani_left = ?, cycles = ?, seen_at = ? "
            "WHERE device_id = ?",
            (json.dumps(current), reading.sani_left, reading.cycles, to_utc_iso(now), device.id),
        )
        events = [
            LitterBoxEvent(device.id, kind, detail, now, gone=True)
            for kind, detail in before.items()
            if kind not in current
        ] + [
            LitterBoxEvent(device.id, kind, detail, now)
            for kind, detail in current.items()
            if before.get(kind) != detail  # new, or changed (running low, then out)
        ]
        for event in events:
            for listener in self.listeners:
                try:
                    await listener(event)
                except Exception:
                    log.exception("A litter box listener failed for %s", event)
        return len(events)

    async def _alerts(self, notifications: list[dict[str, Any]]) -> None:
        """New notifications kept; one naming an error makes the box's alert live. The first
        read is the starting point."""
        first = not self.db.scalar("SELECT alerts_read FROM catgenie_account WHERE id = 1")
        devices = self.devices()
        now = to_utc_iso(clock.now())
        for raw in notifications:
            alert = read_alert(raw)
            if self.db.one("SELECT 1 FROM catgenie_notifications WHERE id = ?", (alert.alert_id,)):
                continue
            device = _device_for(alert, devices)
            self.db.execute(
                "INSERT INTO catgenie_notifications (id, device_id, data, created_at, first, "
                "seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    alert.alert_id,
                    device.id if device else None,
                    str(raw.get("data") or ""),
                    to_utc_iso(alert.at) if alert.at else None,
                    1 if first else 0,
                    now,
                ),
            )
            if first or device is None or not alert.error:
                continue
            if alert.error not in self._logged and alert.error not in CODES:
                self._logged.add(alert.error)
                log.warning("The litter box alerted %r, which Themi has no words for", alert.error)
            self.db.execute(
                "UPDATE litter_states SET alert = ?, alert_at = ? WHERE device_id = ?",
                (error_words(alert.error), to_utc_iso(alert.at or clock.now()), device.id),
            )
        if first:
            self.db.execute("UPDATE catgenie_account SET alerts_read = 1 WHERE id = 1")

    async def _broken(self, why: str) -> None:
        log.warning("The CatGenie sign-in stopped working: %s", why)
        await self.account.close()
        if self.account.broken(why):
            for listener in self.broken_listeners:
                try:
                    await listener(why)
                except Exception:
                    log.exception("Telling about the CatGenie sign-in failed")

    def _keep_word(self, device: Device, word: str) -> None:
        self.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET state = excluded.state, "
            "seen_at = excluded.seen_at",
            (device.id, word, to_utc_iso(clock.now())),
        )


async def write_captures(watcher: CatGenieWatcher, folder: Path) -> Path:
    """`themi catgenie capture`: the boxes' reports and the notifications, in one file."""
    folder.mkdir(parents=True, exist_ok=True)
    captured = await watcher.capture()
    stamp = clock.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"catgenie-{stamp}.json"
    path.write_text(json.dumps(captured, indent=1, sort_keys=True) + "\n")
    return path


def _device_for(alert: Alert, devices: list[Device]) -> Device | None:
    """The box an alert is about; with only one box, an alert naming none is about it."""
    for device in devices:
        if device.external_id == alert.manufacturer_id:
            return device
    return devices[0] if len(devices) == 1 and not alert.manufacturer_id else None


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in PRIVATE}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _scrub_notification(raw: dict[str, Any]) -> dict[str, Any]:
    kept = _scrub(raw)
    try:
        data = json.loads(raw.get("data") or "{}")
    except (TypeError, ValueError):
        data = None
    kept["data"] = _scrub(data) if isinstance(data, dict) else None
    return kept


def _reading_words(reading: LitterBoxReading) -> dict[str, Any]:
    return {
        "problems": reading.problems,
        "said": state_word(reading),
        "cycles": reading.cycles,
        "unknown": list(reading.unknown),
    }
