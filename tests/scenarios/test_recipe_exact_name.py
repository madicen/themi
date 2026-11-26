"""F42c (Michael's bugs #205 and #206, replies 440-443): a recipe named exactly is the one,
even when its name is the start of another's ("Chocolate Chip Cookies" and "Chocolate Chip
Cookies for 2"), and a turn where nothing was done never ends "Done."."""

from __future__ import annotations

from tests.fixtures.cookbook import cookbook, load, recipe
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys

COOKIES = recipe(
    "Chocolate Chip Cookies",
    ["2 Cups flour", "1 Cup chocolate chips", "½ Cup maple syrup"],
    ["Mix everything.", "Bake for 10 minutes."],
)
FOR_TWO = recipe(
    "Chocolate Chip Cookies for 2",
    ["3 Tbsp flour", "1 Tbsp chocolate chips", "1 Tbsp maple syrup"],
    ["Mix everything.", "Bake for 8 minutes."],
)


def cookies(scenario: Scenario) -> None:
    blocks = cookbook()
    at = blocks.index(("H1", "Sides"))
    load(scenario.app.services, [*blocks[:at], *COOKIES, *FOR_TWO, *blocks[at:]])


def results(scenario: Scenario) -> list[str]:
    return [
        block.content
        for message in scenario.primary.requests[-1].messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


async def card(scenario: Scenario, name: str) -> str:
    scenario.primary.queue_tool_call("recipe_card", {"name": name})
    scenario.primary.queue_text("Here it is.")
    await scenario.say("Husband", f"Show me a recipe card for {name}")
    return results(scenario)[-1]


async def test_the_shorter_name_said_exactly_is_that_recipe(scenario: Scenario) -> None:
    cookies(scenario)
    assert (await card(scenario, "chocolate chip cookies")).startswith(
        "Sent Chocolate Chip Cookies as a picture."
    )
    assert len(scenario.pictures("Husband")) == 1


async def test_the_longer_name_said_exactly_is_that_recipe(scenario: Scenario) -> None:
    cookies(scenario)  # reply 441's exact argument
    assert (await card(scenario, "Chocolate Chip Cookies for 2")).startswith(
        "Sent Chocolate Chip Cookies for 2 as a picture."
    )


async def test_part_of_a_name_still_asks_which(scenario: Scenario) -> None:
    cookies(scenario)
    asked = await card(scenario, "chocolate chip")
    assert asked.startswith("Several recipes match")
    assert "1. Chocolate Chip Cookies" in asked and "2. Chocolate Chip Cookies for 2" in asked
    assert "call again with that name" in asked


async def test_find_recipe_sends_the_one_named_exactly(scenario: Scenario) -> None:
    cookies(scenario)
    scenario.primary.queue_tool_call(
        "find_recipe", {"query": "Chocolate Chip Cookies", "section": "", "book": ""}
    )
    scenario.primary.queue_text("There you go.")
    await scenario.say("Husband", "Show me the chocolate chip cookies recipe")
    shown = [t for t in scenario.inbox("Husband") if t.startswith("Chocolate Chip Cookies")]
    assert shown and not shown[-1].startswith("Chocolate Chip Cookies for 2")
    found = scenario.app.services.get(keys.recipes).find("chocolate chip cookies")
    assert found[0].exact and found[0].recipe.name == "Chocolate Chip Cookies"


async def test_nothing_done_never_ends_done(scenario: Scenario) -> None:
    cookies(scenario)
    scenario.primary.queue_tool_call("recipe_card", {"name": "chocolate chip"})
    scenario.primary.queue_text("Chocolate Chip Cookies or Chocolate Chip Cookies for 2?")
    await scenario.say("Husband", "Show me a recipe card for the chocolate chip ones")
    # Reply 443: the model said its last message again, which F41c drops; "Done." was left.
    scenario.primary.queue_tool_call("recipe_card", {"name": "chocolate chip"})
    scenario.primary.queue_text("Chocolate Chip Cookies or Chocolate Chip Cookies for 2?")
    replies = await scenario.say("Husband", "Yes, show me a recipe card")
    assert "Done." not in replies
    assert replies == ["Chocolate Chip Cookies or Chocolate Chip Cookies for 2?"]


async def test_a_misspelt_recipe_is_asked_about_and_yes_shows_it(scenario: Scenario) -> None:
    """F64d (seen in #270's conversation): "Let's make the bechemel" said there was no such
    recipe; Bechamel Sauce was there."""
    load(scenario.app.services)
    scenario.primary.queue_tool_call("find_recipe", {"query": "bechemel", "section": "", "book": ""})
    scenario.primary.queue_text("Is that the one?")
    await scenario.say("Husband", "Let's make the bechemel")
    assert "Did you mean Bechamel Sauce?" in scenario.inbox("Husband")
    assert scenario.last_buttons("Husband") == ["Bechamel Sauce"]
    shown = await scenario.tap("Husband", "Bechamel Sauce")
    assert any(t.startswith("Bechamel Sauce") for t in shown)


async def test_a_misspelt_recipe_card_asks_first(scenario: Scenario) -> None:
    load(scenario.app.services)
    asked = await card(scenario, "bechemel")
    assert "nearest spelling: Bechamel Sauce" in asked and "Ask whether" in asked
    assert scenario.pictures("Husband") == []
