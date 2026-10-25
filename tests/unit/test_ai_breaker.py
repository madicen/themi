from datetime import datetime, timedelta

from themi import clock
from themi.ai.breaker import BreakerBoard, BreakerState

ERIN, CLAUDE, GEMINI = 1, 10, 11


def test_opens_after_five_consecutive_failures(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(4):
        board.record_failure(ERIN, CLAUDE)
    assert board.state(ERIN, CLAUDE) is BreakerState.CLOSED and board.allow(ERIN, CLAUDE)
    board.record_failure(ERIN, CLAUDE)
    assert board.state(ERIN, CLAUDE) is BreakerState.OPEN
    assert not board.allow(ERIN, CLAUDE)


def test_success_resets_the_count(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(4):
        board.record_failure(ERIN, CLAUDE)
    board.record_success(ERIN, CLAUDE)
    for _ in range(4):
        board.record_failure(ERIN, CLAUDE)
    assert board.state(ERIN, CLAUDE) is BreakerState.CLOSED


def test_breakers_are_per_member_and_backend(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(5):
        board.record_failure(ERIN, CLAUDE)
    assert board.allow(ERIN, GEMINI)
    assert board.allow(2, CLAUDE)


def test_half_opens_after_five_minutes_and_allows_one_probe(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(5):
        board.record_failure(ERIN, CLAUDE)
    clock.advance(timedelta(minutes=4, seconds=59))
    assert not board.allow(ERIN, CLAUDE)
    clock.advance(timedelta(seconds=1))
    assert board.state(ERIN, CLAUDE) is BreakerState.HALF_OPEN
    assert board.allow(ERIN, CLAUDE)  # the probe
    assert not board.allow(ERIN, CLAUDE)  # nobody else while it's in flight


def test_successful_probe_closes(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(5):
        board.record_failure(ERIN, CLAUDE)
    clock.advance(timedelta(minutes=5))
    assert board.allow(ERIN, CLAUDE)
    board.record_success(ERIN, CLAUDE)
    assert board.state(ERIN, CLAUDE) is BreakerState.CLOSED


def test_failed_probe_reopens_for_a_fresh_cool_down(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(5):
        board.record_failure(ERIN, CLAUDE)
    clock.advance(timedelta(minutes=5))
    assert board.allow(ERIN, CLAUDE)
    board.record_failure(ERIN, CLAUDE)
    assert board.state(ERIN, CLAUDE) is BreakerState.OPEN
    clock.advance(timedelta(minutes=4))
    assert not board.allow(ERIN, CLAUDE)
    clock.advance(timedelta(minutes=1))
    assert board.allow(ERIN, CLAUDE)


def test_released_probe_lets_another_try(frozen_clock: datetime) -> None:
    board = BreakerBoard()
    for _ in range(5):
        board.record_failure(ERIN, CLAUDE)
    clock.advance(timedelta(minutes=5))
    assert board.allow(ERIN, CLAUDE)
    board.release_probe(ERIN, CLAUDE)
    assert board.allow(ERIN, CLAUDE)
