"""F19c (Erin's idea #86): "for shared tasks, when one user snoozes the task, only snooze it
for that user (it should remain active for the user who did not snooze the task)". The clock
starts on Wednesday 21 October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from tests.scenarios.harness import Scenario
from themi import clock
from themi.ai.types import ToolResult
from themi.core.tasks import Task, TaskBoard

PACIFIC = ZoneInfo("America/Los_Angeles")
WED = date(2026, 10, 21)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def both(scenario: Scenario, title: str = "Bring bins in", at: str = "10:00") -> Task:
    """A task either of them can do, due today, and both nudged for it."""
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, title, "errand", 1, WED, assignee=erin, due_time=time.fromisoformat(at)
    )
    return await board(scenario).make_either(task.id)


async def until(scenario: Scenario, day: int, hour: int, minute: int = 0) -> None:
    """On to that moment in October, running what the scheduler would on the way."""
    clock.advance(datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC) - clock.now())
    await scenario.run_periodic("tasks.resurface")
    await scenario.app.outbox.flush()


def nudges(scenario: Scenario, name: str, title: str = "Bring bins in") -> list[str]:
    return [t for t in scenario.inbox(name) if title in t and t.endswith("or later?")]


def on_their_day(scenario: Scenario, name: str, title: str = "Bring bins in") -> bool:
    summary = scenario.app.services.day_summary
    assert summary is not None
    return title in (summary.text(scenario.member(name), WED) or "")


async def snooze(scenario: Scenario, name: str, task: Task, at: str, day: str = "") -> str:
    scenario.primary.queue_tool_call("snooze_task", {"task_id": task.id, "until": at, "day": day})
    scenario.primary.queue_text("Okay.")
    await scenario.say(name, "later")
    return tool_result(scenario)


def tool_result(scenario: Scenario) -> str:
    results: list[Any] = [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]
    return str(results[-1])


async def test_put_off_by_one_it_stays_with_the_other(scenario: Scenario) -> None:
    bins = await both(scenario)
    await until(scenario, 21, 10, 1)
    assert len(nudges(scenario, "Erin")) == len(nudges(scenario, "Husband")) == 1
    said = await snooze(scenario, "Erin", bins, "14:00")
    assert said == (
        "No rush on that one (Bring bins in). It waits for you until 2 pm today. It's still "
        "on Husband's list."
    )
    assert board(scenario).get(bins.id).status == "open"
    await until(scenario, 21, 13, 59)
    assert len(nudges(scenario, "Erin")) == 1
    await until(scenario, 21, 14, 1)
    assert len(nudges(scenario, "Erin")) == 2  # hers again, at her time
    assert len(nudges(scenario, "Husband")) == 1  # his was never touched


async def test_put_off_to_tomorrow_it_leaves_one_day_only(scenario: Scenario) -> None:
    bins = await both(scenario)
    await snooze(scenario, "Erin", bins, "09:00", day="2026-10-22")
    assert not on_their_day(scenario, "Erin")
    assert on_their_day(scenario, "Husband")


async def test_later_on_a_shared_nudge_is_the_tappers_alone(scenario: Scenario) -> None:
    await both(scenario)
    await until(scenario, 21, 10, 1)
    await scenario.tap("Erin", "Later")
    edit = scenario.edits("Erin")[-1]["text"]
    assert edit == (
        "No rush on that one (Bring bins in). It'll come back to you in a few hours. It's "
        "still on Husband's list."
    )


async def test_both_put_it_off_each_hears_at_their_own_time(scenario: Scenario) -> None:
    bins = await both(scenario)
    await until(scenario, 21, 10, 1)
    await snooze(scenario, "Erin", bins, "14:00")
    said = await snooze(scenario, "Husband", bins, "16:00")
    assert said == (  # nobody else has it now
        "No rush on that one (Bring bins in). It waits for you until 4 pm today."
    )
    await until(scenario, 21, 14, 1)
    assert (len(nudges(scenario, "Erin")), len(nudges(scenario, "Husband"))) == (2, 1)
    await until(scenario, 21, 16, 1)
    assert (len(nudges(scenario, "Erin")), len(nudges(scenario, "Husband"))) == (2, 2)


async def test_done_by_the_other_meanwhile_ends_the_put_off(scenario: Scenario) -> None:
    bins = await both(scenario)
    await until(scenario, 21, 10, 1)
    await snooze(scenario, "Erin", bins, "14:00")
    await board(scenario).complete(bins.id, scenario.member("Husband"))
    await until(scenario, 21, 14, 1)
    assert len(nudges(scenario, "Erin")) == 1
    count = scenario.app.db.scalar("SELECT COUNT(*) FROM task_snoozes")
    assert count == 0


async def test_a_new_day_moves_it_for_both_and_says_so(scenario: Scenario) -> None:
    bins = await both(scenario)
    await until(scenario, 21, 10, 1)
    await snooze(scenario, "Erin", bins, "14:00")
    scenario.primary.queue_tool_call(
        "reschedule_task",
        {"task_id": bins.id, "due_date": "2026-10-22", "due_time": "", "from_time": ""},
    )
    scenario.primary.queue_text("Moved.")
    await scenario.say("Erin", "Make it tomorrow instead")
    assert tool_result(scenario).endswith("That's for both of you.")
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM task_snoozes") == 0


async def test_a_task_of_ones_own_is_put_off_as_before(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Call the vet", "call", 1, WED, assignee=erin)
    said = await snooze(scenario, "Erin", task, "14:00")
    assert said == "No rush on that one (Call the vet). It waits until 2 pm today."
    assert board(scenario).get(task.id).status == "snoozed"
