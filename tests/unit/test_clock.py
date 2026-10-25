from datetime import UTC, datetime, timedelta, timezone

import pytest

from themi import clock


def test_now_is_timezone_aware_when_not_frozen() -> None:
    assert clock.now().tzinfo is not None
    assert not clock.is_frozen()


def test_freeze_pins_time(frozen_clock: datetime) -> None:
    assert clock.now() == frozen_clock
    assert clock.now() == frozen_clock
    assert clock.is_frozen()


def test_freeze_keeps_the_given_zone() -> None:
    pacific = timezone(timedelta(hours=-7))
    at = datetime(2026, 10, 21, 9, 0, tzinfo=pacific)
    clock.freeze(at)
    assert clock.now().utcoffset() == timedelta(hours=-7)
    assert clock.now() == datetime(2026, 10, 21, 16, 0, tzinfo=UTC)


def test_freeze_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.freeze(datetime(2026, 10, 21, 9, 0))  # noqa: DTZ001 - deliberately naive


def test_advance_moves_frozen_clock(frozen_clock: datetime) -> None:
    later = clock.advance(timedelta(hours=8, minutes=30))
    assert later == frozen_clock + timedelta(hours=8, minutes=30)
    assert clock.now() == later


def test_advance_requires_frozen_clock() -> None:
    with pytest.raises(RuntimeError, match="frozen"):
        clock.advance(timedelta(minutes=1))


def test_advance_never_goes_backwards(frozen_clock: datetime) -> None:
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))
    assert clock.now() == frozen_clock


def test_unfreeze_returns_to_real_time(frozen_clock: datetime) -> None:
    clock.unfreeze()
    assert not clock.is_frozen()
    assert clock.now() > frozen_clock
