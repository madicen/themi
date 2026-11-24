"""A litter box's report, read (CG1a, CG1b): how it's doing, and what it needs a person for.

What PetNovations reports for a device (`device/device/v2`, from the community client's
models, checked 2026-11-04):

- `reportedStatus`: "connected" when it's online.
- `operationStatus`: `state` (1 while cleaning), `progress` (0-100, 255 when idle) and
  `error` (text, empty when fine).
- `activeErrors`: a list whose entries nobody has documented yet.
- `remainingSaniSolution`: how many cleans the cartridge has left, on every box. F41a (bug
  #197, "480% sani-solution") found it on the Whoosh (`fwVersion` 100.x) and kept the A.I.
  (8.x) as a percent; F58b (bug #252) found the A.I. counts cleans too: a new cartridge
  read 239, then 238 after one clean.
- `lastClean`, and `configuration.activation.count`: its cleaning cycles, ever.

There's no granule (litter) level: the granules' chore counts cycles instead
(`themi_home.litter_box`).

Errors are put in words by `CODES`, written from captures (`themi catgenie capture`, into
`tests/fixtures/catgenie`, or the Pi's `litter_problems`), never guessed. Until a code is
there, it's still a problem, in plain words from the code itself (a bare number is said to
be a code Themi doesn't know yet, F58b), and logged once.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ERROR, ALERT, SOLUTION, GRANULES = "error", "alert", "solution", "granules"
LOW, OUT = "running low on sani-solution", "out of sani-solution"
LOW_CLEANS = 30  # cleans left at or under this is running low (about ten days at three a day)
CLEANS = "cleans"  # F58b: every box's sani-solution is a count of cleans
GRANULES_TEXT = "due a granule top-up"

# An error code (as the box or an alert gives it) -> words. From captures only.
CODES: dict[str, str] = {
    # F58b (bug #248): the Whoosh on 11 Nov and the A.I. on 22 Nov each showed error 6 while
    # out of sani-solution, and both cleared with the new cartridge (`litter_problems` 1-4).
    "6": OUT,
    # F60b (bug #261): the Whoosh showed 3 on 24 Nov (`litter_problems` 6); the app said
    # "Error: Drainage issue".
    "3": "it's showing a drainage issue",
}
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
    sani_left: int | None = None  # cleans left
    sani_unit: str = CLEANS  # always CLEANS since F58b (kept: `litter_states` stores it)
    cycles: int | None = None  # cleaning cycles ever
    errors: tuple[str, ...] = ()  # codes, as it reports them
    # F60b: codes the family told Themi the words for (`litter_codes`), as (code, words)
    named: tuple[tuple[str, str], ...] = ()

    @property
    def problems(self) -> dict[str, str]:
        """What it needs a person for: kind -> words."""
        found: dict[str, str] = {}
        # F58b: a code that means the cartridge is out is the solution's problem, not an
        # error of its own (no second message, chore or wall item).
        errors = [e for e in self.errors if CODES.get(e) != OUT]
        if errors:
            found[ERROR] = "; ".join(error_words(e, dict(self.named)) for e in errors)
        if len(errors) < len(self.errors) or (self.sani_left is not None and self.sani_left <= 0):
            found[SOLUTION] = OUT
        elif self.sani_left is not None and self.sani_left <= LOW_CLEANS:
            found[SOLUTION] = LOW
        return found

    @property
    def unknown(self) -> tuple[str, ...]:
        named = dict(self.named)
        return tuple(e for e in self.errors if e not in CODES and e not in named)


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


def read_device(raw: dict[str, Any], named: Mapping[str, str] | None = None) -> LitterBoxReading:
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
    sani = _int(raw.get("remainingSaniSolution"))
    return LitterBoxReading(
        online=str(raw.get("reportedStatus") or "").lower() == "connected",
        cleaning=cleaning,
        progress=progress if cleaning and progress is not None and 0 <= progress <= 100 else None,
        last_clean=_time(raw.get("lastClean")),
        sani_left=sani if sani is None or sani >= 0 else None,
        cycles=_int(activation.get("count")),
        errors=tuple(dict.fromkeys(e for e in errors if e.lower() not in NOT_AN_ERROR)),
        named=tuple(sorted((named or {}).items())),
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


def sani_words(left: int, unit: str = CLEANS) -> str:
    """ "477 cleans of sani-solution left" (`unit` is kept for callers; it's always cleans)."""
    return f"{left} clean{'' if left == 1 else 's'} of sani-solution left"


def named_words(words: str) -> str:
    """F60b: what the family said the app shows, as the words a message uses."""
    return f"it's showing {words}"


def error_words(code: str, named: Mapping[str, str] | None = None) -> str:
    """ "it shows an error (heater fault)" until a capture gives the code its words. A bare
    number says nothing to a person, so it's called a code Themi doesn't know (F58b), until
    someone tells Themi what the app calls it (F60b, `named`)."""
    if code in CODES:
        return CODES[code]
    if named and code in named:
        return named_words(named[code])
    if code.strip().isdigit():
        return (
            f"it's showing a code Themi doesn't know yet ({code.strip()}), "
            "which the CatGenie app can explain"
        )
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
