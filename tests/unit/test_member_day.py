"""F34j: a person's "today" goes through `themi.localtime.member_day`, so their rollover
("My day ends at 3 am") counts everywhere. Core may still work out the family's calendar
date, but only in these places, each for a reason; a new one is added here on purpose."""

from __future__ import annotations

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "src" / "themi" / "core"
FAMILY_DATE = re.compile(
    r"clock\.now\(\)\.astimezone\([^)]*\)\)?\.date\(\)|to_local\(clock\.now\(\), [^)]*\)\.date\(\)"
)
ALLOWED = {
    # the family's date when no person is given (each has a member-aware form beside it)
    "tasks.py", "routines.py", "day_summary.py", "habits.py",
    # household things, not one person's day
    "appliances.py", "dishwasher.py", "maintenance.py", "meals.py", "recipe_ideas.py",
    "spending.py",
    # the wall's own day: Cozyla's chart, routines and to-dos are by calendar day
    "chore_chart.py", "cozyla_chores.py", "cozyla_routines.py", "cozyla_todos.py",
    # calendar words ("on Friday", "tomorrow"): the calendar day, as the prompt says
    "commands.py", "events.py", "liaison.py", "reminders.py",
    # a business's opening day is the calendar's
    "business_hours.py",
}  # fmt: skip


def test_a_persons_today_goes_through_member_day() -> None:
    found = {p.name for p in CORE.glob("*.py") if FAMILY_DATE.search(p.read_text())}
    assert found - ALLOWED == set(), (
        "work out a person's day with themi.localtime.member_day, or add the module to "
        "ALLOWED with its reason"
    )
