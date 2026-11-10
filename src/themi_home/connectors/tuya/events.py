"""A feeder's data points, read (32): what it needs a person for, and its food level.

Tuya's standard pet feeder (category `cwwsq`, its status set, checked 2026-11-04) reports
`surplus_grain` (food left, %), `feed_report` (portions just fed), `feed_state`,
`battery_percentage` and `charge_state`, but no fault. Real feeders add their own data
points for that, named and typed per model: usually a `fault` bitmap whose labels (from
the device's specification) say what's wrong ("food_shortage", "motor_fault", ...).

So the reading goes in three steps:

1. `MODELS`: a model's own mapping (by Tuya product id), once its data points have been
   captured (`themi tuya capture`) and read. Empty until the family's feeders are.
2. `STANDARD`: Tuya's standard codes.
3. Otherwise by name: a code with "fault", "alarm" or "error" in it is a fault, decoded by
   its type (a bitmap's labels, an enum's word, a flag); a flag or enum about the food
   ("food_shortage", "food_level") is the food.

Each fault label is then put in words and sorted: food low or out, food stuck (a jam), or
some other fault. Unknown labels still become a fault in plain words, and are logged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

FOOD, JAMMED, FAULT = "food", "jammed", "fault"
LOW, OUT = "running low on food", "out of food"
LOW_PERCENT = 20  # food left at or under this is running low

# Roles a data point can play.
LEVEL, FOOD_FLAG, FOOD_STATE, FAULT_CODE, FED, BATTERY = (
    "level",
    "food_flag",
    "food_state",
    "fault",
    "fed",
    "battery",
)
STANDARD = {
    "surplus_grain": LEVEL,
    "feed_report": FED,
    "battery_percentage": BATTERY,
}
# Tuya product id -> {data point code: role}, for a model whose data points the rules
# below misread. Written from captures (tests/fixtures/tuya), never guessed.
MODELS: dict[str, dict[str, str]] = {}

FAULT_NAME = re.compile(r"fault|alarm|error|warn")
FOOD_NAME = re.compile(r"food|grain|feed")
FOOD_STATE_NAME = re.compile(r"level|state|status|surplus|remain")
NOT_A_FAULT = frozenset({"", "0", "none", "normal", "ok", "no_fault", "nofault", "false"})

# Label words -> what it means. Checked in this order: "low_battery" is the battery, not food.
OTHER = (
    (re.compile(r"batt|power"), "the battery's low"),
    (re.compile(r"desicc"), "the desiccant needs changing"),
)
FOOD_OUT = re.compile(r"empty|exhaust|no_?food|out_?of|run_?out|used_?up")
FOOD_LOW = re.compile(r"short|lack|insufficien|low|little|less|not_?enough")
STUCK = re.compile(r"block|clog|jam|stuck|motor|dispens|cannot_?feed|feed_?fail|outlet")


@dataclass(frozen=True)
class FeederReading:
    problems: dict[str, str]  # kind -> words, at most one of each kind
    level: int | None = None  # % of food left, when it says
    battery: int | None = None
    unknown: tuple[str, ...] = ()  # fault labels with no words of Themi's own (logged once)
    feed_codes: tuple[str, ...] = ()  # the data points its feedings are reported on


@dataclass(frozen=True)
class FeederEvent:
    device_id: int
    kind: str  # FOOD, JAMMED or FAULT
    detail: str  # in words: "out of food", "the food's stuck (motor fault)"
    at: datetime
    gone: bool = False  # the feeder stopped showing it


@dataclass
class _Found:
    level: int | None = None
    battery: int | None = None
    food: str | None = None
    stuck: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    fed: list[str] = field(default_factory=list)


def read_status(
    status: list[dict[str, Any]], spec: dict[str, Any] | None = None, product_id: str = ""
) -> FeederReading:
    """A feeder's status (Tuya's [{code, value}]) read with its specification."""
    types = _types(spec)
    model = MODELS.get(product_id, {})
    found = _Found()
    for point in status:
        code, value = str(point.get("code") or ""), point.get("value")
        role = model.get(code) or STANDARD.get(code) or _role(code, types.get(code, {}))
        if role == LEVEL and isinstance(value, int | float) and not isinstance(value, bool):
            found.level = int(value)
        elif role == BATTERY and isinstance(value, int | float) and not isinstance(value, bool):
            found.battery = int(value)
        elif role == FED:
            found.fed.append(code)
        elif role == FOOD_FLAG:
            if value is True:
                _sort_label(code, found)
        elif role == FOOD_STATE:
            word = str(value or "").lower()  # "full", "middle", "low", "empty"...
            if FOOD_OUT.search(word) or word == "none":
                found.food = OUT
            elif FOOD_LOW.search(word) and found.food != OUT:
                found.food = LOW
        elif role == FAULT_CODE:
            for label in _fault_labels(code, value, types.get(code, {})):
                _sort_label(label, found)
    if found.level is not None and found.food is None:
        if found.level <= 0:
            found.food = OUT
        elif found.level <= LOW_PERCENT:
            found.food = LOW
    problems: dict[str, str] = {}
    if found.food:
        problems[FOOD] = found.food
    if found.stuck:
        problems[JAMMED] = f"the food's stuck ({', '.join(found.stuck)})"
    if found.other:
        problems[FAULT] = "; ".join(found.other)
    return FeederReading(
        problems,
        found.level,
        found.battery,
        tuple(found.unknown),
        tuple(found.fed) or ("feed_report",),
    )


def state_word(reading: FeederReading) -> str:
    """What it's like, in words, for the website and a status question."""
    left = f" ({reading.level}% left)" if reading.level is not None else ""
    food = reading.problems.get(FOOD)
    said = f"{food}{left}" if food else (f"plenty of food{left}" if left else "")
    rest = [words for kind, words in reading.problems.items() if kind != FOOD]
    return "; ".join(part for part in (said, *rest) if part) or "fine"


