"""F20b: how the appliances are doing, when someone asks (Michael's bug #109).

"How much longer on the current wash cycle?" was answered "25 minutes left", and "And the
dryer?" "The dryer isn't running", both made up: no tool read the appliances. Now
`appliance_status` reads each one live (LG ThinQ for the washer and dryer, Home Connect for
the dishwasher, Roborock for the vacuum, V1, Tuya for the pet feeders, 32, CatGenie for the
litter box, CG1a), keeps what it
saw as a poll would, and says the time left when the appliance reports it. One that can't be
read now is told as it was last seen, with the time, and one that was never seen says so.
Reading changes nothing in the house, so it isn't staged through the trust tiers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Device
from themi.core import keys
from themi.core.services import Services
from themi.core.tools import ToolContext, tool
from themi.modules import Module, ModuleContext
from themi.modules.prompt import PromptFragment
from themi.standard.tasks import clock_words
from themi_home import home_groups
from themi_home.connectors.catgenie import CatGenieError
from themi_home.connectors.catgenie.events import state_word as litter_words
from themi_home.connectors.homeconnect import HomeConnectError
from themi_home.connectors.roborock import RoborockError
from themi_home.connectors.roborock.events import problems, state_word
from themi_home.connectors.thinq import FINISHED, IDLE, RUNNING, ThinqError
from themi_home.connectors.tuya import TuyaError
from themi_home.connectors.tuya.events import state_word as feeder_words

log = logging.getLogger(__name__)

APPLIANCES = ("washer", "dryer", "dishwasher", "vacuum", "feeder", "litter_box")
IN_WORDS = ("vacuum", "feeder", "litter_box")  # their states are kept in words already
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
    "No washer, dryer, dishwasher, vacuum, feeder or litter box is linked to Themi, so Themi "
    "can't see "
    "them. An admin can link them on the website's Accounts page. Say so; don't guess how "
    "they're doing."
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
        self.services.provide(keys.appliances, self)
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

    def at_a_glance(self) -> list[str] | None:
        """W2, the website's Home: what's worth knowing, from the states last seen (no reads,
        so the page never waits on an appliance). None when nothing is linked."""
        devices = [d for d in self.services.store.list_devices() if d.appliance in APPLIANCES]
        if not devices:
            return None
        states = {
            r["device_id"]: str(r["state"])
            for r in self.db.query("SELECT device_id, state FROM device_states")
        }
        lines = []
        for device in devices:
            state = states.get(device.id)
            if state is None:
                continue
            if device.appliance in IN_WORDS:
                lines.append(f"{device.name}: {state}")
                continue
            state = HOME_CONNECT.get(state, state)
            if state == RUNNING:  # F40b, idea #196: when it'll finish, never when it began
                ends = self._ends(device)
                lines.append(f"{device.name}: running" + (f", done around {ends}" if ends else ""))
            elif state == FINISHED:
                ended = self._cycle(device, "ended_at")
                lines.append(f"{device.name}: finished" + (f" at {ended}" if ended else ""))
        return lines

    async def _line(self, device: Device) -> str:
        name = f"{device.name} ({device.appliance})"
        if device.provider == "roborock":
            return await self._vacuum(device, name)
        if device.provider == "tuya":
            return await self._feeder(device, name)
        if device.provider == "catgenie":
            return await self._litter_box(device, name)
        try:
            state, minutes = await self._read(device)
        except (ThinqError, HomeConnectError) as exc:
            log.info("Couldn't read %s for a status question: %s", device.name, exc)
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        if state is None:
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        return f"{name}, read just now: {self._words(device, state, minutes)}."

    async def _read(self, device: Device) -> tuple[str | None, int | None]:
        if device.provider == "lg_thinq" and self.services.maybe(keys.thinq) is not None:
            return await self.services.get(keys.thinq).read(device)
        if device.provider == "home_connect" and self.services.maybe(keys.dishwasher) is not None:
            word, minutes = await self.services.get(keys.dishwasher).read(device)
            return HOME_CONNECT.get(word, "offline" if word == "Offline" else IDLE), minutes
        return None, None

    async def _vacuum(self, device: Device, name: str) -> str:
        """The robot vacuum: what it's doing, and anything it needs a person for."""
        watcher = self.services.maybe(keys.roborock)
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
        vacuum = self.services.maybe(keys.vacuum)
        chores = vacuum.chores(device.id) if vacuum is not None else []  # F23d: and whose
        return " ".join([f"{name}, read just now: {said}.", *chores])

    async def _feeder(self, device: Device, name: str) -> str:
        """A pet feeder: its food, anything it needs a person for, and its last feeding."""
        watcher = self.services.maybe(keys.tuya)
        if watcher is None:
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        try:
            reading = await watcher.read(device)
        except TuyaError as exc:
            log.info("Couldn't read %s for a status question: %s", device.name, exc)
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        said = feeder_words(reading)
        fed = watcher.last_fed(device)
        if fed is not None:
            at, portions = fed
            said += (
                f"; last fed {self._local_words(at)}{self._day_words(at)}, "
                f"{portions} portion{'s' if portions != 1 else ''}"
            )
        feeders = self.services.maybe(keys.feeders)
        chores = feeders.chores(device.id) if feeders is not None else []
        return " ".join([f"{name}, read just now: {said}.", *chores])

    async def _litter_box(self, device: Device, name: str) -> str:
        """The litter box: cleaning or not, its sani-solution, any error, its last clean."""
        watcher = self.services.maybe(keys.catgenie)
        if watcher is None:
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        try:
            reading = await watcher.read(device)
        except CatGenieError as exc:
            log.info("Couldn't read %s for a status question: %s", device.name, exc)
            return f"{name}: couldn't be read just now. {self._last_seen(device)}"
        said = litter_words(reading)
        if reading.last_clean is not None:
            said += f"; last cleaned {self._local_words(reading.last_clean)}"
            said += self._day_words(reading.last_clean)
        litter_box = self.services.maybe(keys.litter_box)
        chores = litter_box.chores(device.id) if litter_box is not None else []  # and whose
        return " ".join([f"{name}, read just now: {said}.", *chores])

    def _words(self, device: Device, state: str, minutes: int | None) -> str:
        if state == RUNNING:
            since = self._cycle(device, "started_at", open_only=True)
            said = "running" + (f" since {since}" if since else "")
            if minutes is None:
                return f"{said}; it doesn't say how long is left"
            done = self._local_words(clock.now() + timedelta(minutes=minutes))
            return f"{said}, {_minutes(minutes)} left, done around {done}"
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
        if device.appliance in IN_WORDS:
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

    def _ends(self, device: Device) -> str | None:
        """F40b: when its running cycle should end, in words, if that's still ahead."""
        at = self.db.scalar(
            "SELECT ends_at FROM appliance_cycles WHERE device_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (device.id,),
        )
        if not at or datetime.fromisoformat(str(at)) <= clock.now():
            return None
        return self._local_words(datetime.fromisoformat(str(at)))

    def _day_words(self, moment: datetime) -> str:
        """ "" today, " yesterday", or " on Monday 2 November"."""
        family = self.services.store.get_family()
        zone = ZoneInfo(family.timezone if family else "UTC")
        day, today = moment.astimezone(zone).date(), clock.now().astimezone(zone).date()
        if day == today:
            return " today"
        if day == today - timedelta(days=1):
            return " yesterday"
        return f" on {day.strftime('%A')} {day.day} {day.strftime('%B')}"

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
    "How the washer, dryer, dishwasher, robot vacuum, pet feeder or litter box is doing right "
    "now: running or not, the time left when the appliance says, what the vacuum needs, the "
    "feeder's food and last feeding, and the litter box's sani-solution, errors and last "
    "clean. Use it for any question about them ('how long on the wash?', 'is the dryer "
    "done?', 'where's the vacuum?', 'has the cat been fed?', 'is the litter box ok?'); never "
    "answer those from memory or the conversation.",
    {
        "appliance": {
            "type": "string",
            "enum": [*APPLIANCES, "all"],
            "description": "The one they asked about, or 'all'.",
        },
    },
)
async def appliance_status(ctx: ToolContext, args: dict[str, Any]) -> str:
    appliances = ctx.services.maybe(keys.appliances)
    if appliances is None:
        return NONE_LINKED
    return await appliances.status(args["appliance"])


# CR8a: the system prompt's rules about this module's feature.
PROMPT_RULES = (
    PromptFragment(
        "appliances.how-the-washer-dryer",
        "speak",
        80,
        """\
- How the washer, dryer, dishwasher or robot vacuum is doing (running, done, time left,
  stuck) comes only from appliance_status, asked each time: never from memory or the
  conversation.""",
    ),
)


class AppliancesModule(Module):
    """F20b: asked how the appliances are doing, it reads them."""

    name = "appliances"
    title = "Appliances"
    summary = "Answers how the washer, dryer, dishwasher and other appliances are doing."
    tool_groups = (home_groups.DEVICES,)

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*PROMPT_RULES)
        appliances = ctx.provide(Appliances(ctx.services))
        appliances.install()
        ctx.dashboard_panel(  # CR17a: what's running, when anything is linked
            "dashboard/around_the_house.html",
            30,
            values=lambda _member: {"around_the_house": appliances.at_a_glance()},
        )
