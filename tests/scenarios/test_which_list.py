"""F17b, Erin's idea #68: "if an item could be added to more than one list, provide a prompt
with buttons for the most likely options plus 'not now'"."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from tests.scenarios.test_things_to_buy import groceries, on_it

ASK = {"item": "paper towels", "lists": ["Things to Buy", "grocery list"]}


async def ask(scenario: Scenario) -> list[str]:
    scenario.primary.queue_tool_call("ask_which_list", ASK)
    scenario.primary.queue_text("")
    return await scenario.say("Erin", "paper towels")


async def test_paper_towels_asks_which_list(scenario: Scenario) -> None:
    # #68: "paper towels" was staged for the grocery list; she meant Things to Buy.
    assert await ask(scenario) == ["Paper towels: which list?", "Done."]
    assert scenario.last_buttons("Erin") == ["Things to Buy", "Grocery list", "Not now"]
    await scenario.tap("Erin", "Things to Buy")
    assert on_it(scenario) == [("paper towels", False)]  # the tap was her answer: on at once
    assert groceries(scenario) == []
    assert scenario.edits("Erin")[-1]["text"] == "Added paper towels to Things to Buy."


async def test_the_grocery_list_from_the_card(scenario: Scenario) -> None:
    await ask(scenario)
    await scenario.tap("Erin", "Grocery list")
    assert scenario.edits("Erin")[-1]["text"] == "Added paper towels to the grocery list."
    assert groceries(scenario) == ["paper towels"]


async def test_not_now_adds_nothing(scenario: Scenario) -> None:
    await ask(scenario)
    await scenario.tap("Erin", "Not now")
    assert scenario.edits("Erin")[-1]["text"] == "Paper towels: left off the lists for now."
    assert on_it(scenario) == [] and groceries(scenario) == []


async def test_one_list_isnt_a_question(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "ask_which_list", {"item": "eggs", "lists": ["groceries", "grocery list"]}
    )
    scenario.primary.queue_text("Added.")
    await scenario.say("Erin", "eggs")
    assert "only one list" in str(scenario.primary.last_request.messages[-1])
    assert not any(t.endswith("which list?") for t in scenario.inbox("Erin"))
