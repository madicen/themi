"""F64e (Michael's idea #270, 2026-11-25): "need to be able to have multiple recipes going at
once and swap between them". The ricotta (step 9 of 15, the milk coming to temperature) ended
"switched" when he started the mozzarella. Now it waits, set aside, and comes back.
The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cooking import ALFREDO, card, card_buttons, items, to_the_steps
from themi.ai.types import ToolResult
from themi.core import keys
from themi_home.cooking import Cooking


@pytest.fixture
def cookbook(scenario: Scenario) -> Scenario:
    load(scenario.app.services)
    return scenario


def cooking(s: Scenario) -> Cooking:
    found = s.app.services.maybe(keys.cooking)
    assert found is not None
    return found


def names(s: Scenario) -> list[str]:
    c = cooking(s)
    return [c.name_of(x) for x in c.open_sessions(s.member("Erin"))]


async def pancakes_then_alfredo(s: Scenario) -> None:
    await to_the_steps(s)  # Pancakes, step 1
    s.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    s.primary.queue_structured(items(ALFREDO))
    await s.say("Erin", "While that's going, let's make the alfredo sauce")


def tool_results(s: Scenario) -> list[str]:
    return [
        b.content
        for m in s.primary.requests[-1].messages
        for b in m.content
        if isinstance(b, ToolResult)
    ]


async def test_a_second_recipe_sets_the_first_aside_and_a_tap_brings_it_back(
    cookbook: Scenario,
) -> None:
    await pancakes_then_alfredo(cookbook)
    assert names(cookbook) == ["Alfredo Sauce", "Pancakes"]  # both on the go, Alfredo in front
    row = cookbook.app.db.one("SELECT outcome FROM cooking_sessions WHERE recipe_id = "
                              "(SELECT id FROM recipes WHERE name = 'Pancakes')")  # fmt: skip
    assert row == {"outcome": None}  # not "switched"
    aside = [e["text"] for e in cookbook.edits("Erin") if e["text"].startswith("Set aside")]
    assert aside == ["Set aside: Pancakes, step 1."]
    front = cookbook.telegram.calls_in_order("sendMessage")[-1][1]["text"]
    assert front.startswith("Cooking Alfredo Sauce.") and "Also going: Pancakes, step 1" in front
    assert "Go to Pancakes" in cookbook.last_buttons("Erin")

    await cookbook.tap("Erin", "Go to Pancakes")
    assert names(cookbook) == ["Pancakes", "Alfredo Sauce"]
    back = cookbook.telegram.calls_in_order("sendMessage")[-1][1]["text"]
    assert back.startswith("Pancakes: step 1 of 5")  # where it was
    assert "Also going: Alfredo Sauce, getting ready" in back
    assert any(
        e["text"] == "Set aside: Alfredo Sauce, getting ready." for e in cookbook.edits("Erin")
    )
    await cookbook.tap("Erin", "Next")
    assert card(cookbook).startswith("Pancakes: step 2 of 5")


async def test_back_to_one_by_name_and_questions_know_the_others(cookbook: Scenario) -> None:
    await pancakes_then_alfredo(cookbook)
    cookbook.primary.queue_tool_call("switch_recipe", {"recipe": "the pancakes"})
    await cookbook.say("Erin", "back to the pancakes")
    assert names(cookbook)[0] == "Pancakes"
    cookbook.primary.queue_text("You're on step 1 of the pancakes.")
    await cookbook.say("Erin", "where am I with everything?")
    turn = cookbook.primary.requests[-1].messages[0].text
    assert "Cooking now with Themi: Pancakes (on step 1 of 5)" in turn
    assert "Also on the go, set aside" in turn and "Alfredo Sauce (getting ready)" in turn


async def test_finishing_one_brings_the_other_back(cookbook: Scenario) -> None:
    await pancakes_then_alfredo(cookbook)
    await cookbook.tap("Erin", "Go to Pancakes")
    for _ in range(4):
        await cookbook.tap("Erin", "Next")
    sent = await cookbook.tap("Erin", "All done")
    assert any(t.startswith("Back to Alfredo Sauce, getting ready.\nCooking Alfredo Sauce.")
               for t in sent)  # fmt: skip
    assert names(cookbook) == ["Alfredo Sauce"]


async def test_stopping_one_by_name_keeps_the_other(cookbook: Scenario) -> None:
    await pancakes_then_alfredo(cookbook)
    cookbook.primary.queue_tool_call("stop_cooking", {"recipe": "pancakes"})
    cookbook.primary.queue_text("Stopped the pancakes.")
    await cookbook.say("Erin", "stop the pancakes")
    assert names(cookbook) == ["Alfredo Sauce"]
    assert cooking(cookbook).current(cookbook.member("Erin")) is not None


async def test_a_timer_says_its_recipe_and_brings_it_forward(cookbook: Scenario) -> None:
    await to_the_steps(cookbook)
    for _ in range(4):
        await cookbook.tap("Erin", "Next")
    await cookbook.tap("Erin", "Timer 2 min (2-3)")
    cookbook.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    cookbook.primary.queue_structured(items(ALFREDO))
    await cookbook.say("Erin", "let's make the alfredo sauce too")
    cookbook.primary.queue_text("2 minutes on the pancakes.")
    await cookbook.say("Erin", "how long left?")
    await cookbook.advance(minutes=2)
    await cookbook.run_jobs()
    await cookbook.app.outbox.flush()
    assert cookbook.inbox("Erin")[-1] == "Time's up: 2 min for step 5 of Pancakes."
    assert cookbook.last_buttons("Erin") == ["Go to Pancakes"]
    from themi_home.cooking_screen import state

    (fired,) = state(cooking(cookbook), cookbook.member("Erin"))["timers"]  # F64f: the screen
    assert fired["fired"] and fired["go"]["name"] == "Pancakes"
    await cookbook.tap("Erin", "Go to Pancakes")
    assert names(cookbook)[0] == "Pancakes"


async def test_a_fourth_recipe_asks_which_to_stop(cookbook: Scenario) -> None:
    await pancakes_then_alfredo(cookbook)
    cookbook.primary.queue_tool_call("start_cooking", {"recipe": "bechamel sauce", "scale": ""})
    cookbook.primary.queue_structured(items(["onion", "cloves", "bay leaf", "soy milk"]))
    await cookbook.say("Erin", "and the bechamel")
    cookbook.primary.queue_tool_call("start_cooking", {"recipe": "simple parmesan", "scale": ""})
    cookbook.primary.queue_text("Which one should stop?")
    await cookbook.say("Erin", "and the parmesan")
    assert "Three recipes are on the go already" in tool_results(cookbook)[-1]
    assert len(names(cookbook)) == 3
    assert card_buttons(cookbook) is not None
