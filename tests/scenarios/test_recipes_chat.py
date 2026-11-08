"""RC1b: finding a recipe in the family cookbook and showing it in chat. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import COOKBOOK_ID, load
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.standard.conversation_mode import is_request


@pytest.fixture
def cookbook(scenario: Scenario) -> Scenario:
    load(scenario.app.services)
    return scenario


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def test_erin_asks_for_the_ranch_dressing(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call("find_recipe", {"query": "ranch dressing", "section": ""})
    replies = await cookbook.say("Erin", "Can you pull up our ranch dressing?")
    (card,) = replies  # the recipe is the whole answer
    assert card.startswith("Silken Tofu Ranch Dressing (Ingredients · Sauces, Dressings & Dips)")
    assert "> - 1 package silken tofu (12.3oz) firm" in card
    assert "> 1. Blend ingredients together until smooth" in card
    assert f"https://docs.google.com/document/d/{COOKBOOK_ID}/edit#heading=h." in card
    assert cookbook.primary.pending() == 0  # no second model round


async def test_two_matches_come_as_buttons(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "find_recipe", {"query": "chocolate peanut butter bars", "section": ""}
    )
    replies = await cookbook.say("Husband", "What's the recipe for the peanut butter bars?")
    assert replies == ["From the cookbook:"]
    assert cookbook.last_buttons("Husband") == ["Chocolate Peanut Butter Bars"] * 2
    shown = await cookbook.tap("Husband", "Chocolate Peanut Butter Bars")
    assert shown[0].startswith("Chocolate Peanut Butter Bars (Desserts)")
    assert "> - 1 Cup peanut butter" in shown[0]


async def test_a_chart_row_answers_a_question(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call("find_recipe", {"query": "roast broccoli", "section": ""})
    cookbook.primary.queue_text("From your cookbook: 400°F for 20 minutes, cut into florets.")
    replies = await cookbook.say("Erin", "How long do I roast broccoli?")
    result = tool_result(cookbook)
    assert '<data source="cookbook Roasted Vegetables">' in result
    assert "Broccoli: Temp 400, Time 20 min, Prep Cut to florets" in result
    assert replies == ["From your cookbook: 400°F for 20 minutes, cut into florets."]


async def test_nothing_in_the_cookbook_isnt_made_up(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call("find_recipe", {"query": "beef wellington", "section": ""})
    cookbook.primary.queue_text("There's no beef wellington in the cookbook.")
    await cookbook.say("Erin", "Find the beef wellington recipe")
    assert "never make up a recipe" in tool_result(cookbook)


async def test_no_cookbook_yet_says_how(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("find_recipe", {"query": "pancakes", "section": ""})
    scenario.primary.queue_text("There's no cookbook yet.")
    await scenario.say("Erin", "Pull up the pancakes recipe")
    assert "Accounts page" in tool_result(scenario)


async def test_a_section_with_no_other_words_lists_it(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call("find_recipe", {"query": "a dessert", "section": ""})
    await cookbook.say("Erin", "What desserts do we have?")
    assert cookbook.last_buttons("Erin") == [
        "Ube Gelato", "Chocolate Peanut Butter Bars", "Chocolate Peanut Butter Bars",
    ]  # fmt: skip


async def test_the_context_says_theres_a_cookbook(cookbook: Scenario) -> None:
    cookbook.primary.queue_text("Hello!")
    await cookbook.say("Erin", "Hi")
    turn = cookbook.primary.requests[0].messages[0].text
    assert "The family cookbook has 16 recipes and charts (find_recipe)." in turn


def test_recipe_words_are_requests_in_conversation_mode() -> None:
    assert is_request("Cook the pancakes with me")
    assert is_request("What's the recipe for chana masala")
    assert is_request("Is the lasagna in our cookbook?")
    assert not is_request("I'm cooking tonight and feeling good about it")
