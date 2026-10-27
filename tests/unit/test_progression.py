"""F9c: a plan that steps up week by week (Erin's runs): parsing, the amount on a day, and
the read-back."""

from datetime import date, timedelta

import pytest

from themi.core.progression import Progression, ProgressionError, parse_plan, read_back

MON = date(2026, 10, 26)  # the day Erin said "next week is 1.3 miles"
TUE = date(2026, 10, 27)


def test_erins_plan() -> None:
    plan = parse_plan("1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays", MON)
    assert plan == Progression(
        unit="miles", amounts=(1.3, 1.5), step=0.25, weekday=1, start=TUE, up_to=None
    )
    assert plan.amount_on(MON) is None  # it hasn't started
    assert [plan.amount_on(TUE + timedelta(days=n)) for n in (0, 6, 7, 13, 14, 21)] == [
        1.3,
        1.3,  # all week, through Monday
        1.5,
        1.5,
        1.75,
        2.0,
    ]
    assert read_back(plan) == (
        "1.3 miles from Tue 27 Oct, then 1.5, then up 0.25 a week; it steps up on Tuesdays"
    )
    assert Progression.from_json(plan.to_json()) == plan


def test_a_plan_can_stop_somewhere_and_start_on_a_date() -> None:
    plan = parse_plan("2 km, up 0.5 a week up to 5 km, starting 2 Nov, on Mondays", MON)
    assert (plan.start, plan.weekday, plan.amounts, plan.up_to) == (date(2026, 11, 2), 0, (2,), 5)
    assert plan.amount_on(date(2026, 11, 2) + timedelta(weeks=10)) == 5
    assert read_back(plan) == (
        "2 km from Mon 02 Nov, then up 0.5 a week, up to 5 km; it steps up on Mondays"
    )
    flat = parse_plan("1.3 miles, then 1.5", MON)  # no step: it stays at the last one
    assert flat.weekday == 0 and flat.amount_on(MON + timedelta(weeks=5)) == 1.5
    assert flat.start == MON  # starts on its step day: today, a Monday


def test_amounts_read_without_float_noise() -> None:
    plan = parse_plan("1.3 miles, up 0.1 a week", MON)
    assert plan.words_on(MON + timedelta(weeks=2)) == "1.5 miles this week"


@pytest.mark.parametrize(
    "words", ["", "run more", "miles, then more", "1.3 miles, then down 0.25 a week", "0 miles"]
)
def test_unclear_plans_are_refused_with_an_example(words: str) -> None:
    with pytest.raises(ProgressionError, match=r"1\.3 miles, then 1\.5"):
        parse_plan(words, MON)
