"""Chore schedules in words (F7): parsing, read-back, and the next occurrences."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from themi.core.repeat import (
    Repeat,
    RepeatError,
    next_occurrences,
    parse,
    read_back,
    round_end,
)

TZ = ZoneInfo("America/Los_Angeles")
WED = date(2026, 10, 21)  # a Wednesday


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("2 times a week", "Twice a week, counted from the last time it was done"),
        ("twice a week", "Twice a week, counted from the last time it was done"),
        ("once a week", "Once a week, counted from the last time it was done"),
        ("3x per week", "3 times a week, counted from the last time it was done"),
        ("every Tuesday at 6pm", "Every Tuesday at 6 pm"),
        ("tuesdays in the evening", "Every Tuesday at 6 pm"),
        ("every tue and fri", "Every Tuesday and Friday"),
        (
            "every monday, wednesday and friday at 7:30 am",
            "Every Monday, Wednesday and Friday at 7:30 am",
        ),
        ("every other monday", "Every other Monday"),
        ("every 2 weeks on thursday", "Every other Thursday"),
        ("every 3 weeks on sunday", "Every 3 weeks on Sunday"),
        ("every day at 9", "Every day at 9 am"),
        ("daily", "Every day"),
        ("every 3 days", "Every 3 days"),
        ("every other day", "Every other day"),
        ("first monday of the month", "The first Monday of each month"),
        ("last friday of every month at noon", "The last Friday of each month at 12 pm"),
        ("the 1st of every month", "The 1st of each month"),
        ("monthly on the 15th", "The 15th of each month"),
    ],
)
def test_phrases_parse_and_read_back(words: str, expected: str) -> None:
    assert read_back(parse(words, WED)) == expected


@pytest.mark.parametrize(
    "words", ["", "sometimes", "every blursday", "8 times a day", "0 times a week"]
)
def test_unclear_phrases_are_refused_with_examples(words: str) -> None:
    with pytest.raises(RepeatError, match="every Tuesday at 6pm"):
        parse(words, WED)


def test_a_repeat_round_trips_through_json() -> None:
    rep = parse("every other monday at 7:30 am", WED)
    assert Repeat.from_json(rep.to_json()) == rep
    assert rep.at == time(7, 30) and rep.start == WED


def test_next_weekly_occurrences() -> None:
    rep = parse("every Tuesday at 6pm", WED)
    after = datetime(2026, 10, 21, 9, tzinfo=TZ)
    assert next_occurrences(rep, after, TZ, 3) == [
        datetime(2026, 10, 27, 18, tzinfo=TZ),
        datetime(2026, 11, 3, 18, tzinfo=TZ),  # after the clocks go back (Nov 1)
        datetime(2026, 11, 10, 18, tzinfo=TZ),
    ]
    assert next_occurrences(rep, after, TZ, 2)[1].utcoffset() != after.utcoffset()  # DST


def test_later_today_counts_and_every_other_week_keeps_its_rhythm() -> None:
    daily = parse("every day at 6pm", WED)
    assert next_occurrences(daily, datetime(2026, 10, 21, 9, tzinfo=TZ), TZ) == [
        datetime(2026, 10, 21, 18, tzinfo=TZ)
    ]
    other = parse("every other wednesday", WED)  # starting this week
    got = next_occurrences(other, datetime(2026, 10, 21, 0, 0, 1, tzinfo=TZ), TZ, 2)
    assert [d.date() for d in got] == [date(2026, 11, 4), date(2026, 11, 18)]


def test_monthly_occurrences() -> None:
    first_monday = parse("first monday of the month", WED)
    after = datetime(2026, 10, 21, 9, tzinfo=TZ)
    assert [d.date() for d in next_occurrences(first_monday, after, TZ, 2)] == [
        date(2026, 11, 2),
        date(2026, 12, 7),
    ]
    fifteenth = parse("monthly on the 15th", WED)
    assert next_occurrences(fifteenth, after, TZ)[0].date() == date(2026, 11, 15)


def test_floating_repeats_have_no_fixed_dates() -> None:
    assert next_occurrences(parse("twice a week", WED), datetime(2026, 10, 21, tzinfo=TZ), TZ) == []


def test_a_course_with_an_end_date() -> None:
    """C2a: the wall's medication courses run until a day ("Mimi pill until 30 Oct")."""
    rep = parse("every 2 days until 30 Oct", WED)
    assert rep.until == date(2026, 10, 30)
    assert read_back(rep) == "Every other day, until Fri 30 Oct"
    assert parse("every Tuesday at 6pm until 2026-11-10", WED).until == date(2026, 11, 10)
    assert Repeat.from_json(rep.to_json()) == rep
    found = next_occurrences(rep, datetime(2026, 10, 21, 12, tzinfo=TZ), TZ, count=10)
    assert [d.date().day for d in found] == [23, 25, 27, 29]  # none after the 30th


