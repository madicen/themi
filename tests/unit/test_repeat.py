"""Chore schedules in words (F7): parsing, read-back, and the next occurrences."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from themi.core.repeat import Repeat, RepeatError, next_occurrences, parse, read_back

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
