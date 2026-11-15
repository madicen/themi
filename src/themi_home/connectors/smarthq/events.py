"""The range's ERDs, read and written as the oven sends them (OV1's capture, 2026-11-15).

An ERD is one of GE's numbered appliance values, a hex string. Themi decodes the few it
needs itself, so the words and the tests don't depend on `gehomesdk`'s converters, and the
fake range (`tests/fakes/smarthq.py`) can hold the bytes the real one sent.

The upper oven's codes are `0x51xx`, the lower's `0x52xx`:

- `COOK_MODE` (r/w, 13 bytes): the mode, the set °F (2 bytes), cook time (2), the probe's
  target °F (2), then delay and two-temperature fields. Themi writes all but the first two
  as 0. Mode 0 is off.
- `CURRENT_STATE` (1 byte): what the oven is doing (off, preheating, baking, proofing...).
  A refused write still echoes in `COOK_MODE` for about 45 s, so success is read here.
- `RAW_TEMPERATURE` (2 bytes): the real °F. (`DISPLAY_TEMPERATURE` says 100 for anything
  under 100, so it isn't used.)
- `KITCHEN_TIMER` (r/w, 2 bytes, minutes): the upper oven's only; the lower has none.
- `REMOTE_ENABLED` (1 byte): Remote Enable is on. A cooking oven reports it on even with
  the icon off, and takes a remote off.
- `PROBE_PRESENT` / `PROBE_DISPLAY_TEMP`: the lower oven's probe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

UPPER, LOWER = "upper", "lower"
CAVITIES = (UPPER, LOWER)
NAMES = {UPPER: "upper oven", LOWER: "lower oven"}

# ERD codes by cavity.
_BASE = {UPPER: 0x5100, LOWER: 0x5200}
COOK_MODE, CURRENT_STATE, KITCHEN_TIMER = 0x00, 0x01, 0x05
COOK_TIME_REMAINING, PROBE_DISPLAY_TEMP, PROBE_PRESENT = 0x04, 0x03, 0x07
REMOTE_ENABLED, RAW_TEMPERATURE = 0x0A, 0x0D
READ = (
    COOK_MODE,
    CURRENT_STATE,
    KITCHEN_TIMER,
    COOK_TIME_REMAINING,
    PROBE_DISPLAY_TEMP,
    PROBE_PRESENT,
    REMOTE_ENABLED,
    RAW_TEMPERATURE,
)
MODEL_NUMBER = "0x0001"

# Cook modes (`ErdOvenCookMode`), the ones the family's range offers or Themi sends.
OFF = 0
BAKE = 1
CONV_BAKE = 18
CONV_MULTI_BAKE = 27
CONV_ROAST = 36
PROOF = 13
AIR_FRY = 158
MODE_WORDS = {
    BAKE: "Bake",
    CONV_BAKE: "Convection Bake",
    CONV_MULTI_BAKE: "Convection Multi Bake",
    CONV_ROAST: "Convection Roast",
    PROOF: "Proof",
    AIR_FRY: "Air Fry",
    56: "Frozen Snacks",
    57: "Frozen Snacks",
    58: "Frozen Pizza",
    59: "Frozen Pizza",
    60: "Baked Goods",
}
# What each oven takes from Themi (OV1). Proof isn't in the upper oven's own mode list, but
# it takes mode 13 at exactly 85°F, as the range sends it itself.
OFFERS = {
    UPPER: (BAKE, PROOF),
    LOWER: (BAKE, CONV_MULTI_BAKE, CONV_ROAST),
}
PROOF_F = 85
LOWEST_F, HIGHEST_F = 170, 550  # OVEN_MODE_MIN_MAX_TEMP
TIMER_OVEN = UPPER  # the only one with a kitchen timer

# Current states (`ErdOvenState`).
STATE_OFF = 0
PREHEATING = frozenset({1, 2, 3, 4})
COOKING = frozenset({5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17})
WARM, STATE_PROOF, SABBATH, DELAY = 18, 19, 20, 27
CLEANING = frozenset({21, 22, 23, 24, 25, 26})


def code(cavity: str, erd: int) -> str:
    """The ERD's code as gehomesdk and the oven write it: "0x5101"."""
    return f"0x{_BASE[cavity] + erd:04x}"


