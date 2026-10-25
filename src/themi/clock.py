"""The only source of "now" in Themi.

Business logic must read time from here, never from `datetime.now()` or
`time.time()`, so tests and simulations can freeze and move it.
`tools/check_clock.py` enforces this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_frozen: datetime | None = None


def now() -> datetime:
    """Current time, timezone-aware (UTC unless frozen at another zone)."""
    return _frozen if _frozen is not None else datetime.now(UTC)


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


def unfreeze() -> None:
    """Return to real time."""
    global _frozen
    _frozen = None


def is_frozen() -> bool:
    return _frozen is not None
