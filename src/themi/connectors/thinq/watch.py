"""The family's LG appliances, watched: pushes when they come, polling otherwise (30).

- `devices.thinq_push`, every minute: keeps the push connection up and handles what it
  brought.
- `devices.thinq`, every 5 minutes: reads each appliance while pushes aren't coming in
  (about 580 calls a day for a washer and a dryer), and once an hour even when they are,
  in case one went missing.

Each appliance's last state is kept (`device_states`); a change becomes an
`ApplianceEvent` for the listeners (the laundry, 31). The first state seen for an
appliance only sets the starting point, so linking doesn't announce an old load.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from themi import clock
from themi.accounts import AccountStore, Device, Member
from themi.connectors.thinq.client import (
    DeviceOffline,
    RateLimited,
    ThinqAccount,
    ThinqError,
    TokenRejected,
)
from themi.connectors.thinq.events import (
    TOWER,
    ApplianceEvent,
    minutes_left,
    parts,
    read_push,
    read_report,
)
from themi.connectors.thinq.push import ThinqPush
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

PROVIDER = "lg_thinq"
SAFETY_POLL = timedelta(hours=1)  # while pushes come in

ApplianceListener = Callable[[ApplianceEvent], Awaitable[None]]


class ThinqWatcher:
    def __init__(self, store: AccountStore, account: ThinqAccount, push: ThinqPush) -> None:
        self.store = store
        self.db = store.db
        self.account = account
        self.push = push
        self.listeners: list[ApplianceListener] = []
        self._last_poll: datetime | None = None

    # ----- linking (the Accounts page) -------------------------------------------------

    async def link(self, by: Member, token: str, country: str) -> list[Device]:
        """Keep the token and add the appliances it can see (new ones only)."""
        found = await self.account.link(by, token, country)
        self.push.reset()
        known = {d.external_id for d in self.devices()}
        added = []
        for device in found:
            for part in parts(device):
                if part.external_id not in known:
                    added.append(
                        self.store.add_device(
                            by, PROVIDER, part.external_id, part.name, part.appliance
                        )
                    )
        return added

    async def unlink(self) -> None:
        self.push.reset()
        await self.account.unlink()

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

    # ----- the jobs ---------------------------------------------------------------------

    async def listen(self) -> int:
        """Scheduler job: keep pushes coming and handle them. Returns how many events."""
        if not self.account.linked():
            return 0
        await self.push.keep_up(sorted(_lg_ids(self.devices())))
        events = 0
        for message in self.push.drain():
            for external_id, state in read_push(message).items():
                events += await self._saw(external_id, state)
        return events

    async def poll(self) -> int:
        """Scheduler job: read each appliance, unless pushes are covering it. Returns how
        many events."""
        if not self.account.linked():
            return 0
        now = clock.now()
        if (
            self.push.connected()
            and self._last_poll is not None
            and now < self._last_poll + SAFETY_POLL
        ):
            return 0
        self._last_poll = now
        events = 0
        for lg_id, kind in sorted(_lg_ids(self.devices()).items()):
            try:
                report = await self.account.state(lg_id)
            except DeviceOffline:
                continue  # says nothing either way
            except RateLimited as exc:
                log.warning("LG ThinQ asked to wait %s; the laundry read waits", exc.wait)
                return events
            except TokenRejected as exc:
                log.warning("LG ThinQ turned down the token: %s", exc)
                return events
            except ThinqError as exc:
                log.warning("Couldn't read an LG appliance: %s", exc)
                continue
            for external_id, state in read_report(lg_id, kind, report).items():
                events += await self._saw(external_id, state)
        return events

    async def read(self, device: Device) -> tuple[str | None, int | None]:
        """F20b, asked how it's doing: the appliance's state read now (and kept, as a poll
        would) and its minutes left, if LG says. ThinqError when it can't be read."""
        lg_id, _, part = device.external_id.partition(":")
        kind = TOWER if part else ""
        report = await self.account.state(lg_id)
        state = read_report(lg_id, kind, report).get(device.external_id)
        if state is not None:
            await self._saw(device.external_id, state)
        return state, minutes_left(lg_id, kind, report).get(device.external_id)

    async def _saw(self, external_id: str, state: str) -> int:
        device = next((d for d in self.devices() if d.external_id == external_id), None)
        if device is None:
            return 0
        before = self.db.one("SELECT state FROM device_states WHERE device_id = ?", (device.id,))
        now = clock.now()
        self.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET state = excluded.state, "
            "seen_at = excluded.seen_at",
            (device.id, state, to_utc_iso(now)),
        )
        if before is None or before["state"] == state:
            return 0
        event = ApplianceEvent(device.id, device.appliance, state, now)
        for listener in self.listeners:
            try:
                await listener(event)
            except Exception:
                log.exception("An appliance listener failed for %s", event)
        return 1


def _lg_ids(devices: list[Device]) -> dict[str, str]:
    """LG's device ids behind Themi's devices, and whether each is a WashTower."""
    found: dict[str, str] = {}
    for device in devices:
        lg_id, _, part = device.external_id.partition(":")
        found[lg_id] = TOWER if part else ""
    return found