@pytest.mark.parametrize("words", ["twice a week until 30 Oct", "every day until 1 Oct"])
def test_end_dates_need_fixed_days_and_the_future(words: str) -> None:
    with pytest.raises(RepeatError):
        parse(words, WED)


def test_an_either_day_round_and_a_rest_rule() -> None:
    """F9a, Erin's runs: "Tuesday, Thursday, and Saturday or Sunday. Never two days in a row."""
    rep = parse("every Tue, Thu and Sat or Sun at 2pm, never two days in a row", WED)
    assert (rep.weekdays, rep.or_days, rep.rest) == ((1, 3, 5), (6,), True)
    assert read_back(rep) == (
        "Every Tuesday, Thursday and Saturday or Sunday at 2 pm, never two days in a row"
    )
    assert Repeat.from_json(rep.to_json()) == rep
    after = datetime(2026, 10, 21, 9, tzinfo=TZ)
    found = next_occurrences(rep, after, TZ, 4)
    assert [d.date().day for d in found] == [22, 24, 27, 29]  # Sunday is no round of its own
    saturday, tuesday = date(2026, 10, 24), date(2026, 10, 27)
    assert (round_end(rep, saturday), round_end(rep, tuesday)) == (date(2026, 10, 25), tuesday)
    assert read_back(parse("every saturday or sunday", WED)) == "Every Saturday or Sunday"
    assert not parse("every tuesday", WED).rest
    assert read_back(parse("every other day, no two days in a row", WED)) == (
        "Every other day, never two days in a row"
    )


@pytest.mark.parametrize(
    "words",
    [
        "every monday or thursday",  # "or" is a day and the one after it
        "twice a week, never two days in a row",  # no fixed days to keep apart
        "first monday or tuesday of the month",
    ],
)
def test_either_days_and_rest_need_fixed_neighbouring_days(words: str) -> None:
    with pytest.raises(RepeatError):
        parse(words, WED)


def test_titles_match_loosely() -> None:
    """Bug #20: event searches by the words people use."""
    from themi.core.events import title_matches

    assert title_matches("tutoring", "Tutor Gabriel (Illems)")
    assert title_matches("pediatrics", "Pediatrician: Rosie")
    assert title_matches("the dentist", "Dentist")
    assert not title_matches("dentist", "Dental cleaning")  # sharing "dent" isn't enough
    assert not title_matches("run", "Brunch")
    assert not title_matches("", "Anything")


def test_a_date_in_a_past_year_is_this_years() -> None:
    """Bug #84: "Friday" became 2020-10-30."""
    from themi.core.tasks import day_arg

    assert day_arg("2020-10-30", WED) == date(2026, 10, 30)
    assert day_arg("2025-01-04", WED) == date(2027, 1, 4)  # this year's has gone
    assert day_arg("2024-02-29", WED) == date(2027, 2, 28)
    assert day_arg("2026-10-01", WED) == date(2026, 10, 1)  # this year: as given


def test_words_in_common_with_a_title() -> None:
    from themi.core.events import words_in_common

    title = "Contact Erin\u2019s parents about babysitting"
    assert words_in_common("We contacted Erin\u2019s parents", title) == 3
    assert words_in_common("We contacted Erin\u2019s parents", "Bring bins in") == 0
    assert words_in_common("done", title) == 0
    assert words_in_common("that's done", "Take out the bins") == 0  # no scraps or fillers


def test_times_relative_to_sunset() -> None:
    """F9b, Erin's runs: "an afternoon check-in at least an hour before sunset"."""
    rep = parse("every Tue, Thu and Sat or Sun at 2pm, at least an hour before sunset", WED)
    assert (rep.at, rep.before_sunset) == (time(14), 60)
    assert read_back(rep) == (
        "Every Tuesday, Thursday and Saturday or Sunday at 2 pm, at least an hour before sunset"
    )
    assert Repeat.from_json(rep.to_json()) == rep
    alone = parse("every day 30 minutes before sunset", WED)
    assert (alone.at, alone.before_sunset, read_back(alone)) == (
        None,
        30,
        "Every day, 30 minutes before sunset",
    )
    assert read_back(parse("every friday at sunset", WED)) == "Every Friday, at sunset"
    with pytest.raises(RepeatError):
        parse("twice a week, an hour before sunset", WED)  # no fixed days
