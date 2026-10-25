"""The only source of "now" in Themi.

Business logic must read time from here, never from `datetime.now()` or
`time.time()`, so tests and simulations can freeze and move it.
`tools/check_clock.py` enforces this. `shift()` is the one exception to
"tests only": the local dev runner uses it to skip a running Themi ahead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_frozen: datetime | None = None
_shift = timedelta(0)


def now() -> datetime:
    """Current time, timezone-aware (UTC unless frozen at another zone)."""
    return _frozen if _frozen is not None else datetime.now(UTC) + _shift


def freeze(at: datetime) -> None:
    """Pin the clock at `at`, which must be timezone-aware."""
    global _frozen
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("freeze() needs a timezone-aware datetime")
    _frozen = at


def advance(delta: timedelta) -> datetime:
    """Move a frozen clock forward by `delta` and return the new time."""
    global _frozen
    if _frozen is None:
        raise RuntimeError("advance() needs a frozen clock; call freeze() first")
    if delta < timedelta(0):
        raise ValueError("advance() only moves forward")
    _frozen = _frozen + delta
    return _frozen


def shift(delta: timedelta) -> datetime:
    """Move the real (unfrozen) clock ahead by `delta`; it keeps ticking from there."""
    global _shift
    if _frozen is not None:
        raise RuntimeError("shift() is for the real clock; use advance() on a frozen one")
    if delta < timedelta(0):
        raise ValueError("shift() only moves forward")
    _shift = _shift + delta
    return now()


def shifted_by() -> timedelta:
    """How far shift() has moved the clock ahead of real time."""
    return _shift


def unfreeze() -> None:
    """Return to real time, undoing any shift."""
    global _frozen, _shift
    _frozen = None
    _shift = timedelta(0)


def is_frozen() -> bool:
    return _frozen is not None
