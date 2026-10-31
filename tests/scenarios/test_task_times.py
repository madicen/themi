"""F15a: changing a task's day and time (bug #54) and one task, not two (bug #56). The clock
starts on Wednesday 21 October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tests.scenarios.harness import Scenario
from themi import clock
from themi.ai.types import ToolResult
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

PACIFIC = ZoneInfo("America/Los_Angeles")


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def call(scenario: Scenario, name: str, said: str, tool: str, args: dict[str, Any]) -> str:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Okay.")
    await scenario.say(name, said)
    return tool_result(scenario)


async def until(scenario: Scenario, day: int, hour: int, minute: int = 0) -> None:
    """On to that moment in October, running what the scheduler would on the way."""
    clock.advance(datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC) - clock.now())
    await scenario.run_periodic("tasks.resurface")
    await scenario.app.outbox.flush()


def nudges(scenario: Scenario, title: str) -> list[str]:
    return [t for t in scenario.inbox("Erin") if t.startswith("Due ") and title in t]


async def reminder(scenario: Scenario, title: str, due: date, at: str) -> Task:
    from datetime import time

    erin = scenario.member("Erin")
    return await board(scenario).create(
        erin, title, "errand", 1, due, assignee=erin, due_time=time.fromisoformat(at)
    )


def reschedule(task: Task, day: str = "", at: str = "", start: str = "") -> dict[str, Any]:
    return {"task_id": task.id, "due_date": day, "due_time": at, "from_time": start}


async def test_reminders_moved_to_tomorrow_wait_for_tomorrow(scenario: Scenario) -> None:
    """Bug #54: "extra reminders for the tutoring at 2pm and 3pm" (the session is tomorrow)
    were snoozed to 2 and 3 today; moved to tomorrow, the snoozes stayed, so they would
    still have come today."""
    tutoring = await reminder(scenario, "Tutoring reminder", date(2026, 10, 21), "14:00")
    await call(
        scenario,
        "Erin",
        "remind me at 2",
        "snooze_task",
        {"task_id": tutoring.id, "until": "14:00", "day": ""},
    )
    result = await call(
        scenario, "Erin", "They should have been for 2 tomorrow", "reschedule_task",
        reschedule(tutoring, "2026-10-22", "14:00"),
    )  # fmt: skip
    assert result == "Tutoring reminder is now due Thu 22 Oct, 2 pm."
    assert board(scenario).get(tutoring.id).status == "open"
    await until(scenario, 21, 14, 1)
    assert nudges(scenario, "Tutoring reminder") == []
    await until(scenario, 22, 13, 59)
    assert nudges(scenario, "Tutoring reminder") == []
    await until(scenario, 22, 14, 1)
    assert nudges(scenario, "Tutoring reminder") == [
        "Due today: Tutoring reminder. Done already, or later?"
    ]


async def test_earlier_on_the_same_day(scenario: Scenario) -> None:
    """Bug #54: "on Friday afternoon, remind me to drink green tea", then "earlier... 5pm is
    too late" was moved to earlier *today*."""
    tea = await reminder(scenario, "Drink green tea", date(2026, 10, 23), "17:00")
    result = await call(
        scenario, "Erin", "I want it Friday afternoon but 5pm is too late", "reschedule_task",
        reschedule(tea, at="13:00"),
    )  # fmt: skip
    assert result == "Drink green tea is now due Fri 23 Oct, 1 pm."
    await until(scenario, 23, 12, 59)
    assert nudges(scenario, "green tea") == []
    await until(scenario, 23, 13, 1)
    assert len(nudges(scenario, "green tea")) == 1


async def test_put_off_to_another_day_says_which(scenario: Scenario) -> None:
    tea = await reminder(scenario, "Drink green tea", date(2026, 10, 21), "10:00")
    result = await call(
        scenario,
        "Erin",
        "tomorrow at 8",
        "snooze_task",
        {"task_id": tea.id, "until": "08:00", "day": ""},
    )
    assert result == "No rush on that one (Drink green tea). It waits until Thu 22 Oct, 8 am."