@dataclass(frozen=True)
class FeedCommand:
    """How to feed now (F39a): the writable data point and its portions' range."""

    code: str
    least: int = 1
    most: int = 12

    def clamp(self, portions: int) -> int:
        return max(self.least, min(self.most, portions))


FEED_NOW = re.compile(r"manual_?feed|quick_?feed|feed_?now|meal_?now")


def feed_command(spec: dict[str, Any] | None) -> FeedCommand | None:
    """The specification's writable "feed now" point: Tuya's standard `manual_feed`, or a
    model's own by name, as long as it takes a number of portions. None: it can't be fed
    from here."""
    functions = [p for p in (spec or {}).get("functions", []) if isinstance(p, dict)]
    found = [p for p in functions if str(p.get("code") or "") == "manual_feed"] or [
        p for p in functions if FEED_NOW.search(str(p.get("code") or "").lower())
    ]
    for point in found:
        if str(point.get("type") or "").lower() != "integer":
            continue
        values = point.get("values")
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except ValueError:
                values = {}
        values = values if isinstance(values, dict) else {}
        least = int(values.get("min") or 1) if _is_number(values.get("min")) else 1
        most = int(values["max"]) if _is_number(values.get("max")) else 12
        return FeedCommand(str(point["code"]), max(1, least), max(1, least, most))
    return None


def words(label: str) -> str:
    """ "motor_fault" -> "motor fault"."""
    return re.sub(r"[_\-]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", label)).strip().lower()


def _sort_label(label: str, found: _Found) -> None:
    key = label.lower()
    for pattern, said in OTHER:
        if pattern.search(key):
            if said not in found.other:
                found.other.append(said)
            return
    if (FOOD_OUT.search(key) and FOOD_NAME.search(key)) or key in ("empty", "no_food"):
        found.food = OUT
        return
    if FOOD_LOW.search(key) and (FOOD_NAME.search(key) or key in ("shortage", "lack")):
        if found.food != OUT:
            found.food = LOW
        return
    if STUCK.search(key):
        if words(label) not in found.stuck:
            found.stuck.append(words(label))
        return
    found.unknown.append(label)
    if words(label) not in found.other:
        found.other.append(words(label))


def _role(code: str, kind: dict[str, Any]) -> str | None:
    name = code.lower()
    if FAULT_NAME.search(name):
        return FAULT_CODE
    if FOOD_NAME.search(name) and not name.startswith(("feed_", "quick", "manual", "slow")):
        if kind.get("type", "").lower() == "boolean":
            return FOOD_FLAG
        if FOOD_STATE_NAME.search(name) and kind.get("type", "").lower() == "enum":
            return FOOD_STATE
        if re.search(r"short|lack|low|empty|insufficien", name):
            return FOOD_FLAG
    return None


def _fault_labels(code: str, value: Any, kind: dict[str, Any]) -> list[str]:
    """The faults a fault data point shows, as labels."""
    type_ = str(kind.get("type") or "").lower()
    if isinstance(value, bool) or type_ == "boolean":
        return [code] if value is True else []
    if type_ == "bitmap" or (_is_number(value) and kind.get("label")):
        labels = list(kind.get("label") or [])
        bits = int(value) if _is_number(value) else 0
        shown = [
            labels[i] if i < len(labels) else f"{code} {i}" for i in range(32) if bits >> i & 1
        ]
        return shown
    if _is_number(value):
        return [f"{code} {int(value)}"] if int(value) else []
    word = str(value or "").strip()
    return [] if word.lower() in NOT_A_FAULT else [word]


def _types(spec: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """code -> {"type": ..., plus its values (a bitmap's "label", an enum's "range")}."""
    found: dict[str, dict[str, Any]] = {}
    for point in [*(spec or {}).get("status", []), *(spec or {}).get("functions", [])]:
        code = str(point.get("code") or "")
        if not code or code in found:
            continue
        values = point.get("values")
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except ValueError:
                values = {}
        found[code] = {
            "type": str(point.get("type") or ""),
            **(values if isinstance(values, dict) else {}),
        }
    return found


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
