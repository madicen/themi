"""33: when a maintenance item is due, across its active months, and how that's said."""

from __future__ import annotations

from datetime import date

import pytest

from themi_home.maintenance import (
    Item,
    due_on,
    every_words,
    in_season,
    month_numbers,
    months_words,
)

SPRING_TO_FALL = (3, 4, 5, 6, 7, 8, 9, 10)  # March to October


def item(interval: int = 90, months: tuple[int, ...] = (), first: date = date(2026, 1, 1)) -> Item:
    return Item(1, "Fertilize the trees", interval, months, (), None, first, None, None, None, None)


def test_due_its_interval_after_it_was_last_done() -> None:
    assert due_on(item(90), date(2026, 8, 1), date(2026, 9, 1)) == date(2026, 10, 30)


def test_never_done_its_due_on_its_first_day() -> None:
    assert due_on(item(90, first=date(2026, 11, 4)), None, date(2026, 11, 4)) == date(2026, 11, 4)


def test_due_out_of_season_waits_for_the_seasons_first_day() -> None:
    # Done 1 Oct, due 60 days on (30 Nov): out of season, so 1 March.
    assert due_on(item(60, SPRING_TO_FALL), date(2026, 10, 1), date(2026, 10, 2)) == date(
        2027, 3, 1
    )


def test_due_in_season_stays_put() -> None:
    assert due_on(item(30, SPRING_TO_FALL), date(2026, 5, 1), date(2026, 5, 2)) == date(2026, 5, 31)


def test_overdue_as_the_season_ends_waits_for_the_next_one() -> None:
    # Due 20 October and not done; by November it's out of season until March.
    assert due_on(item(30, SPRING_TO_FALL), date(2026, 9, 20), date(2026, 11, 4)) == date(
        2027, 3, 1
    )
    # Still in October, it's simply overdue.
    assert due_on(item(30, SPRING_TO_FALL), date(2026, 9, 20), date(2026, 10, 25)) == date(
        2026, 10, 20
    )


def test_a_season_across_new_year() -> None:
    winter = (11, 12, 1, 2)
    assert in_season(date(2026, 3, 15), winter) == date(2026, 11, 1)
    assert in_season(date(2026, 12, 15), winter) == date(2026, 12, 15)
    assert due_on(item(45, winter), date(2026, 12, 20), date(2027, 1, 1)) == date(2027, 2, 3)


def test_all_year_is_any_day() -> None:
    assert in_season(date(2026, 7, 4), ()) == date(2026, 7, 4)


def test_how_often_in_words() -> None:
    assert every_words(90) == "every 90 days"
    assert every_words(14) == "every 2 weeks"
    assert every_words(7) == "every week"
    assert every_words(365) == "once a year"
    assert every_words(1) == "every day"


def test_the_months_in_words() -> None:
    assert months_words(()) == "all year"
    assert months_words(SPRING_TO_FALL) == "March to October"
    assert months_words((11, 12, 1, 2)) == "November to February"
    assert months_words((3, 6, 9)) == "March, June and September"
    assert months_words((4, 10)) == "April and October"


def test_month_names_from_chat() -> None:
    assert month_numbers(["March", "april", "Sept"]) == (3, 4, 9)
    assert month_numbers(["All year"]) == ()
    with pytest.raises(ValueError, match="isn't a month"):
        month_numbers(["Smarch"])
