import asyncio
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


def test_shift_moves_real_time_ahead_and_keeps_it_ticking() -> None:
    before = clock.now()
    clock.shift(timedelta(hours=3))
    shifted = clock.now()
    assert shifted - before >= timedelta(hours=3)
    assert shifted - before < timedelta(hours=3, minutes=1)
    assert clock.shifted_by() == timedelta(hours=3)
    assert not clock.is_frozen()
    assert clock.now() >= shifted


def test_shifts_add_up_and_never_go_backwards() -> None:
    clock.shift(timedelta(minutes=30))
    clock.shift(timedelta(minutes=30))
    assert clock.shifted_by() == timedelta(hours=1)
    with pytest.raises(ValueError):
        clock.shift(timedelta(minutes=-1))


def test_shift_is_for_real_time_only(frozen_clock: datetime) -> None:
    with pytest.raises(RuntimeError, match="advance"):
        clock.shift(timedelta(hours=1))


def test_unfreeze_clears_a_shift() -> None:
    clock.shift(timedelta(days=1))
    clock.unfreeze()
    assert clock.shifted_by() == timedelta(0)
    assert clock.now() - datetime.now(UTC) < timedelta(seconds=5)


async def test_sleep_on_a_frozen_clock_waits_for_it_to_move() -> None:
    clock.freeze(datetime(2026, 10, 28, 9, tzinfo=UTC))
    try:
        sleeper = asyncio.create_task(clock.sleep(10))
        for _ in range(5):
            await asyncio.sleep(0)
        assert not sleeper.done()
        clock.advance(timedelta(seconds=10))
        await asyncio.wait_for(sleeper, timeout=1)
    finally:
        clock.unfreeze()
