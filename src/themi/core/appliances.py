"""F20b: how the appliances are doing, when someone asks (Michael's bug #109).

"How much longer on the current wash cycle?" was answered "25 minutes left", and "And the
dryer?" "The dryer isn't running", both made up: no tool read the appliances. Now
`appliance_status` reads each one live (LG ThinQ for the washer and dryer, Home Connect for
the dishwasher, Roborock for the vacuum, V1), keeps what it saw as a poll would, and says the
time left when the appliance reports it. One that can't be read now is told as it was last
seen, with the time, and one that was never seen says so. Reading changes nothing in the
house, so it isn't staged through the trust tiers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from themi.accounts import Device
from themi.connectors.homeconnect import HomeConnectError
from themi.connectors.roborock import RoborockError
from themi.connectors.roborock.events import problems, state_word
from themi.connectors.thinq import FINISHED, IDLE, RUNNING, ThinqError
from themi.core.services import Services
from themi.core.tasks import clock_words
from themi.core.tools import ToolContext, tool

log = logging.getLogger(__name__)

APPLIANCES = ("washer", "dryer", "dishwasher", "vacuum")
# Home Connect's words, as LG's three (and its own few that are neither).
HOME_CONNECT = {
    "Run": RUNNING,
    "Pause": RUNNING,  # a paused cycle still has its load in
    "Finished": FINISHED,
    "Ready": IDLE,
    "Inactive": IDLE,
    "Aborting": IDLE,
}
NONE_LINKED = (
    "No washer, dryer, dishwasher or vacuum is linked to Themi, so Themi can't see them. An admin "
    "can link them on the website's Family page. Say so; don't guess how they're doing."
)
SAY_ONLY = (
    "That's all Themi can see of them: say it as it is, and never add a time or a state "
    "that isn't here."
)


class Appliances:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        self.services.appliances = self
        self.services.tools.register(appliance_status)

    async def status(self, which: str) -> str:
        devices = [
            d
            for d in self.services.store.list_devices()
            if d.appliance in APPLIANCES and which in ("all", d.appliance)
        ]
        if not devices:
            if which == "all":
                return NONE_LINKED
            return f"No {which} is linked to Themi, so Themi can't see it. Say so; don't guess."
        lines = [await self._line(d) for d in devices]
        return "\n".join(lines) + "\n\n" + SAY_ONLY

    async def _line(self, device: Device) -> str:
        name = f"{device.name} ({device.appliance})"
        if device.provider == "roborock":
            return await self._vacuum(device, name)
        try:
            state, minutes = await self._read(device)
        except (ThinqError, HomeConnectError) as exc:
            log.info("Couldn't read %s for a status question: %s", device.name, exc)
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        if state is None:
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        return f"{name}, read just now: {self._words(device, state, minutes)}."

    async def _read(self, device: Device) -> tuple[str | None, int | None]:
        if device.provider == "lg_thinq" and self.services.thinq is not None:
            return await self.services.thinq.read(device)
        if device.provider == "home_connect" and self.services.dishwasher is not None:
            word, minutes = await self.services.dishwasher.read(device)
            return HOME_CONNECT.get(word, "offline" if word == "Offline" else IDLE), minutes
        return None, None

    async def _vacuum(self, device: Device, name: str) -> str:
        """The robot vacuum: what it's doing, and anything it needs a person for."""
        watcher = self.services.roborock
        if watcher is None:
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        try:
            status = await watcher.read(device)
        except RoborockError as exc:
            log.info("Couldn't read %s for a status question: %s", device.name, exc)
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        said = state_word(status)
        if status.battery is not None:
            said += f", battery {status.battery}%"
        needs = [words for words in problems(status).values()]
        if needs:
            said += "; it needs a hand: " + "; ".join(needs)
        vacuum = self.services.vacuum
        chores = vacuum.chores(device.id) if vacuum is not None else []  # F23d: and whose
        return " ".join([f"{name}, read just now: {said}.", *chores])

    def _words(self, device: Device, state: str, minutes: int | None) -> str:
        if state == RUNNING:
            since = self._cycle(device, "started_at", open_only=True)
            said = "running" + (f" since {since}" if since else "")
            if minutes is None:
                return f"{said}; it doesn't say how long is left"
            return f"{said}, {_minutes(minutes)} left"
        if state == FINISHED:
            ended = self._cycle(device, "ended_at")
            return "finished" + (f" at {ended}" if ended else "") + ", not running now"
        if state == "offline":
            return "not connected right now, so its state isn't known"
        return "not running"

    def _last_seen(self, device: Device) -> str:
        row = self.db.one(
            "SELECT state, seen_at FROM device_states WHERE device_id = ?", (device.id,)
        )
        if row is None:
            return "Themi hasn't seen it yet, so its state isn't known."
        state = HOME_CONNECT.get(str(row["state"]), str(row["state"]))
        seen = self._local_words(datetime.fromisoformat(row["seen_at"]))
        if device.appliance == "vacuum":  # kept in words already
            return f"As of {seen} it was {state}."
        was = {RUNNING: "running", FINISHED: "finished"}.get(state, "not running")
        return f"As of {seen} it was {was}."

    def _cycle(self, device: Device, column: str, *, open_only: bool = False) -> str | None:
        """When its latest cycle started or ended, in words, if Themi saw it."""
        row = self.db.one(
            f"SELECT {column} AS at FROM appliance_cycles WHERE device_id = ?"
            + (" AND ended_at IS NULL" if open_only else f" AND {column} IS NOT NULL")
            + " ORDER BY id DESC LIMIT 1",
            (device.id,),
        )
        return self._local_words(datetime.fromisoformat(row["at"])) if row else None

    def _local_words(self, moment: datetime) -> str:
        family = self.services.store.get_family()
        local = moment.astimezone(ZoneInfo(family.timezone if family else "UTC"))
        return clock_words(local)


def _minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    return f"{hours} hour{'s' if hours != 1 else ''}" + (f" {rest} minutes" if rest else "")


@tool(
    "appliance_status",
    "How the washer, dryer, dishwasher or robot vacuum is doing right now: running or not, "
    "the time left when the appliance says, and what the vacuum needs. Use it for any "
    "question about them ('how long on the wash?', 'is the dryer done?', 'where's the "
    "vacuum?'); never answer those from memory or the conversation.",
    {
        "appliance": {
            "type": "string",
            "enum": [*APPLIANCES, "all"],
            "description": "The one they asked about, or 'all'.",
        },
    },
)
async def appliance_status(ctx: ToolContext, args: dict[str, Any]) -> str:
    appliances = ctx.services.appliances
    if appliances is None:
        return NONE_LINKED
    return await appliances.status(args["appliance"])
