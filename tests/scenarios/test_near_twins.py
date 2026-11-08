"""F24a: Erin's bug #132 (2026-11-03): "Urgent for Michael: cat feeders need to be refilled"
made a new "Refill cat feeders" for him, though he had "Refill auto feeders" every Thursday.
Her context lists only her own tasks, so it's create_task that has to find his. The clock
starts on Wednesday 21 October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from datetime import date
from typing import Any

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys
from themi.core.repeat import parse
from themi.core.tasks import TaskBoard
from themi.core.wording import near_twin

SAID = "Urgent for Husband: cat feeders need to be refilled"


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


def made(title: str, assign_to: str = "Husband", due: str = "2026-10-21") -> dict[str, Any]:
    return {
        "title": title, "kind": "physical", "effort": 1, "due_date": due, "due_time": "",
        "from_time": "", "assign_to": assign_to, "steps": [], "check_in": False,
        "importance": "high",
    }  # fmt: skip


def results(scenario: Scenario) -> list[str]:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


async def feeders(scenario: Scenario) -> tuple[int, int]:
    husband = scenario.member("Husband")
    today = date(2026, 10, 21)
    auto = await board(scenario).create(
        husband, "Refill auto feeders", "physical", 2, assignee=husband, nudge=False
    )
    await board(scenario).set_schedule(auto.id, husband, repeat=parse("every Thursday", today))
    pet = await board(scenario).create(
        husband, "Refill pet feeders", "physical", 2, date(2026, 11, 19), assignee=husband,
        nudge=False,
    )  # fmt: skip
    return auto.id, pet.id


def test_near_twins_share_most_of_their_words() -> None:
    assert near_twin("Refill cat feeders", "Refill auto feeders")
    assert near_twin("Refill the bird feeder", "Refill auto feeders")
    assert not near_twin("Clean the kitchen", "Clean the upstairs bathroom")  # one word
    assert not near_twin("Take out the trash", "Take out the recycling bins")  # two of four
    assert not near_twin("Feeders", "Refill auto feeders")


async def test_asked_for_again_the_open_task_is_raised(scenario: Scenario) -> None:
    auto, pet = await feeders(scenario)
    husband = scenario.member("Husband")
    scenario.primary.queue_tool_call("create_task", made("Refill cat feeders"))
    scenario.primary.queue_tool_call(
        "reschedule_task",
        {"task_id": auto, "due_date": "2026-10-21", "due_time": "", "from_time": ""},
    )
    scenario.primary.queue_tool_call("set_task_importance", {"task_id": auto, "importance": "high"})
    scenario.primary.queue_text("Husband's Refill auto feeders is due today, and it matters.")
    await scenario.say("Erin", SAID)
    refused = results(scenario)[0]
    assert refused.startswith("Not created: it may be one that's already open: ")
    assert (
        f"task {auto} (Refill auto feeders, Husband's, every Thursday, due Thu 22 Oct)" in refused
    )
    assert f"task {pet} (Refill pet feeders, Husband's, due Thu 19 Nov)" in refused
    assert "reschedule_task" in refused and "set_task_importance" in refused
    titles = [t.title for t in board(scenario).open_for(husband)]
    assert sorted(titles) == ["Refill auto feeders", "Refill pet feeders"]
    raised = board(scenario).get(auto)
    assert (raised.due_on, raised.importance) == (date(2026, 10, 21), "high")
    assert raised.repeat is not None and raised.repeat.weekdays == (3,)  # still Thursdays
    await scenario.app.outbox.flush()
    assert len([t for t in scenario.inbox("Husband") if "Refill auto feeders" in t]) == 1


async def test_a_different_job_is_made_when_asked_again(scenario: Scenario) -> None:
    await feeders(scenario)
    husband = scenario.member("Husband")
    scenario.primary.queue_tool_call("create_task", made("Refill the bird feeder"))
    scenario.primary.queue_tool_call("create_task", made("Refill the bird feeder"))
    scenario.primary.queue_text("Added.")
    await scenario.say("Erin", "Husband needs to refill the bird feeder in the garden")
    first, second = results(scenario)
    assert first.startswith("Not created: it may be one that's already open: ")
    assert second.startswith("Task ") and " created " in second
    assert "Refill the bird feeder" in [t.title for t in board(scenario).open_for(husband)]


async def test_a_task_with_one_word_in_common_is_made(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await board(scenario).create(erin, "Clean the upstairs bathroom", "physical", 3, assignee=erin)
    scenario.primary.queue_tool_call("create_task", made("Clean the kitchen", "me"))
    scenario.primary.queue_text("Added.")
    await scenario.say("Erin", "I need to clean the kitchen today")
    assert results(scenario)[0].startswith("Task ")
