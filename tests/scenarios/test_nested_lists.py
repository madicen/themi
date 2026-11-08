"""F29g (bug #152, idea #153): list items with sub-items, at any depth. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.standard.lists import ListsPreferences


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def make(scenario: Scenario, name: str = "Service dog tasks") -> None:
    scenario.primary.queue_tool_call("create_list", {"name": name, "personal": False})
    scenario.primary.queue_text("Made.")
    await scenario.say("Erin", f"Make a list called {name}")


async def add(
    scenario: Scenario,
    said: str,
    items: list[str],
    under: str = "",
    name: str = "Service dog tasks",
) -> list[str]:
    scenario.primary.queue_tool_call("add_to_list", {"list": name, "items": items, "under": under})
    return await scenario.say("Erin", said)


async def show(scenario: Scenario, name: str = "Service dog tasks") -> list[str]:
    scenario.primary.queue_tool_call("show_lists", {"list": name})
    scenario.primary.queue_text("Here it is, with dashes for you.")
    return await scenario.say("Erin", f"What does the {name} list look like?")


def rows(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query("SELECT id, name, parent_id, done FROM list_items ORDER BY id")


async def test_bug_152_items_with_dashes_keep_their_shape(scenario: Scenario) -> None:
    await make(scenario)
    said = "Add to service dog tasks:\n- body doubling\n-- go upstairs\n-- go downstairs"
    await add(scenario, said, ["- body doubling", "-- go upstairs", "-- go downstairs"])
    found = rows(scenario)
    assert [(r["name"], r["parent_id"]) for r in found] == [
        ("body doubling", None),
        ("go upstairs", found[0]["id"]),
        ("go downstairs", found[0]["id"]),
    ]
    assert await show(scenario) == [
        "Service dog tasks\n- body doubling\n-- go upstairs\n-- go downstairs"
    ]


async def test_idea_153_a_sub_item_under_a_sub_item_is_a_third_level(scenario: Scenario) -> None:
    await make(scenario, "Pets")
    await add(scenario, "Add cats and dogs to pets", ["cats", "dogs"], name="Pets")
    await add(scenario, "Add food and toys under cats", ["food", "toys"], "cats", "Pets")
    await add(scenario, "Add a sub item under food: kibble", ["kibble"], "food", "Pets")
    assert await show(scenario, "Pets") == ["Pets\n- cats\n-- food\n--- kibble\n-- toys\n- dogs"]


async def test_an_unclear_under_asks_which(scenario: Scenario) -> None:
    await make(scenario, "Pets")
    await add(scenario, "Add cats and dogs to pets", ["cats", "dogs"], name="Pets")
    await add(scenario, "Add food under cats", ["food"], "cats", "Pets")
    await add(scenario, "Add food under dogs", ["food"], "dogs", "Pets")
    scenario.primary.queue_tool_call(
        "add_to_list", {"list": "Pets", "items": ["kibble"], "under": "food"}
    )
    scenario.primary.queue_text("Which food?")
    await scenario.say("Erin", "Add kibble under food")
    result = tool_result(scenario)
    assert "food (under cats)" in result and "food (under dogs)" in result


async def test_the_style_is_theirs(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await make(scenario, "Pets")
    await add(scenario, "Add cats to pets", ["cats"], name="Pets")
    await add(scenario, "Add food under cats", ["food"], "cats", "Pets")
    scenario.app.store.save_preferences(erin, erin.id, ListsPreferences, list_style="numbers")
    assert await show(scenario, "Pets") == ["Pets\n1. cats\n1.1. food"]
    scenario.app.store.save_preferences(erin, erin.id, ListsPreferences, list_style="bullets")
    assert await show(scenario, "Pets") == ["Pets\n• cats\n  • food"]


async def test_ticking_or_removing_a_parent_does_its_sub_items(scenario: Scenario) -> None:
    await make(scenario, "Pets")
    await add(scenario, "Add cats and dogs to pets", ["cats", "dogs"], name="Pets")
    await add(scenario, "Add food and toys under cats", ["food", "toys"], "cats", "Pets")
    scenario.primary.queue_tool_call(
        "tick_list_items", {"list": "Pets", "items": ["cats"], "done": True}
    )
    scenario.primary.queue_text("Ticked.")
    await scenario.say("Erin", "Tick off cats")
    assert "and its 2 sub-items" in tool_result(scenario)
    assert [r["done"] for r in rows(scenario)] == [1, 0, 1, 1]
    scenario.primary.queue_tool_call(
        "remove_from_list", {"list": "Pets", "items": ["cats"], "ticked": False}
    )
    scenario.primary.queue_text("Gone.")
    await scenario.say("Erin", "Take cats off")
    assert [r["name"] for r in rows(scenario)] == ["dogs"]


async def test_an_item_moves_under_another(scenario: Scenario) -> None:
    await make(scenario)
    await add(scenario, "Add body doubling and go upstairs", ["body doubling", "go upstairs"])
    scenario.primary.queue_tool_call(
        "move_list_item",
        {"list": "Service dog tasks", "item": "go upstairs", "under": "body doubling"},
    )
    scenario.primary.queue_text("Moved.")
    await scenario.say("Erin", "Put go upstairs under body doubling")
    assert await show(scenario) == ["Service dog tasks\n- body doubling\n-- go upstairs"]
