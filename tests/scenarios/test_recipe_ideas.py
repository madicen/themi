"""RC7: cookbook recipes in meal ideas. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from themi.core.recipe_ideas import covers

CHANA_PANTRY = [
    "dried chickpeas", "oil", "onion", "bay leaf", "garlic", "tomatoes", "coriander powder",
    "garam masala",
]  # fmt: skip
MEALS = {
    "options": [
        {"title": "Chickpea toast", "uses": ["chickpeas"], "steps": "Mash, toast.", "minutes": 10},
        {"title": "Tomato rice", "uses": ["tomatoes"], "steps": "Stir, heat.", "minutes": 15},
    ]
}


@pytest.fixture
def stocked(scenario: Scenario) -> Scenario:
    load(scenario.app.services)
    pantry = scenario.app.services.pantry
    assert pantry is not None
    for name in CHANA_PANTRY:
        pantry.set_status(name, "plenty", source="said")
    return scenario


def ideas(scenario: Scenario) -> list[str]:
    found = scenario.app.services.recipe_ideas
    assert found is not None
    return [i.recipe.name for i in found.pick(scenario.member("Erin"), limit=5)]


def test_names_cover_each_other() -> None:
    assert covers("chickpeas", "dried chickpeas") and covers("tomato", "tomatoes")
    assert covers("rice", "rice flour")  # by words, "rice" is in "rice flour"
    assert not covers("milk", "oat flour")


async def test_meal_ideas_offer_the_chana_masala(stocked: Scenario) -> None:
    stocked.primary.queue_tool_call("suggest_meals", {"request": ""})
    stocked.primary.queue_structured(MEALS)
    stocked.primary.queue_text("A few ideas above.")
    await stocked.say("Erin", "What should I make for dinner?")
    offer = next(t for t in stocked.inbox("Erin") if t.startswith("Two easy options"))
    assert offer.splitlines()[-1] == (
        "Or from the cookbook: Chana Masala (you'd need cilantro leaves)."
    )
    assert stocked.last_buttons("Erin")[-2:] == ["Cook this", "Add cilantro leaves"]
    (added,) = await stocked.tap("Erin", "Add cilantro leaves")
    assert added == "Added to the grocery list: cilantro leaves."


async def test_the_main_item_missing_rules_it_out(stocked: Scenario) -> None:
    pantry = stocked.app.services.pantry
    assert pantry is not None
    pantry.set_status("dried chickpeas", "out", source="said")
    assert "Chana Masala" not in ideas(stocked)


async def test_low_energy_only_short_recipes(stocked: Scenario) -> None:
    assert ideas(stocked)[0] == "Chana Masala"
    energy = stocked.app.services.energy
    energy.record(stocked.member("Erin"), "day_level", -1.0)
    assert energy.suggested_level(stocked.member("Erin")) == "low"
    assert "Chana Masala" not in ideas(stocked)  # seven steps and an overnight soak


async def test_not_one_cooked_this_week(stocked: Scenario) -> None:
    from datetime import timedelta

    from themi import clock

    recipes = stocked.app.services.recipes
    assert recipes is not None
    chana = next(r for r in recipes.all() if r.name == "Chana Masala")
    stocked.app.db.execute(
        "INSERT INTO cooking_sessions (member_id, recipe_id, phase, started_at, last_tap_at, "
        "ended_at, outcome) VALUES (?, ?, 'done', ?, ?, ?, 'finished')",
        (1, chana.id, *(clock.now().isoformat(),) * 3),
    )
    assert "Chana Masala" not in ideas(stocked)
    clock.advance(timedelta(days=8))
    assert "Chana Masala" in ideas(stocked)


async def test_what_can_we_make(stocked: Scenario) -> None:
    stocked.primary.queue_tool_call("cookbook_recipes_we_can_make", {})
    (listed,) = await stocked.say("Erin", "What can we make from the cookbook with what we have?")
    assert listed.splitlines()[0] == "From the cookbook, with what you have:"
    assert "> Chana Masala (you'd need cilantro leaves)" in listed
    assert "energy" not in listed.lower()
