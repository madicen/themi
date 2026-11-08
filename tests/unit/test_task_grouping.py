"""F32a: tasks grouped on the website, by due date and other ways. Words only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from themi.standard.tasks import Task
from themi.web.task_pages import group_tasks, grouping_of

SATURDAY = date(2026, 10, 24)
SUNDAY = date(2026, 10, 25)
WEDNESDAY = date(2026, 10, 21)


def task(n: int, due: date | None = None, **fields: Any) -> Task:
    values: dict[str, Any] = {
        "id": n, "title": f"Task {n}", "kind": "text", "effort": 1, "assignee": 1,
        "default_owner": 1, "assign_reason": "", "status": "open", "due_on": due,
    }  # fmt: skip
    return Task(**(values | fields))


def headings(groups: list[tuple[str, list[Task]]]) -> list[tuple[str, list[int]]]:
    return [(h, [t.id for t in tasks]) for h, tasks in groups]


def test_by_due_date_on_a_wednesday() -> None:
    d = WEDNESDAY
    tasks = [
        task(1),
        task(2, d - timedelta(days=3)),
        task(3, d),
        task(4, d + timedelta(days=1)),
        task(5, d + timedelta(days=4)),  # Sunday: this week
        task(6, d + timedelta(days=5)),  # next Monday
        task(7, d + timedelta(days=11)),  # next Sunday
        task(8, d + timedelta(days=12)),
        task(9, d - timedelta(days=1)),
    ]
    assert headings(group_tasks(tasks, "due", d)) == [
        ("Overdue", [2, 9]),
        ("Today", [3]),
        ("Tomorrow", [4]),
        ("This week", [5]),
        ("Next week", [6, 7]),
        ("Later", [8]),
        ("No due date", [1]),
    ]


def test_on_a_saturday_tomorrow_is_sunday_and_this_week_is_empty() -> None:
    tasks = [task(1, SUNDAY), task(2, SUNDAY + timedelta(days=1))]
    assert headings(group_tasks(tasks, "due", SATURDAY)) == [
        ("Tomorrow", [1]),
        ("Next week", [2]),
    ]


def test_on_a_sunday_monday_is_tomorrow_and_the_week_after_is_next() -> None:
    tasks = [task(1, SUNDAY + timedelta(days=1)), task(2, SUNDAY + timedelta(days=2))]
    assert headings(group_tasks(tasks, "due", SUNDAY)) == [
        ("Tomorrow", [1]),
        ("Next week", [2]),
    ]


def test_by_urgency_in_words() -> None:
    d = WEDNESDAY
    tasks = [
        task(1, d, importance="high"),
        task(2, d),
        task(3, None, importance="high"),
        task(4),
    ]
    assert headings(group_tasks(tasks, "urgency", d)) == [
        ("Urgent and important", [1]),
        ("Urgent", [2]),
        ("Important", [3]),
        ("Neither", [4]),
    ]


def test_by_kind_and_by_repeats() -> None:
    tasks = [
        task(1, kind="call"),
        task(2, kind="physical", times_per_week=1.0),
        task(3, kind="errand", check_in=True, times_per_week=2.0),
        task(4, kind="text"),
    ]
    assert headings(group_tasks(tasks, "kind", WEDNESDAY)) == [
        ("Calls", [1]),
        ("Errands", [3]),
        ("Around the house", [2]),
        ("Messages and online", [4]),
    ]
    assert headings(group_tasks(tasks, "repeats", WEDNESDAY)) == [
        ("One-offs", [1, 4]),
        ("Repeating chores", [2]),
        ("Check-ins", [3]),
    ]


def test_none_is_one_list_and_a_bad_value_is_by_due_date() -> None:
    tasks = [task(1), task(2, WEDNESDAY)]
    assert headings(group_tasks(tasks, "none", WEDNESDAY)) == [("", [2, 1])]
    assert group_tasks([], "none", WEDNESDAY) == []
    assert grouping_of("colour") == "due" and grouping_of(None) == "due"
    assert headings(group_tasks(tasks, "colour", WEDNESDAY)) == [
        ("Today", [2]),
        ("No due date", [1]),
    ]