@dataclass(frozen=True)
class OvenReading:
    """One oven, as it last reported."""

    cavity: str
    state: int  # CURRENT_STATE
    mode: int  # COOK_MODE's mode
    set_f: int  # COOK_MODE's °F (0 when off)
    temp_f: int | None  # RAW_TEMPERATURE
    timer_minutes: int | None  # KITCHEN_TIMER (None: this oven has none)
    cook_minutes_left: int | None
    remote: bool
    probe_f: int | None  # with a probe in
    read_at: datetime | None = None
    probe_target_f: int | None = None  # COOK_MODE's probe field, when a target is set
    raw: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def on(self) -> bool:
        return self.state != STATE_OFF

    @property
    def preheating(self) -> bool:
        return self.state in PREHEATING

    @property
    def heated(self) -> bool:
        """At its temperature: cooking (past preheat), proofing or keeping warm."""
        return self.state in COOKING or self.state in (STATE_PROOF, WARM)


def _int(raw: str | None, start: int = 0, length: int | None = None) -> int | None:
    if not raw:
        return None
    part = raw[start * 2 : (start + length) * 2] if length is not None else raw[start * 2 :]
    try:
        return int(part, 16)
    except ValueError:
        return None


def read(cavity: str, raw: dict[str, str], at: datetime | None = None) -> OvenReading:
    """An oven's reading from its raw ERDs (codes as `code()` writes them)."""

    def get(erd: int) -> str | None:
        return raw.get(code(cavity, erd))

    cook = get(COOK_MODE) or ""
    temp = _int(get(RAW_TEMPERATURE), 0, 2)
    timer = _int(get(KITCHEN_TIMER), 0, 2) if code(cavity, KITCHEN_TIMER) in raw else None
    probe_in = _int(get(PROBE_PRESENT), 0, 1)
    probe = _int(get(PROBE_DISPLAY_TEMP), 0, 2) if probe_in else None
    left = _int(get(COOK_TIME_REMAINING), 0, 2)
    return OvenReading(
        cavity=cavity,
        state=_int(get(CURRENT_STATE), 0, 1) or STATE_OFF,
        mode=_int(cook, 0, 1) or OFF,
        set_f=_int(cook, 1, 2) or 0,
        temp_f=temp,
        timer_minutes=timer,
        cook_minutes_left=left or None,
        remote=bool(_int(get(REMOTE_ENABLED), 0, 1)),
        probe_f=probe or None,
        read_at=at,
        probe_target_f=_int(cook, 5, 2) or None,
        raw={k: v for k, v in raw.items() if k.startswith(code(cavity, 0)[:4])},
    )


# ----- writing -----------------------------------------------------------------------------


def cook_value(mode: int, temp_f: int) -> str:
    """COOK_MODE's 13 bytes: mode, °F, and the timed fields at 0 (as the range sends Proof:
    "0D0055" and ten zero bytes)."""
    return f"{mode:02X}{temp_f:04X}" + "00" * 10


OFF_VALUE = "00" * 13


def timer_value(minutes: int) -> str:
    return f"{minutes:04X}"


# ----- words ---------------------------------------------------------------------------------


def mode_words(mode: int) -> str:
    return MODE_WORDS.get(mode, "cooking")


def state_words(reading: OvenReading) -> str:
    """What the oven is doing, for a person: "preheating to 400°F (285°F now)"."""
    s = reading.state
    if s == STATE_OFF:
        return "off"
    if s in PREHEATING:
        now = f" ({reading.temp_f}°F now)" if reading.temp_f and reading.temp_f > 100 else ""
        return f"preheating to {reading.set_f}°F for {mode_words(reading.mode)}{now}"
    if s == STATE_PROOF:
        return "proofing (85°F)"
    if s == WARM:
        return "keeping food warm"
    if s in CLEANING:
        return "self-cleaning"
    if s == DELAY:
        return "waiting on a delayed start"
    if s == SABBATH:
        return "in Sabbath mode"
    if reading.set_f:
        return f"on {mode_words(reading.mode)} at {reading.set_f}°F, preheated"
    return f"on {mode_words(reading.mode)}"
