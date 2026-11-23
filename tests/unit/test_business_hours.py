"""F34k: opening hours read from web snippets and their own words."""

from __future__ import annotations

from datetime import time

from themi.standard.business_hours import parse_hours, read_back

NINE_TO_FIVE = (time(8), time(17))


def test_common_listings() -> None:
    hours = parse_hours("Rosewood Dental. Hours: Mon-Fri 8am-5pm, Sat 9am-1pm, Sun closed")
    assert [hours[d] for d in range(5)] == [NINE_TO_FIVE] * 5
    assert hours[5] == (time(9), time(13)) and hours[6] is None
    assert read_back(hours) == "Monday to Friday 8 am-5 pm; Saturday 9 am-1 pm; closed Sunday"


def test_long_names_dashes_and_missing_am_pm() -> None:
    hours = parse_hours("Monday \u2013 Thursday: 8:30 - 5, Friday 8-12")
    assert hours[0] == (time(8, 30), time(17)) and hours[3] == (time(8, 30), time(17))
    assert hours[4] == (time(8), time(12))
    assert hours[5] is None and hours[6] is None  # not mentioned: closed


def test_daily_and_24_hours() -> None:
    assert parse_hours("Open daily 11am-10pm")[6] == (time(11), time(22))
    assert parse_hours("Every day: open 24 hours")[2] == (time(0), time(23, 59))


def test_nothing_to_read() -> None:
    assert parse_hours("Call us at 650-555-0100 for an appointment") == {}


# ----- F58f (bug #253): the time before the days, as people say it ---------------------------

STANFORD = {
    **{d: (time(18, 30), time(20, 30)) for d in range(5)},
    5: (time(12), time(20, 30)),
    6: (time(12), time(20, 30)),
}


def test_the_time_before_the_days_is_read() -> None:
    assert parse_hours("6:30\u20138:30 pm weekdays and 12\u20138:30 pm weekends") == STANFORD
    assert parse_hours("6:30-8:30 pm on weekdays, 12-8:30 pm on weekends") == STANFORD


def test_the_notes_and_the_facts_own_words_are_read() -> None:
    """Place 1's note and fact 12 on the Pi, word for word."""
    note = "Visiting hours: 6:30\u20138:30 pm weekdays and 12\u20138:30 pm weekends."
    fact = "Stanford's visiting hours are 6:30\u20138:30 pm weekdays and 12\u20138:30 pm weekends."
    assert parse_hours(note) == STANFORD
    assert parse_hours(fact) == STANFORD


def test_both_orders_together() -> None:
    hours = parse_hours("9-5 Mon-Fri, Sat 10-2")
    assert hours[0] == (time(9), time(17)) and hours[5] == (time(10), time(14))
    assert hours[6] is None
