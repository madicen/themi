"""C2c: reminders by importance; the end of the day; more specific when overdue.

The clock starts on Wednesday 21 October 2026, 09:00. Erin's quiet hours start at 21:30, so
her end-of-day message comes from 19:30; her husband's start at 23:00 (from 21:00)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

WED = date(2026, 10, 21)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def task(
    scenario: Scenario, title: str, due: date | None, importance: str = "normal", **kw: Any
) -> Task:
    erin = scenario.member("Erin")
    made = await board(scenario).create(erin, title, "errand", 2, due, assignee=erin, **kw)
    scenario.app.db.execute("UPDATE tasks SET importance = ? WHERE id = ?", (importance, made.id))
    return board(scenario).get(made.id)


def texts(scenario: Scenario, start: str) -> list[str]:
    """Messages (sent or waiting) that begin with `start`."""
    rows = scenario.app.db.query("SELECT text FROM outbox ORDER BY id")
    return [r["text"] for r in rows if r["text"].startswith(start)]


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> None:
    """Move the clock to that local time and run the reminder jobs, as the scheduler would."""
    target = clock.now().replace(
        year=day.year, month=day.month, day=day.day, hour=hour, minute=minute
    )
    clock.advance(target - clock.now())
    await scenario.run_periodic("tasks.day_end")
    await scenario.run_periodic("tasks.overdue")


async def test_the_end_of_the_day_lists_whats_still_open(scenario: Scenario) -> None:
    await task(scenario, "Book the dentist", WED)
    await task(scenario, "Water the plants", WED, importance="low")  # left out
    await task(scenario, "Pay the water bill", WED + timedelta(days=1))  # not today's
    done = await task(scenario, "Call the vet", WED)
    await board(scenario).complete(done.id, scenario.member("Erin"))

    await at(scenario, WED, 19, 0)
    assert texts(scenario, "Still open today") == []
    await at(scenario, WED, 19, 31)
    assert texts(scenario, "Still open today") == [
        "Still open today: Book the dentist. Done any of them already? Tomorrow's fine too."
    ]
    await at(scenario, WED, 20, 0)
    assert len(texts(scenario, "Still open today")) == 1  # once a day
    assert not any(  # nothing of his was open
        r["member_id"] == scenario.member("Husband").id
        for r in scenario.app.db.query("SELECT member_id FROM outbox WHERE text LIKE 'Still%'")
    )


async def test_overdue_reminders_get_more_specific(scenario: Scenario) -> None:
    await task(
        scenario,
        "Clean the kitchen",
        WED,
        steps=["(Optional/Bonus) Spray the counters", "Do the dishes", "Wipe the table"],
    )
    await at(scenario, WED + timedelta(days=1), 10)  # Thursday
    (first,) = texts(scenario, "Overdue: Clean the kitchen")
    assert first.startswith("Overdue: Clean the kitchen, due yesterday.\n\n")
    await at(scenario, WED + timedelta(days=2), 10)  # Friday: normal is every other day
    assert len(texts(scenario, "Overdue: Clean the kitchen")) == 1
    await at(scenario, WED + timedelta(days=3), 10)  # Saturday
    second = texts(scenario, "Overdue: Clean the kitchen")[-1]
    assert second.startswith(
        "Overdue: Clean the kitchen, due Wednesday. The smallest version: Do the dishes.\n\n"
    )
    await at(scenario, WED + timedelta(days=5), 10)  # Monday
    third = texts(scenario, "Overdue: Clean the kitchen")[-1]
    assert "The smallest version: Do the dishes." in third
    assert "looks lighter, if that helps" in third or "good moment, if that helps" in third
    assert "I can move it, or ask Husband to take it." in third
    assert all("Done already, or later?" in t for t in (first, second, third))


async def test_importance_sets_the_rhythm(scenario: Scenario) -> None:
    await task(scenario, "Give Mimi her pill", WED, importance="high")
    photos = await task(scenario, "Sort the photos", WED, importance="low")
    for days in range(1, 9):
        await at(scenario, WED + timedelta(days=days), 10)
    assert len(texts(scenario, "Overdue: Give Mimi her pill")) == 8  # every day
    raised = scenario.app.db.scalar(
        "SELECT overdue_reminders FROM tasks WHERE id = ?", (photos.id,)
    )
    assert raised == 2  # weekly
    # Both waited behind Mimi's, so the second took the first's place (bug #49).
    assert len(texts(scenario, "Overdue: Sort the photos")) == 1


async def test_chores_that_roll_on_arent_raised_as_overdue(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    bins = await board(scenario).create(erin, "Take out the bins", "physical", 1, assignee=erin)
    await board(scenario).set_schedule(bins.id, erin, repeat=parse("every Wednesday", WED))
    await at(scenario, WED + timedelta(days=1), 10)
    assert texts(scenario, "Overdue: Take out the bins") == []


async def test_saying_it_matters_sets_the_importance(scenario: Scenario) -> None:
    pill = await task(scenario, "Give Mimi her pill", WED)
    scenario.primary.queue_tool_call(
        "set_task_importance", {"task_id": pill.id, "importance": "high"}
    )
    scenario.primary.queue_text("Got it, that one comes first.")
    await scenario.say("Erin", "Mimi's pill really matters")
    assert board(scenario).get(pill.id).importance == "high"
