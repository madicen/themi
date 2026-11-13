"""DC11: a step-up plan as a picture: the plan's weeks, this week marked, never what was
missed. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from tests.unit.test_day_card import golden
from themi.drawing.render import to_png
from themi.standard.plan_card import PlanCardData, plan_svg, plan_weeks, view
from themi.standard.progression import parse_plan

TUESDAY = date(2026, 10, 20)


def runs() -> PlanCardData:
    plan = parse_plan("1.3 miles, then 1.5, then up 0.25 a week up to 3 miles, on Tuesdays",
                      date(2026, 10, 6))  # fmt: skip
    return replace(plan_weeks(plan, date(2026, 10, 22)), title="Go for a run")


def test_the_plan_matches_its_golden_files() -> None:
    golden("plan", plan_svg(runs()))
    golden("plan_dark", plan_svg(runs(), "dark"))
    assert to_png(plan_svg(runs()), 1680)[:4] == b"\x89PNG"


def test_the_weeks_step_up_and_this_week_is_marked() -> None:
    data = runs()
    assert data.weeks[0].starts >= date(2026, 10, 6)  # never before the plan starts
    assert [w.amount for w in data.weeks[:4]] == [1.3, 1.5, 1.75, 2.0]
    (now,) = [w for w in data.weeks if w.now]
    assert now.starts == TUESDAY and now.amount == 1.75
    assert max(w.amount for w in data.weeks) == 3  # up to 3 miles
    assert view(data)["cap"] == "up to 3 miles"


def test_only_the_plan_is_drawn() -> None:
    svg = plan_svg(runs()).lower()
    for word in ("missed", "skipped", "done", "late", "behind"):
        assert word not in svg


def test_a_plan_that_starts_later_has_no_this_week() -> None:
    plan = parse_plan("20 minutes, up 5 a week, starting 2 Nov, on Mondays", date(2026, 10, 22))
    data = plan_weeks(plan, date(2026, 10, 22))
    assert not any(w.now for w in data.weeks)
    assert data.weeks[0].amount == 20
