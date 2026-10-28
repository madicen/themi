"""T1, Erin's idea #44: urgent and important. Waiting task nudges go urgent and important
first, then urgent only, then important only, then neither; an important task left a week
goes ahead of the urgent-only. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date, timedelta

from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.tasks import TaskBoard
from themi.localtime import to_utc_iso

WED = date(2026, 10, 21)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def nudged(scenario: Scenario) -> list[str]:
    titles = ("Water the plants", "Renew the passport", "Pay the water bill", "Buy stamps")
    return [t for t in scenario.inbox("Erin") for title in titles if title in t]


async def four_tasks(scenario: Scenario) -> None:
    """Asked about one at a time (F10): a first nudge goes, and the four wait their turn."""
    erin = scenario.member("Erin")
    new = board(scenario).create
    await new(erin, "Book the dentist", "errand", 1, WED, assignee=erin)
    await scenario.advance(minutes=30)
    assert any("Book the dentist" in t for t in scenario.inbox("Erin"))
    await new(erin, "Water the plants", "physical", 1, assignee=erin, importance="low")
    await new(erin, "Buy stamps", "errand", 1, WED, assignee=erin)  # urgent only
    await new(erin, "Renew the passport", "errand", 2, assignee=erin, importance="high")
    await new(erin, "Pay the water bill", "errand", 1, WED, assignee=erin, importance="high")


async def answer_each(scenario: Scenario) -> list[str]:
    await scenario.advance(hours=1)
    for _ in range(4):
        await scenario.tap("Erin", "Done")
        await scenario.advance(minutes=1)
    return [t.split(":", 1)[1].split(".")[0].strip() for t in nudged(scenario)]


async def test_urgent_and_important_go_first(scenario: Scenario) -> None:
    await four_tasks(scenario)
    assert await answer_each(scenario) == [
        "Pay the water bill", "Buy stamps", "Renew the passport", "Water the plants",
    ]  # fmt: skip


async def test_an_important_task_left_a_week_goes_before_the_urgent_only(
    scenario: Scenario,
) -> None:
    await four_tasks(scenario)
    week_ago = to_utc_iso(clock.now() - timedelta(days=8))
    scenario.app.db.execute(
        "UPDATE tasks SET created_at = ? WHERE title = 'Renew the passport'", (week_ago,)
    )
    assert await answer_each(scenario) == [
        "Pay the water bill", "Renew the passport", "Buy stamps", "Water the plants",
    ]  # fmt: skip


async def test_the_model_reads_it_in_words(scenario: Scenario) -> None:
    await four_tasks(scenario)
    items = [i.summary for i in board(scenario).open_items(scenario.member("Erin"))]
    assert any("urgent and important): Pay the water bill" in i for i in items)
    assert any("due 2026-10-21, urgent): Buy stamps" in i for i in items)
    assert any("(theirs, important): Renew the passport" in i for i in items)
    assert any("(theirs): Water the plants" in i for i in items)


async def test_urgent_with_no_date_is_due_today(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "Call the bank", "kind": "call", "effort": 2, "due_date": "",
            "due_time": "", "from_time": "", "assign_to": "me", "steps": [],
            "check_in": False, "importance": "normal",
        },
    )  # fmt: skip
    scenario.primary.queue_text("Added.")
    await scenario.say("Erin", "I need to call the bank, it's urgent")
    (task,) = board(scenario).open_for(scenario.member("Erin"))
    assert task.due_on == WED
