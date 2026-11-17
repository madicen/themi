"""GW5: a wrong weight fixed in chat: believed, changed at once with an undo, asked about
only when it can't be a weight. The family's guide on the Pi has "1 Tbsp Water: 5g", about
a third of the real 15 g. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fixtures.weights_guide import WEIGHTS_GUIDE
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi_home.gram_weights import GramWeights, key, regrammed

WATER = "1mL Water / 1 Tbsp Water: Weight in Grams 1g / 5g"


@pytest.fixture
def weights(scenario: Scenario) -> GramWeights:
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    guides.save(scenario.member("Erin"), "Weights of Common Ingredients", WEIGHTS_GUIDE,
                personal=False)  # fmt: skip
    found = scenario.app.services.maybe(GramWeights)
    assert found is not None
    return found


def guide_text(weights: GramWeights) -> str:
    guide = weights.guide()
    assert guide is not None
    return guide.text


async def say_water(scenario: Scenario, grams: float = 15) -> list[str]:
    scenario.primary.queue_tool_call(
        "correct_gram_weight",
        {"ingredient": "water", "amount": 1, "unit": "tbsp", "grams": grams},
    )
    return await scenario.say("Erin", f"A tablespoon of water is {grams:g} g, not 5")


def test_one_number_in_a_line_is_changed() -> None:
    assert regrammed(WATER, 1, 15) == "1mL Water / 1 Tbsp Water: Weight in Grams 1g / 15g"
    assert regrammed(WATER, 0, 1.25) == "1mL Water / 1 Tbsp Water: Weight in Grams 1.2g / 5g"
    assert regrammed("1 Cup Flour: Weight in Grams 120g", 0, 125) == (
        "1 Cup Flour: Weight in Grams 125g"
    )
    assert regrammed(WATER, 2, 15) is None


async def test_the_water_fix_and_its_undo(scenario: Scenario, weights: GramWeights) -> None:
    replies = await say_water(scenario)
    assert replies == [
        "Changed: 1 Tbsp water is 15 g now. That was in your guide as 5 g. Say undo to put it back."
    ]
    assert "1mL Water / 1 Tbsp Water: Weight in Grams 1g / 15g" in guide_text(weights)
    assert weights.book().grams("water", 1, "tbsp") == 15
    assert weights.book().grams("water", 1, "ml") == 1  # the other half of the line stays
    meta = weights.meta(key("water"))
    assert meta is not None and (meta["source"], meta["previous"]) == ("corrected", WATER)
    assert scenario.last_buttons("Erin") == ["Undo"]
    replies = await scenario.tap("Erin", "Undo")
    assert WATER in guide_text(weights)
    assert weights.meta(key("water")) is None  # the family's own line again


async def test_undo_said_in_words(scenario: Scenario, weights: GramWeights) -> None:
    await say_water(scenario)
    scenario.primary.queue_tool_call("undo_gram_weight", {"ingredient": "water"})
    replies = await scenario.say("Erin", "undo that")
    assert replies == [f"Put back: {WATER}"]
    assert weights.book().grams("water", 1, "tbsp") == 5


async def test_undo_is_for_a_day(scenario: Scenario, weights: GramWeights) -> None:
    await say_water(scenario)
    clock.freeze(clock.now() + timedelta(hours=25))
    said = await weights.undo(scenario.member("Erin"), "water")
    assert said.startswith("The change to water was more than a day ago")
    assert weights.book().grams("water", 1, "tbsp") == 15


async def test_a_weight_that_cant_be_right_is_asked_about(
    scenario: Scenario, weights: GramWeights
) -> None:
    replies = await say_water(scenario, 150)
    assert replies == ["150 g for 1 Tbsp seems a lot. Did you mean 15?"]
    assert scenario.last_buttons("Erin") == ["15 g", "150 g"]
    assert weights.book().grams("water", 1, "tbsp") == 5  # nothing changed yet
    await scenario.tap("Erin", "15 g")
    assert weights.book().grams("water", 1, "tbsp") == 15


async def test_a_correction_of_themis_own_weight_says_what_it_was(
    scenario: Scenario, weights: GramWeights
) -> None:
    erin = scenario.member("Erin")
    assert await weights.save(erin, "almond flour", 1, "cup", 98, "web", agrees=2)
    said, _ = await weights.correct(erin, "almond flour", 1, "cup", 96)
    assert said == "Changed: 1 cup almond flour is 96 g now (was 98 g). Say undo to put it back."
    assert "1 Cup Almond Flour: Weight in Grams 96g" in guide_text(weights)
    assert "98g" not in guide_text(weights)


async def test_a_new_weight_is_added(scenario: Scenario, weights: GramWeights) -> None:
    said, _ = await weights.correct(scenario.member("Erin"), "tahini", 2, "tbsp", 30)
    assert said == "Saved: 2 Tbsp tahini is 30 g. Say undo to put it back."
    assert "1 Tbsp Tahini: Weight in Grams 15g" in guide_text(weights)


async def test_an_alias(scenario: Scenario, weights: GramWeights) -> None:
    scenario.primary.queue_tool_call("same_ingredient", {"name": "plain flour", "same_as": "flour"})
    replies = await scenario.say("Erin", "Plain flour is just flour")
    assert replies == ["From now on, plain flour uses the weight for flour."]
    assert weights.book().grams("plain flour", 1, "cup") == 120


async def test_forget(scenario: Scenario, weights: GramWeights) -> None:
    scenario.primary.queue_tool_call("forget_gram_weight", {"ingredient": "garlic powder"})
    replies = await scenario.say("Erin", "Stop converting the garlic powder")
    assert replies == [
        "Taken out of your weights guide: 1 tsp garlic powder: Weight in Grams 3g. "
        "Recipes show it as written now. Say undo to put it back."  # F45e: undoable
    ]
    assert not weights.book().has("garlic powder")
    weights.ask("garlic powder", "tsp", None, None)
    assert weights.queued() == []  # not looked up again
    said, buttons = await weights.forget(scenario.member("Erin"), "water")
    assert buttons == []
    assert said.startswith("water shares a line with another weight")


async def test_a_correction_cancels_its_weighing_task(
    scenario: Scenario, weights: GramWeights
) -> None:
    import json

    scenario.app.db.execute(
        "INSERT INTO recipes (key, source, name, ingredients, created_at, updated_at) "
        "VALUES ('teff', 'doc', 'Teff Pancakes', ?, '2026-10-21', '2026-10-21')",
        (json.dumps([{"text": "1 cup teff flour", "group": ""}]),),
    )
    weights.record("teff flour", "wanted")
    await weights.look_up()
    task_id = scenario.app.db.scalar("SELECT id FROM tasks")
    await weights.correct(scenario.member("Erin"), "teff flour", 1, "cup", 92)
    assert scenario.app.db.scalar("SELECT status FROM tasks WHERE id = ?", (task_id,)) == (
        "cancelled"
    )
