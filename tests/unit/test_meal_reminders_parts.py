"""35a: learning someone's usual gap between meals, and when their waking day began."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tests.fixtures.family import SeededFamily
from themi_home.meals import (
    DEFAULT_GAP,
    GAP_CEILING,
    GAP_FLOOR,
    usual_gap,
    waking_started,
)
from themi_home.takeout import TakeoutSettings, clean_items

TZ = "America/Los_Angeles"
LA = ZoneInfo(TZ)


def day_of_meals(day: int, *hours: float) -> list[datetime]:
    base = datetime(2026, 10, day, tzinfo=LA)
    return [base + timedelta(hours=h) for h in hours]


def test_too_few_gaps_use_the_default() -> None:
    assert usual_gap([], TZ) == DEFAULT_GAP
    assert usual_gap(day_of_meals(1, 8, 12, 18) + day_of_meals(2, 8, 13), TZ) == DEFAULT_GAP


def test_the_gap_is_the_median_times_one_point_three() -> None:
    # gaps of 4, 4, 4, 5 and 5 hours: median 4, so 5.2 hours
    meals = day_of_meals(1, 8, 12, 16) + day_of_meals(2, 7, 11, 15) + day_of_meals(3, 9, 14, 19)
    assert usual_gap(meals, TZ) == timedelta(hours=4) * 1.3


def test_overnight_is_not_a_gap_between_meals() -> None:
    # without the overnight gaps (14, 13 hours) the median is 4 hours
    meals = day_of_meals(1, 8, 12, 16, 20) + day_of_meals(2, 9, 13, 17)
    assert usual_gap(meals, TZ) == timedelta(hours=4) * 1.3


def test_the_order_of_the_log_does_not_matter() -> None:
    meals = day_of_meals(1, 8, 12, 16) + day_of_meals(2, 7, 11, 15)
    assert usual_gap(list(reversed(meals)), TZ) == usual_gap(meals, TZ)


def test_a_grazer_gets_the_floor_and_a_long_faster_the_ceiling() -> None:
    grazing = day_of_meals(1, 8, 9, 10, 11, 12, 13)
    assert usual_gap(grazing, TZ) == GAP_FLOOR
    two_a_day = day_of_meals(1, 7, 19) + day_of_meals(2, 7, 19) + day_of_meals(3, 7, 19)
    two_a_day += day_of_meals(4, 7, 19) + day_of_meals(5, 7, 19)
    assert usual_gap(two_a_day, TZ) == GAP_CEILING


def test_waking_started_is_the_latest_end_of_quiet_hours(family: SeededFamily) -> None:
    erin = family.erin  # quiet 21:30 to 08:00
    assert waking_started(erin, datetime(2026, 10, 21, 13, 0, tzinfo=LA), TZ) == datetime(
        2026, 10, 21, 8, 0, tzinfo=LA
    )
    assert waking_started(erin, datetime(2026, 10, 21, 7, 0, tzinfo=LA), TZ) == datetime(
        2026, 10, 20, 8, 0, tzinfo=LA
    )
    always_awake = family.store.update_settings(
        family.erin, erin.id, quiet_start="00:00", quiet_end="00:00"
    )
    assert always_awake.quiet_start == time(0, 0)
    assert waking_started(always_awake, datetime(2026, 10, 21, 13, 0, tzinfo=LA), TZ) is None


def test_takeout_settings_check_their_times_and_cap() -> None:
    assert TakeoutSettings(dinner_from="5:30", dinner_until="19:00").dinner_from == "05:30"
    for bad in ({"dinner_from": "dinner"}, {"order_cap_cents": 0}):
        try:
            TakeoutSettings(**bad)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")


def test_a_favourites_items_are_tidied() -> None:
    assert clean_items(["- Pad thai ", "", "•  Spring   rolls", "* 2 x Thai tea"]) == (
        "Pad thai",
        "Spring rolls",
        "2 x Thai tea",
    )