async def test_put_off_to_tomorrow_afternoon_waits_for_tomorrow(scenario: Scenario) -> None:
    """Bugs #104, #106: at 1:37 pm, "snooze the green tea to tomorrow afternoon" ran
    snooze_task with until 14:00 (it took only a time), so the tea came back at 2 pm that
    day, the reply said "2 pm tomorrow", and the day's summary still had it."""
    tea = await reminder(scenario, "Drink green tea", date(2026, 10, 21), "13:00")
    await until(scenario, 21, 13, 37)
    asked = len(nudges(scenario, "green tea"))
    result = await call(
        scenario, "Erin", "Snooze the green tea to tomorrow afternoon", "snooze_task",
        {"task_id": tea.id, "until": "14:00", "day": "2026-10-22"},
    )  # fmt: skip
    assert result == "No rush on that one (Drink green tea). It waits until Thu 22 Oct, 2 pm."
    summary = scenario.app.services.day_summary
    assert summary is not None
    assert "green tea" not in (summary.text(scenario.member("Erin"), date(2026, 10, 21)) or "")
    await until(scenario, 21, 14, 1)
    await until(scenario, 22, 13, 59)
    assert len(nudges(scenario, "green tea")) == asked
    await until(scenario, 22, 14, 1)
    assert scenario.inbox("Erin")[-1] == (
        "Was due yesterday: Drink green tea. Done already, or later?"
    )


async def test_put_off_until_later_today_says_today(scenario: Scenario) -> None:
    """Bug #104: the result said "until 2 pm", and the reply made it "2 pm tomorrow"."""
    tea = await reminder(scenario, "Drink green tea", date(2026, 10, 21), "10:00")
    result = await call(
        scenario, "Erin", "at 2", "snooze_task", {"task_id": tea.id, "until": "14:00", "day": ""}
    )
    assert result == "No rush on that one (Drink green tea). It waits until 2 pm today."


async def test_put_off_to_a_day_without_a_time_is_its_morning(scenario: Scenario) -> None:
    tea = await reminder(scenario, "Drink green tea", date(2026, 10, 21), "10:00")
    result = await call(
        scenario, "Erin", "Friday", "snooze_task",
        {"task_id": tea.id, "until": "", "day": "2026-10-23"},
    )  # fmt: skip
    assert result == "No rush on that one (Drink green tea). It waits until Fri 23 Oct, 9 am."


async def test_a_repeating_chores_time_is_every_rounds(scenario: Scenario) -> None:
    """Bug #56: "Mimi pill should always check at 9pm, and never before" made a second,
    one-off "Mimi pill" at 9 pm; the every-other-day one still nudged at 9 am."""
    erin = scenario.member("Erin")
    pill = await board(scenario).create(
        erin, "Mimi pill - 1 tab", "physical", 2, assignee=erin, nudge=False
    )
    today = date(2026, 10, 21)
    await board(scenario).set_schedule(
        pill.id, erin, repeat=parse("every 2 days until 30 Oct", today)
    )

    refused = await call(
        scenario, "Erin", "Mimi pill should always check at 9pm", "create_task",
        {
            "title": "Mimi pill", "kind": "physical", "effort": 1, "due_date": "2026-10-21",
            "due_time": "21:00", "from_time": "", "assign_to": "me", "steps": [],
            "check_in": False, "importance": "normal",
        },
    )  # fmt: skip
    assert refused.startswith(f"Not created: task {pill.id} (Mimi pill - 1 tab) is already open.")
    assert [t.title for t in board(scenario).open_for(erin)] == ["Mimi pill - 1 tab"]

    result = await call(
        scenario, "Erin", "Mimi pill should always check at 9pm", "reschedule_task",
        reschedule(pill, at="21:00"),
    )  # fmt: skip
    assert result == "Mimi pill - 1 tab is now due Wed 21 Oct, 9 pm."
    moved = board(scenario).get(pill.id)
    assert moved.repeat is not None and moved.repeat.at is not None
    assert (moved.repeat.at.hour, moved.repeat.until, moved.due_time) == (
        21,
        date(2026, 10, 30),
        None,
    )
    before = len(nudges(scenario, "Mimi pill"))  # today's, at 9 am, before the change
    await until(scenario, 21, 20, 59)
    assert len(nudges(scenario, "Mimi pill")) == before
    await until(scenario, 21, 21, 1)
    assert len(nudges(scenario, "Mimi pill")) == before + 1
