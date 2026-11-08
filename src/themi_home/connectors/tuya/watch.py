"""The family's feeders, watched (32).

`devices.feeders`, every 10 minutes: reads each feeder's status (its specification once,
for the types and labels), and once an hour its feeding log. About 170 calls a day per
feeder.

Each device's raw specification and status are kept (`tuya_devices`), so a model's data
points can be looked at on the Accounts page and captured (`capture`, `themi tuya
capture`). What a feeder needs (`feeder_states`) is kept too, and only a change becomes a
`FeederEvent` for the listeners (the feeders' chores, `themi_home.feeders`); the first read
is only the starting point, as with the washer (30). Feedings go in `feeder_feeds`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from themi import clock
from themi.accounts import AccountStore, Device, Member
from themi.localtime import to_utc_iso
from themi_home.connectors.tuya.client import (
    DeviceOffline,
    KeyRejected,
    RateLimited,
    TuyaAccount,
    TuyaDevice,
    TuyaError,
)
from themi_home.connectors.tuya.events import FeederEvent, FeederReading, read_status, state_word

log = logging.getLogger(__name__)

PROVIDER = "tuya"
FEEDER_CATEGORY = "cwwsq"  # Tuya's pet feeder; anything else is "Not used" until mapped
FEEDS_EVERY = timedelta(hours=1)
FEEDS_BACK = timedelta(days=1)  # the first look at a feeding log goes back this far
# What a capture leaves out: the device's keys and where it is.
PRIVATE = frozenset({"id", "uuid", "uid", "owner_id", "local_key", "ip", "lat", "lon", "name"})

FeederListener = Callable[[FeederEvent], Awaitable[None]]


class TuyaWatcher:
    def __init__(self, store: AccountStore, account: TuyaAccount) -> None:
        self.store = store
        self.db = store.db
        self.account = account
        self.listeners: list[FeederListener] = []
        # Told once when the project stops working (the feeders' chores tell the admins).
        self.broken_listeners: list[Callable[[str], Awaitable[None]]] = []
        self._feeds_at: dict[int, datetime] = {}
        self._logged: set[str] = set()

    # ----- linking (the Accounts page) -------------------------------------------------

    async def link(self, by: Member, access_id: str, secret: str, region: str) -> list[Device]:
        """Keep the keys and add the devices they can see (new ones only). Feeders map
        themselves; anything else is "Not used" until set."""
        found = await self.account.link(by, access_id, secret, region)
        known = {d.external_id: d for d in self.devices()}
        added = []
        for device in found:
            if device.device_id not in known:
                appliance = "feeder" if device.category == FEEDER_CATEGORY else None
                known[device.device_id] = self.store.add_device(
                    by, PROVIDER, device.device_id, device.name, appliance
                )
                added.append(known[device.device_id])
            self._keep_kind(known[device.device_id], device)
        self._feeds_at.clear()
        return added

    async def unlink(self) -> None:
        await self.account.unlink()
        self._feeds_at.clear()

    def devices(self, appliance: str | None = None) -> list[Device]:
        return [
            d
            for d in self.store.list_devices()
            if d.provider == PROVIDER and (appliance is None or d.appliance == appliance)
        ]

    def states(self) -> dict[int, str]:
        ids = {d.id for d in self.devices()}
        rows = self.db.query("SELECT device_id, state FROM device_states")
        return {r["device_id"]: r["state"] for r in rows if r["device_id"] in ids}

    def raw(self, device: Device) -> dict[str, Any] | None:
        """What Tuya last said about it: category, product, specification and status."""
        row = self.db.one("SELECT * FROM tuya_devices WHERE device_id = ?", (device.id,))
        if row is None:
            return None
        return {
            "category": row["category"],
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "specification": json.loads(row["spec"]) if row["spec"] else None,
            "status": json.loads(row["status"]) if row["status"] else None,
            "read_at": row["read_at"],
        }

    # ----- the job --------------------------------------------------------------------

    async def poll(self, *, feeds: bool = False) -> int:
        """Scheduler job: read each feeder. Returns how many events. `feeds`: read the
        feeding logs now too, not just hourly (`make dev`'s panel, D5d)."""
        if not self.account.linked() or self.account.problem():
            return 0
        events = 0
        for device in self.devices("feeder"):
            try:
                reading = await self._read(device)
                events += await self._saw(device, reading)
                if feeds or self._feeds_due(device):
                    await self._feeds(device, reading)
            except RateLimited as exc:
                log.warning("Tuya asked to wait %s; the feeders wait", exc.wait)
                return events
            except KeyRejected as exc:
                await self._broken(str(exc))
                return events
            except DeviceOffline:
                self._keep_word(device, "offline")
            except TuyaError as exc:
                log.warning("Couldn't read the feeder %s: %s", device.name, exc)
        return events

    async def read(self, device: Device) -> FeederReading:
        """Asked how it's doing: read now (and kept, as a poll would; its events go out
        too). TuyaError when it can't be read."""
        try:
            reading = await self._read(device)
        except KeyRejected as exc:
            await self._broken(str(exc))
            raise
        await self._saw(device, reading)
        return reading

    def last_fed(self, device: Device) -> tuple[datetime, int] | None:
        row = self.db.one(
            "SELECT portions, fed_at FROM feeder_feeds WHERE device_id = ? "
            "ORDER BY fed_at DESC LIMIT 1",
            (device.id,),
        )
        return (datetime.fromisoformat(row["fed_at"]), int(row["portions"])) if row else None

    async def capture(self, device: Device) -> dict[str, Any]:
        """Its data points read now, for a fixture: no ids, keys or names."""
        spec = await self.account.specification(device.external_id)
        status = await self.account.status(device.external_id)
        row = self.db.one("SELECT * FROM tuya_devices WHERE device_id = ?", (device.id,))
        return {
            "category": row["category"] if row else spec.get("category", ""),
            "product_id": row["product_id"] if row else "",
            "product_name": row["product_name"] if row else "",
            "captured_at": to_utc_iso(clock.now()),
            "specification": _scrub(spec),
            "status": status,
            "reading": _reading_words(read_status(status, spec, row["product_id"] if row else "")),
        }

    # ----- what changed -----------------------------------------------------------------

    async def _read(self, device: Device) -> FeederReading:
        row = self.db.one("SELECT * FROM tuya_devices WHERE device_id = ?", (device.id,))
        spec = json.loads(row["spec"]) if row and row["spec"] else None
        if spec is None:
            spec = await self.account.specification(device.external_id)
        status = await self.account.status(device.external_id)
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO tuya_devices (device_id, category, product_id, product_name, spec, "
            "status, read_at) VALUES (?, ?, '', '', ?, ?, ?) ON CONFLICT(device_id) DO UPDATE "
            "SET spec = excluded.spec, status = excluded.status, read_at = excluded.read_at",
            (device.id, str(spec.get("category") or ""), json.dumps(spec), json.dumps(status), now),
        )
        product = self.db.scalar(
            "SELECT product_id FROM tuya_devices WHERE device_id = ?", (device.id,)
        )
        reading = read_status(status, spec, str(product or ""))
        for label in reading.unknown:
            if label not in self._logged:
                self._logged.add(label)
                log.warning("A feeder reported %r, which Themi has no words for", label)
        return reading

    async def _saw(self, device: Device, reading: FeederReading) -> int:
        self._keep_word(device, state_word(reading))
        now = clock.now()
        row = self.db.one("SELECT * FROM feeder_states WHERE device_id = ?", (device.id,))
        current = reading.problems
        if row is None:  # the starting point
            self.db.execute(
                "INSERT INTO feeder_states (device_id, problems, level, seen_at) "
                "VALUES (?, ?, ?, ?)",
                (device.id, json.dumps(current), reading.level, to_utc_iso(now)),
            )
            return 0
        before: dict[str, str] = json.loads(row["problems"])
        self.db.execute(
            "UPDATE feeder_states SET problems = ?, level = ?, seen_at = ? WHERE device_id = ?",
            (json.dumps(current), reading.level, to_utc_iso(now), device.id),
        )
        events = [
            FeederEvent(device.id, kind, detail, now, gone=True)
            for kind, detail in before.items()
            if kind not in current
        ] + [
            FeederEvent(device.id, kind, detail, now)
            for kind, detail in current.items()
            if before.get(kind) != detail  # new, or changed (running low, then out)
        ]
        for event in events:
            for listener in self.listeners:
                try:
                    await listener(event)
                except Exception:
                    log.exception("A feeder listener failed for %s", event)
        return len(events)

    async def _feeds(self, device: Device, reading: FeederReading) -> None:
        """Its feedings since the log was last read, kept."""
        now = clock.now()
        row = self.db.one("SELECT feeds_to FROM feeder_states WHERE device_id = ?", (device.id,))
        since = (
            datetime.fromisoformat(row["feeds_to"]) if row and row["feeds_to"] else now - FEEDS_BACK
        )
        reports = await self.account.reports(
            device.external_id, list(reading.feed_codes), since, now
        )
        self._feeds_at[device.id] = now
        for entry in reports:
            portions = _portions(entry.get("value"))
            if not portions:
                continue
            fed_at = datetime.fromtimestamp(int(entry.get("event_time") or 0) / 1000, UTC)
            self.db.execute(
                "INSERT OR IGNORE INTO feeder_feeds (device_id, portions, fed_at) VALUES (?, ?, ?)",
                (device.id, portions, to_utc_iso(fed_at)),
            )
        self.db.execute(
            "UPDATE feeder_states SET feeds_to = ? WHERE device_id = ?",
            (to_utc_iso(now), device.id),
        )

    async def _broken(self, why: str) -> None:
        log.warning("Tuya's cloud project stopped working: %s", why)
        await self.account.close()
        if self.account.broken(why):
            for listener in self.broken_listeners:
                try:
                    await listener(why)
                except Exception:
                    log.exception("Telling about the Tuya project failed")

    # ----- small things -------------------------------------------------------------------

    def _feeds_due(self, device: Device) -> bool:
        last = self._feeds_at.get(device.id)
        return last is None or clock.now() >= last + FEEDS_EVERY

    def _keep_kind(self, device: Device, found: TuyaDevice) -> None:
        self.db.execute(
            "INSERT INTO tuya_devices (device_id, category, product_id, product_name) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET "
            "category = excluded.category, product_id = excluded.product_id, "
            "product_name = excluded.product_name",
            (device.id, found.category, found.product_id, found.product_name),
        )

    def _keep_word(self, device: Device, word: str) -> None:
        self.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET state = excluded.state, "
            "seen_at = excluded.seen_at",
            (device.id, word, to_utc_iso(clock.now())),
        )


async def write_captures(watcher: TuyaWatcher, folder: Path) -> list[Path]:
    """`themi tuya capture`: each linked device's data points, one file each, named by its
    model (Tuya's product id)."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for n, device in enumerate(watcher.devices(), 1):
        captured = await watcher.capture(device)
        stem = captured["product_id"] or captured["category"] or "device"
        path = folder / f"{stem}-{n}.json"
        path.write_text(json.dumps(captured, indent=1, sort_keys=True) + "\n")
        written.append(path)
    return written


def _portions(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in PRIVATE}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _reading_words(reading: FeederReading) -> dict[str, Any]:
    return {
        "problems": reading.problems,
        "level": reading.level,
        "said": state_word(reading),
        "unknown": list(reading.unknown),
    }
