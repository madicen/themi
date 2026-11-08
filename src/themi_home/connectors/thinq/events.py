"""LG's washer and dryer states, in three words: running, finished or idle (30).

A state report carries `runState.currentState`, one of LG's many words ("RUNNING",
"RINSING", "END", "POWER_OFF", ...). A washer with two drums reports a list, one per
location (MAIN, MINI); the main drum counts. A WashTower is one device holding a washer
and a dryer, `{"washer": {...}, "dryer": {...}}`, so Themi keeps it as two
(`<id>:washer`, `<id>:dryer`).

Pushes come as `{"pushType": "DEVICE_STATUS", "deviceId", "deviceType", "report"}` or
`{"pushType": "DEVICE_PUSH", ..., "pushCode": "WASHING_IS_COMPLETE"}`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from themi_home.connectors.thinq.client import ThinqDevice

log = logging.getLogger(__name__)

RUNNING, FINISHED, IDLE = "running", "finished", "idle"
STATES = (RUNNING, FINISHED, IDLE)

# Mid-cycle words. A paused cycle is still a load in the drum, so it counts as running.
RUNNING_WORDS = frozenset(
    {
        "RUNNING",
        "DETECTING",
        "PREWASH",
        "WASHING",
        "SOAKING",
        "RINSING",
        "RINSE_HOLD",
        "ADDING_RINSE",
        "SPINNING",
        "DRYING",
        "COOLING",
        "STEAM_SOFTENING",
        "STERILIZE",
        "DISPENSING",
        "CHANGE_CONDITION",
        "ADD_DRAIN",
        "REFRESHING",
        "PAUSE",
    }
)
# Done: the clothes are ready to come out (wrinkle care tumbles a finished load now and then).
FINISHED_WORDS = frozenset({"END", "COMPLETE", "WRINKLE_CARE"})
IDLE_WORDS = frozenset(
    {"POWER_OFF", "INITIAL", "SLEEP", "RESERVED", "STANDBY", "ERROR", "CANCEL", "FIRMWARE"}
)
PUSH_CODES = {"WASHING_IS_COMPLETE": "washer", "DRYING_IS_COMPLETE": "dryer"}

# What each kind of device is in the house; anything else waits to be mapped on the website.
APPLIANCES = {
    "DEVICE_WASHER": "washer",
    "DEVICE_DRYER": "dryer",
    "DEVICE_WASHTOWER_WASHER": "washer",
    "DEVICE_WASHTOWER_DRYER": "dryer",
}
TOWER = "DEVICE_WASHTOWER"
TOWER_PARTS = ("washer", "dryer")


@dataclass(frozen=True)
class ApplianceEvent:
    device_id: int  # Themi's device
    appliance: str | None  # washer, dryer, or None while unmapped
    state: str  # running, finished or idle
    at: datetime


@dataclass(frozen=True)
class Part:
    """One appliance Themi keeps for an LG device (a WashTower is two)."""

    external_id: str
    name: str
    appliance: str | None


def parts(device: ThinqDevice) -> list[Part]:
    if device.kind == TOWER:
        return [
            Part(f"{device.device_id}:{part}", f"{device.name} ({part})", part)
            for part in TOWER_PARTS
        ]
    return [Part(device.device_id, device.name, APPLIANCES.get(device.kind))]


def state_word(word: str) -> str | None:
    """LG's word for a state as one of Themi's three, or None for a word not known."""
    word = word.upper()
    if word in RUNNING_WORDS:
        return RUNNING
    if word in FINISHED_WORDS:
        return FINISHED
    if word in IDLE_WORDS:
        return IDLE
    log.info("LG ThinQ reported a state Themi doesn't know: %s", word)
    return None


def _run_state(report: Any) -> str | None:
    report = _main(report)  # one per drum: the main one counts
    if report is None:
        return None
    word = (report.get("runState") or {}).get("currentState")
    return state_word(str(word)) if word else None


def _main(report: Any) -> dict[str, Any] | None:
    """The report for the main drum (a list has one per drum), or the report itself."""
    if isinstance(report, list):
        main = [r for r in report if isinstance(r, dict)]
        main.sort(key=lambda r: (r.get("location") or {}).get("locationName") != "MAIN")
        report = main[0] if main else None
    return report if isinstance(report, dict) else None


def minutes_left(device_id: str, kind: str, report: Any) -> dict[str, int]:
    """F20b: the time left on each appliance in a state report, as {external id: minutes},
    from LG's `timer` (remainHour, remainMinute); an appliance without one is left out."""
    parts_of = (
        {f"{device_id}:{part}": (report or {}).get(part) for part in TOWER_PARTS}
        if kind == TOWER and isinstance(report, dict)
        else {device_id: report}
    )
    found = {}
    for external_id, part in parts_of.items():
        timer = (_main(part) or {}).get("timer")
        if not isinstance(timer, dict) or "remainMinute" not in timer:
            continue
        try:
            found[external_id] = int(timer.get("remainHour") or 0) * 60 + int(timer["remainMinute"])
        except (TypeError, ValueError):
            continue
    return found


def read_report(device_id: str, kind: str, report: Any) -> dict[str, str]:
    """A state report (read or pushed) as {external id: state}; a partial push names only
    what changed, so anything it leaves out is missing, not idle."""
    if kind == TOWER:
        found = {}
        for part in TOWER_PARTS:
            state = _run_state((report or {}).get(part)) if isinstance(report, dict) else None
            if state is not None:
                found[f"{device_id}:{part}"] = state
        return found
    state = _run_state(report)
    return {device_id: state} if state is not None else {}


def read_push(message: dict[str, Any]) -> dict[str, str]:
    """A push message as {external id: state}; anything else it says is left out."""
    device_id, kind = str(message.get("deviceId") or ""), str(message.get("deviceType") or "")
    if not device_id:
        return {}
    push_type = message.get("pushType")
    if push_type == "DEVICE_STATUS":
        return read_report(device_id, kind, message.get("report"))
    if push_type == "DEVICE_PUSH":
        part = PUSH_CODES.get(str(message.get("pushCode") or "").upper())
        if part is None:
            return {}
        return {f"{device_id}:{part}" if kind == TOWER else device_id: FINISHED}
    return {}
