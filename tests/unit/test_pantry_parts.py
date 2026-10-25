from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from themi.accounts import InvalidValue
from themi.connectors.ourgroceries.mirror import backoff
from themi.core.groceries import and_list, item_name
from themi.core.pantry import probably_low, typical_interval

START = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


def every(days: int, times: int, start: datetime = START) -> list[datetime]:
    return [start + timedelta(days=days * n) for n in range(times)]


# ----- names -----------------------------------------------------------------------


def test_item_names_are_plain_and_comparable() -> None:
    assert item_name("  Olive   Oil! ") == "olive oil"
    assert item_name("Ben & Jerry's") == "ben & jerry's"
    assert item_name("cat-food") == "cat-food"
    for bad in ("", "   ", "!!!", "x" * 61):
        with pytest.raises(InvalidValue):
            item_name(bad)
    assert and_list(["eggs"]) == "eggs"
    assert and_list(["eggs", "rice"]) == "eggs and rice"
    assert and_list(["eggs", "rice", "coffee"]) == "eggs, rice and coffee"


# ----- prediction on synthetic histories -------------------------------------------


def test_too_little_history_predicts_nothing() -> None:
    assert typical_interval([]) is None
    assert typical_interval(every(7, 2)) is None
    # Same-day purchases count once.
    assert typical_interval([START, START + timedelta(hours=2), START + timedelta(days=7)]) is None
    assert not probably_low(every(7, 2), START + timedelta(days=90))


def test_a_weekly_staple_is_low_a_week_after_the_last_purchase() -> None:
    bought = every(7, 4)  # days 0, 7, 14, 21
    assert typical_interval(bought) == timedelta(days=7)
    assert not probably_low(bought, START + timedelta(days=27))
    assert probably_low(bought, START + timedelta(days=28))


def test_the_median_ignores_one_odd_gap() -> None:
    days = [0, 10, 20, 30, 75, 85]  # one long trip away
    bought = [START + timedelta(days=d) for d in days]
    assert typical_interval(bought) == timedelta(days=10)
    assert not probably_low(bought, START + timedelta(days=94))
    assert probably_low(bought, START + timedelta(days=95))


def test_saying_it_was_restocked_restarts_the_clock() -> None:
    bought = every(7, 4)
    now = START + timedelta(days=30)
    assert probably_low(bought, now)
    assert not probably_low(bought, now, restocked=START + timedelta(days=26))


@given(
    gap=st.integers(min_value=1, max_value=60),
    times=st.integers(min_value=3, max_value=12),
    wait=st.integers(min_value=0, max_value=120),
)
def test_regular_purchases_predict_exactly_one_gap_later(gap: int, times: int, wait: int) -> None:
    bought = every(gap, times)
    now = bought[-1] + timedelta(days=wait)
    assert typical_interval(bought) == timedelta(days=gap)
    assert probably_low(bought, now) == (wait >= gap)


# ----- the mirror's retry delays ---------------------------------------------------


def test_mirror_backoff_doubles_up_to_an_hour() -> None:
    assert [backoff(n) for n in (1, 2, 3, 4)] == [timedelta(minutes=m) for m in (1, 2, 4, 8)]
    assert backoff(30) == timedelta(hours=1)
