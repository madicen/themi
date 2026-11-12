"""A litter box's report, read (CG1a, CG1b): how it's doing, and what it needs a person for.

What PetNovations reports for a device (`device/device/v2`, from the community client's
models, checked 2026-11-04):

- `reportedStatus`: "connected" when it's online.
- `operationStatus`: `state` (1 while cleaning), `progress` (0-100, 255 when idle) and
  `error` (text, empty when fine).
- `activeErrors`: a list whose entries nobody has documented yet.
- `remainingSaniSolution`: the cartridge's sani-solution left. On the A.I. (`fwVersion` 8.x)
  it's a percent. On the Whoosh (`fwVersion` 100.x) it's how many cleans are left, as its app
  shows it (F41a, bug #197: "480% sani-solution").
- `lastClean`, and `configuration.activation.count`: its cleaning cycles, ever.

There's no granule (litter) level: the granules' chore counts cycles instead
(`themi_home.litter_box`).

Errors are put in words by `CODES`, written from captures (`themi catgenie capture`, into
`tests/fixtures/catgenie`), never guessed. Until a code is there, it's still a problem, in
plain words from the code itself, and logged once.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ERROR, ALERT, SOLUTION, GRANULES = "error", "alert", "solution", "granules"
LOW, OUT = "running low on sani-solution", "out of sani-solution"
LOW_PERCENT = 20  # sani-solution left at or under this is running low (as the feeders' food)
LOW_CLEANS = 30  # the Whoosh: cleans left at or under this (about ten days at three a day)
PERCENT, CLEANS = "%", "cleans"
WHOOSH_FIRMWARE = 100  # a firmware major version this high or more counts cleans (F41a)
GRANULES_TEXT = "due a granule top-up"

# An error code (as the box or an alert gives it) -> words. From captures only.
CODES: dict[str, str] = {}
# A notification's `type` -> what it is, once captures show which are errors. Until then a
# notification is an error only when its `errorType` says one.
ALERT_TYPES: dict[int, str] = {}
NOT_AN_ERROR = frozenset({"", "0", "none", "null", "ok", "no_error", "noerror", "false"})


@dataclass(frozen=True)
class LitterBoxReading:
    online: bool
    cleaning: bool = False
    progress: int | None = None  # % through a clean, while cleaning
    last_clean: datetime | None = None
    sani_left: int | None = None  # in `sani_unit`
    sani_unit: str = PERCENT  # PERCENT, or CLEANS on the Whoosh
    odd_sani: int | None = None  # a percent over 100, left out of `sani_left` (logged once)
    cycles: int | None = None  # cleaning cycles ever
    errors: tuple[str, ...] = ()  # codes, as it reports them

    @property
    def problems(self) -> dict[str, str]:
        """What it needs a person for: kind -> words."""
        found: dict[str, str] = {}
        if self.errors:
            found[ERROR] = "; ".join(error_words(e) for e in self.errors)
        low = LOW_CLEANS if self.sani_unit == CLEANS else LOW_PERCENT
        if self.sani_left is not None and self.sani_left <= 0:
            found[SOLUTION] = OUT
        elif self.sani_left is not None and self.sani_left <= low:
            found[SOLUTION] = LOW
        return found

    @property
    def unknown(self) -> tuple[str, ...]:
        return tuple(e for e in self.errors if e not in CODES)


@dataclass(frozen=True)
class Alert:
    """One of the app's notifications, read."""

    alert_id: str
    manufacturer_id: str  # the litter box it's about ("parentDeviceId")
    kind: int | None
    error: str  # its `errorType`, or what `ALERT_TYPES` makes of its type; "" if not an error
    at: datetime | None


@dataclass(frozen=True)
class LitterBoxEvent:
    device_id: int
    kind: str  # ERROR, ALERT, SOLUTION or GRANULES
    detail: str  # in words
    at: datetime
    gone: bool = False  # it stopped showing it


def read_device(raw: dict[str, Any]) -> LitterBoxReading:
    status = raw.get("operationStatus")
    status = status if isinstance(status, dict) else {}
    config = raw.get("configuration")
    config = config if isinstance(config, dict) else {}
    activation = config.get("activation")
    activation = activation if isinstance(activation, dict) else {}
    cleaning = _int(status.get("state")) == 1
    progress = _int(status.get("progress"))
    errors = [str(status.get("error") or "").strip()]
    errors += [_label(entry) for entry in raw.get("activeErrors") or []]
    unit = sani_unit(raw.get("fwVersion"))
    sani = _int(raw.get("remainingSaniSolution"))
    odd = sani if unit == PERCENT and sani is not None and sani > 100 else None
    return LitterBoxReading(
        online=str(raw.get("reportedStatus") or "").lower() == "connected",
        cleaning=cleaning,
        progress=progress if cleaning and progress is not None and 0 <= progress <= 100 else None,
        last_clean=_time(raw.get("lastClean")),
        sani_left=None if odd is not None else sani,
        sani_unit=unit,
        odd_sani=odd,
        cycles=_int(activation.get("count")),
        errors=tuple(dict.fromkeys(e for e in errors if e.lower() not in NOT_AN_ERROR)),
    )


def read_alert(raw: dict[str, Any]) -> Alert:
    try:
        data = json.loads(raw.get("data") or "{}")
    except (TypeError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    kind = _int(data.get("type"))
    error = str(data.get("errorType") or "").strip()
    if error.lower() in NOT_AN_ERROR:
        error = ALERT_TYPES.get(kind, "") if kind is not None else ""
    return Alert(
        str(raw.get("id") or ""),
        str(data.get("parentDeviceId") or ""),
        kind,
        error,
        _time(data.get("eventTimestamp")) or _time(raw.get("creationTime")),
    )


def sani_unit(firmware: Any) -> str:
    """CLEANS for the Whoosh (firmware 100.x or later), else PERCENT (also when unreadable)."""
    found = re.match(r"\s*(\d+)", str(firmware or ""))
    return CLEANS if found and int(found.group(1)) >= WHOOSH_FIRMWARE else PERCENT


def sani_words(left: int, unit: str) -> str:
    """ "56% sani-solution left", or on the Whoosh "477 cleans of sani-solution left"."""
    if unit == CLEANS:
        return f"{left} clean{'' if left == 1 else 's'} of sani-solution left"
    return f"{left}% sani-solution left"


def error_words(code: str) -> str:
    """ "it shows an error (heater fault)" until a capture gives the code its words."""
    if code in CODES:
        return CODES[code]
    plain = re.sub(r"[_\-]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", code)).strip().lower()
    return f"it shows an error ({plain})"


def state_word(reading: LitterBoxReading) -> str:
    """How it's doing, in words (the Accounts page, the Home page, `appliance_status`)."""
    if not reading.online:
        return "offline"
    if reading.cleaning:
        said = "cleaning" + (f" ({reading.progress}% done)" if reading.progress is not None else "")
    else:
        said = "ready"
    if reading.sani_left is not None:
        said += ", " + sani_words(reading.sani_left, reading.sani_unit)
    if reading.errors:
        said += "; " + "; ".join(error_words(e) for e in reading.errors)
    return said


def _label(entry: Any) -> str:
    """An `activeErrors` entry's code, whatever its shape turns out to be."""
    if isinstance(entry, dict):
        for key in ("errorType", "error", "code", "type", "name"):
            if entry.get(key) not in (None, ""):
                return str(entry[key]).strip()
        return json.dumps(entry, sort_keys=True)
    return str(entry).strip()


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime | None:
    """PetNovations' times have no zone; they're taken as UTC (as the package does)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
