"""F32b (Michael's bug #171, Erin's #166): "my chores" is the chore chart, and a routine item
moves there in one call. The clock starts Wednesday 21 October 2026."""

from __future__ import annotations

from datetime import date
from typing import Any

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cozyla_routines import WED, at
from themi.ai.types import ToolResult
from themi.core import keys
from themi.standard.routines import Routines
from themi.standard.tasks import TaskBoard

ITEM = "Refill the vacuum's clean water"
REPLY_314 = {
    "title": "replace vacuum water",
    "part": "Evening",
    "repeat": "today",
    "position": "end",
    "task_id": 0,
}


def board(scenario: Scenario) -> TaskBoard:
    return scenario.app.services.get(keys.taskboard)


def routines(scenario: Scenario) -> Routines:
    return scenario.app.services.get(keys.routines)


def tool_results(scenario: Scenario) -> list[str]:
    return [
        str(block.content)
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


def cards(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query("SELECT * FROM pending_actions ORDER BY id")


async def evening_item(
    scenario: Scenario, fake_cozyla: FakeCozyla, title: str = ITEM, *, today_only: bool = True
) -> None:
    """The item on Michael's evening routine, in Themi and on the wall."""
    husband = scenario.member("Husband")
    await at(scenario, WED, 9, 30)
    evening = routines(scenario).find(husband, "evening")
    assert evening is not None
    routines(scenario).add_item(evening, title, only_on=WED if today_only else None)
    await at(scenario, WED, 9, 45)
    assert title in fake_cozyla.routine_order("m-husband", "Evening")


async def call(scenario: Scenario, said: str, tool: str, args: dict[str, Any]) -> list[str]:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Done.")
    return await scenario.say("Husband", said)


async def test_reply_314_a_chore_chart_ask_is_not_a_routine(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await evening_item(scenario, fake_cozyla)
    await call(
        scenario, "Move the vacuum water item to my chore chart please", "add_to_wall_routine",
        REPLY_314,
    )  # fmt: skip
    assert cards(scenario) == []
    (result,) = tool_results(scenario)
    assert "They asked for the chore chart, not a routine." in result
    assert "put_task_on_chore_chart (routine_item)" in result


async def test_bug_166_move_it_to_my_chores_is_not_a_routine(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Refill the vacuum water", "physical", 1, assignee=erin
    )
    await at(scenario, WED, 9, 30)
    await call(
        scenario, "I'll handle the vacuum's water. Can you move it to my chores?",
        "add_to_wall_routine", {**REPLY_314, "title": "Vacuum water", "task_id": task.id},
    )  # fmt: skip
    assert cards(scenario) == []
    assert "not a routine" in tool_results(scenario)[0]


async def test_bug_171_the_routine_item_moves_to_the_chart_in_one_call(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await evening_item(scenario, fake_cozyla)
    await call(
        scenario, "Move the vacuum water item to my chore chart please", "put_task_on_chore_chart",
        {"task_id": 0, "routine_item": "vacuum water"},
    )  # fmt: skip
    (result,) = tool_results(scenario)
    assert result.startswith(
        f"Moved {ITEM} from your evening routine to the chore chart, for today."
    )
    assert cards(scenario) == []  # no card, nothing snoozed
    husband = scenario.member("Husband")
    evening = routines(scenario).find(husband, "evening")
    assert evening is not None and routines(scenario).items(evening) == []
    (task,) = [t for t in board(scenario).open_for(husband) if t.title == ITEM]
    assert task.due_on == WED and not task.repeats
    assert scenario.app.services.get(keys.chart_queue).has(task.id)
    await at(scenario, WED, 10)
    assert ITEM not in fake_cozyla.routine_order("m-husband", "Evening")


async def test_a_repeating_item_becomes_a_repeating_chore_with_its_days(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await evening_item(scenario, fake_cozyla, "Cycle Dishwasher", today_only=False)
    await call(
        scenario, "Put cycle dishwasher on my chore chart instead", "put_task_on_chore_chart",
        {"task_id": 0, "routine_item": "Cycle Dishwasher"},
    )  # fmt: skip
    (result,) = tool_results(scenario)
    assert result.startswith(
        "Cycle Dishwasher is a chore now, every day, on your column of the chart."
    )
    husband = scenario.member("Husband")
    (task,) = [t for t in board(scenario).open_for(husband) if t.title == "Cycle Dishwasher"]
    assert task.repeats and task.repeat is not None


async def test_an_item_on_some_days_keeps_its_days(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    husband = scenario.member("Husband")
    await at(scenario, WED, 9, 30)
    evening = routines(scenario).find(husband, "evening")
    assert evening is not None
    routines(scenario).add_item(evening, "Take out the bins", days=(0, 3))
    await call(
        scenario, "bins to my chores please", "put_task_on_chore_chart",
        {"task_id": 0, "routine_item": "bins"},
    )  # fmt: skip
    (result,) = tool_results(scenario)
    assert "is a chore now, on Mondays and Thursdays" in result
    (task,) = [t for t in board(scenario).open_for(husband) if t.title == "Take out the bins"]
    assert task.repeat is not None
    assert board(scenario).next_dates(task)[0].date() == date(2026, 10, 22)  # Thursday


async def test_no_such_item_says_what_is_there(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    await evening_item(scenario, fake_cozyla)
    await call(
        scenario, "Move the gutters to my chores", "put_task_on_chore_chart",
        {"task_id": 0, "routine_item": "gutters"},
    )  # fmt: skip
    (result,) = tool_results(scenario)
    assert "No item like gutters" in result and ITEM in result


async def test_the_same_item_again_on_the_routine_is_refused(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await evening_item(scenario, fake_cozyla)
    await call(
        scenario, "Move the 'replace vacuum water' routine item to the chore list",
        "add_to_wall_routine", REPLY_314,
    )  # fmt: skip
    assert cards(scenario) == []
    assert f"{ITEM} is on the evening routine already." in tool_results(scenario)[0]


async def test_bug_22_adding_a_new_item_for_tonight_still_works(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await at(scenario, WED, 9, 30)
    await call(
        scenario, "Add replace vacuum water to my evening routine tonight", "add_to_wall_routine",
        REPLY_314,
    )  # fmt: skip
    assert [c["category"] for c in cards(scenario)] == ["wall_routine_add"]


async def test_a_second_identical_card_replaces_the_first(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await at(scenario, WED, 9, 30)
    said = "Can you add stretching each morning"  # not asked in so many words: a card
    args = {**REPLY_314, "title": "Stretch", "part": "Morning", "repeat": ""}
    await call(scenario, said, "add_to_wall_routine", args)
    await call(scenario, said, "add_to_wall_routine", args)
    first, second = cards(scenario)
    assert (first["status"], first["resolved_by"]) == ("declined", "system")
    assert second["status"] == "pending"
    assert any(e["text"].endswith("Replaced by the newer card.") for e in scenario.edits("Husband"))

    await scenario.tap("Husband", "Not now")  # snoozed: it would come back
    await call(scenario, said, "add_to_wall_routine", args)
    _, snoozed, third = cards(scenario)
    assert (snoozed["status"], snoozed["resolved_by"]) == ("declined", "system")
    assert third["status"] == "pending"

    other = {**args, "title": "Floss"}  # a different card stays
    await call(scenario, "Can you add flossing each morning", "add_to_wall_routine", other)
    assert cards(scenario)[2]["status"] == "pending"
