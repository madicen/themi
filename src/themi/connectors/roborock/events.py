"""What the robot's status means for the family: the problems a person can fix, in words.

The codes are python-roborock's (`RoborockErrorCode`, `RoborockDockErrorCode`,
`RoborockStateCode`, and the dock status bits in `dss`; 7.15.1, read 2026-11-01). Every
code Themi acts on is in `ROBOT` or `DOCK` below; any other nonzero code is a `fault`, told
by its number and logged, so a missing one shows up.

Kinds of problem, each one chore at a time:

- `stuck`: trapped, wheels caught or hanging, tipped, a bumper pressed.
- `jammed`: a brush, the mop lift or a filter jammed or blocked (on the robot or the dock).
- `water_empty`: the dock's clean-water tank is empty.
- `water_full`: the dock's dirty-water tank is full (or out).
- `bin`: a dustbin or filter not in, a tank latch open.
- `not_docked`: it didn't get back (couldn't find the dock, a flat battery away from it),
  or it's sitting idle off the dock.
- `fault`: anything else it reports.
- `part`: a consumable nearly worn out (`low_parts`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

STUCK, JAMMED, WATER_EMPTY, WATER_FULL, BIN = "stuck", "jammed", "water_empty", "water_full", "bin"
NOT_DOCKED, FAULT, PART = "not_docked", "fault", "part"
KINDS = (STUCK, JAMMED, WATER_EMPTY, WATER_FULL, BIN, NOT_DOCKED, FAULT)

# The robot's error codes: (kind, the words for it).
ROBOT: dict[int, tuple[str, str]] = {
    2: (STUCK, "a bumper's stuck"),
    3: (STUCK, "a wheel's off the floor"),
    7: (STUCK, "the wheels are caught"),
    8: (STUCK, "it's trapped"),
    16: (STUCK, "it's tipped"),
    21: (STUCK, "its top bumper's pressed"),
    24: (STUCK, "it's in a no-go zone"),
    30: (STUCK, "it's against an invisible wall"),
    31: (STUCK, "it can't get over a rug"),
    5: (JAMMED, "the main brush is jammed"),
    6: (JAMMED, "the side brush is jammed"),
    17: (JAMMED, "the side brush is caught"),
    27: (JAMMED, "the mop lift is jammed"),
    29: (JAMMED, "the filter's blocked"),
    10: (JAMMED, "the filter's wet or blocked"),
    9: (BIN, "its dustbin isn't in"),
    38: (WATER_EMPTY, "the clean-water tank needs a look"),
    41: (WATER_EMPTY, "the clean-water tank is empty"),
    39: (WATER_FULL, "the dirty-water tank needs a look"),
    12: (NOT_DOCKED, "its battery ran low"),
    22: (NOT_DOCKED, "it couldn't find the dock"),
    23: (NOT_DOCKED, "it couldn't get back to the dock"),
}
# The dock's error codes.
DOCK: dict[int, tuple[str, str]] = {
    38: (WATER_EMPTY, "the clean-water tank is empty"),
    39: (WATER_FULL, "the dirty-water tank is full"),
    53: (WATER_FULL, "the dock's cleaning tank is full or blocked"),
    34: (JAMMED, "the dock's dust duct is blocked"),
    42: (JAMMED, "the dock's cleaning brush is jammed"),
    32: (BIN, "the dock's dustbin or filter isn't in"),
    33: (BIN, "the dock's dustbin or filter is out of place"),
    44: (BIN, "the dirty-water tank's latch is open"),
    46: (BIN, "the dock's dustbin isn't in"),
}

# States (RoborockStateCode).
CLEANING_STATES = frozenset(
    {1, 4, 5, 7, 11, 16, 17, 18, 26, 29, 6301, 6302, 6303, 6304, 6305, 6306, 6307}
)
RETURNING_STATES = frozenset({6, 15})
DOCKED_STATES = frozenset({8, 100, 22, 23, 25})  # charging, full, emptying, washing the mop
IDLE, PAUSED, ERROR, OFFLINE = 3, 10, 12, 101

# The parts (get_consumable's counters) and how long each lasts, as the Roborock app
# counts them (python-roborock's const.py): seconds of work, or for the dock's parts, times.
PARTS: dict[str, tuple[str, int]] = {
    "main_brush_work_time": ("main brush", 1_080_000),
    "side_brush_work_time": ("side brush", 720_000),
    "filter_work_time": ("filter", 540_000),
    "sensor_dirty_time": ("sensors", 108_000),
    "strainer_work_times": ("dock's water filter", 150),
    "cleaning_brush_work_times": ("dock's cleaning brush", 300),
    "dust_collection_work_times": ("dock's dust bag", 90),
    "moproller_work_time": ("mop roller", 1_080_000),
}
LOW_PART = 0.05  # under this share left, it's time


@dataclass(frozen=True)
class VacuumStatus:
    state: int
    error: int
    dock_error: int
    battery: int | None
    clean_water_out: bool
    dirty_water_full: bool

    @property
    def docked(self) -> bool:
        return self.state in DOCKED_STATES

    @property
    def cleaning(self) -> bool:
        return self.state in CLEANING_STATES

    @property
    def returning(self) -> bool:
        return self.state in RETURNING_STATES

    @property
    def alert(self) -> int | None:
        """The code "Resolved" in the app would clear: the dock's first, then the robot's."""
        return self.dock_error or self.error or None


@dataclass(frozen=True)
class VacuumEvent:
    """A problem starting, or (`gone`) ending. `room`: where the robot is, for stuck and
    not_docked, when its map says."""

    device_id: int
    kind: str
    detail: str
    at: datetime
    gone: bool = False
    room: str | None = None


def read_status(raw: dict[str, Any]) -> VacuumStatus:
    """The status as the robot reports it (get_status)."""
    dss = _int(raw.get("dss"))
    return VacuumStatus(
        state=_int(raw.get("state")),
        error=_int(raw.get("error_code")),
        dock_error=_int(raw.get("dock_error_status")),
        battery=_int(raw["battery"]) if raw.get("battery") is not None else None,
        # The dock's tank bits (python-roborock's StatusV2): 1 means empty, or full/out.
        clean_water_out=bool(dss) and (dss >> 2) & 3 == 1,
        dirty_water_full=bool(dss) and (dss >> 4) & 3 == 1,
    )


def problems(status: VacuumStatus) -> dict[str, str]:
    """Each kind of problem it has now, with the words for it."""
    found: dict[str, str] = {}
    for code, table in ((status.dock_error, DOCK), (status.error, ROBOT)):
        if not code:
            continue
        kind, words = table.get(code, (FAULT, f"it's showing error {code}"))
        found.setdefault(kind, words)
    if status.clean_water_out:
        found.setdefault(WATER_EMPTY, "the clean-water tank is empty")
    if status.dirty_water_full:
        found.setdefault(WATER_FULL, "the dirty-water tank is full")
    if status.state == IDLE and not status.error:
        found.setdefault(NOT_DOCKED, "it stopped away from the dock")
    if found.get(NOT_DOCKED) == ROBOT[12][1] and status.docked:
        del found[NOT_DOCKED]  # low, but on the dock: it's charging
    return found


def unknown_codes(status: VacuumStatus) -> list[str]:
    """Codes Themi has no words for (logged once each, so the table can grow)."""
    found = []
    if status.error and status.error not in ROBOT:
        found.append(f"robot error {status.error}")
    if status.dock_error and status.dock_error not in DOCK:
        found.append(f"dock error {status.dock_error}")
    return found


def low_parts(counters: dict[str, int]) -> dict[str, str]:
    """The parts nearly worn out: their counter name, and the part's name."""
    low = {}
    for name, used in counters.items():
        if name not in PARTS or used is None:
            continue
        part, lasts = PARTS[name]
        if (lasts - int(used)) / lasts < LOW_PART:
            low[name] = part
    return low


def state_word(status: VacuumStatus) -> str:
    """Its state in a few words, for the Family page and a status question."""
    if status.state == OFFLINE:
        return "offline"
    if status.error or status.state == ERROR:  # a dock alert alone: still on its dock
        return "stopped with a problem"
    if status.cleaning:
        return "cleaning"
    if status.returning:
        return "returning to its dock"
    if status.state == 8:
        return "charging on its dock"
    if status.docked:
        return "on its dock"
    if status.state == PAUSED:
        return "paused"
    return "away from its dock"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
