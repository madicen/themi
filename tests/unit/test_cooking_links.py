"""CK2: which ingredient lines each step uses (by rule, and by one cached model call), and the
"With grams" units. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import document, load
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, RANCH, lines
from themi.ai.errors import PermanentError
from themi.core import keys
from themi_home import cookbook as book
from themi_home.cooking import Cooking, CookingPreferences
from themi_home.cooking_links import gaps, rule_links, with_grams, words
from themi_home.recipe_groceries import read_line


def fixture_recipes() -> list:
    return [r for r in book.parse(document()).recipes if r.steps]


def linked(name: str) -> dict[int, list[str]]:
    recipe = next(r for r in fixture_recipes() if r.name == name)
    items = [read_line(i.text) for i in recipe.ingredients]
    return {s: [items[n].item for n in found] for s, found in rule_links(recipe, items).items()}


def test_rule_links_for_the_fixture_steps() -> None:
    assert linked("Alfredo Sauce") == {0: ["cashews", "water"], 1: ["cashews"], 2: []}
    assert linked("Pancakes")[1][:3] == [
        "white whole wheat flour",
        "all-purpose flour",
        "baking powder",
    ]  # fmt: skip  "the flours": both flours, by the word that names a food alone
    every = [item for found in linked("Pancakes").values() for item in found]
    assert "onion powder" not in every  # "powder" alone: no
    assert linked("Silken Tofu Ranch Dressing") == {0: []}


def test_every_rule_link_is_named_in_its_step() -> None:
    for recipe in fixture_recipes():
        items = [read_line(i.text) for i in recipe.ingredients]
        for s, found in rule_links(recipe, items).items():
            said = words(recipe.steps[s].text)
            for n in found:
                assert words(items[n].item) & said, (recipe.name, s, items[n].item)


def test_a_gap_is_a_step_with_amounts_and_no_link() -> None:
    ranch = next(r for r in fixture_recipes() if r.name == "Silken Tofu Ranch Dressing")
    items = [read_line(i.text) for i in ranch.ingredients]
    assert gaps(ranch, rule_links(ranch, items)) == [0]  # "Blend ingredients together"
    alfredo = next(r for r in fixture_recipes() if r.name == "Alfredo Sauce")
    items = [read_line(i.text) for i in alfredo.ingredients]
    assert gaps(alfredo, rule_links(alfredo, items)) == []  # step 3 names no amount


def test_with_grams_only_where_the_line_gives_a_weight() -> None:
    assert with_grams("1 Cup cashews, soaked in water for at least 10 minutes (130g)") == (
        "1 Cup (130 g) cashews, soaked in water for at least 10 minutes"
    )
    assert with_grams("1 ½ Cup (180 grams) white whole wheat flour") == (
        "1 ½ Cup (180 g) white whole wheat flour"
    )
    assert with_grams("1 Tbsp + 1 tsp baking powder (20g)") == "1 Tbsp + 1 tsp (20 g) baking powder"
    assert with_grams("2 tsp pure vanilla extract") == "2 tsp pure vanilla extract"  # no weight
    assert with_grams("1.5 Cups water (355mL)") == "1.5 Cups water (355mL)"  # not a weight


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


def ranch(cooking: Cooking):  # type: ignore[no-untyped-def]
    return next(r for r in cooking.recipes.all() if r.name == "Silken Tofu Ranch Dressing")


async def test_model_links_kept_and_dropped(scenario: Scenario, cooking: Cooking) -> None:
    scenario.primary.queue_structured(lines(RANCH))
    recipe = ranch(cooking)
    items = await cooking.groceries.ingredients(scenario.member("Erin"), recipe)
    scenario.primary.queue_structured(
        {
            "steps": [
                {
                    "step": 1,
                    "lines": [
                        {"line": 1, "item": "silken tofu"},
                        {"line": 4, "item": "garlic"},
                        {"line": 2, "item": "butter"},  # not in "2 Tbsp water": dropped
                        {"line": 40, "item": "salt"},  # no such line: dropped
                    ],
                },
                {"step": 9, "lines": [{"line": 1, "item": "silken tofu"}]},  # no such step
            ]
        }
    )
    await cooking.links.ensure(scenario.member("Erin"), recipe, items)
    assert cooking.links.links(recipe, items) == {0: [0, 3]}
    assert scenario.primary.requests[-1].prompt.startswith(
        '<data source="recipe Silken Tofu Ranch Dressing">'
    )  # the recipe is data


async def test_the_links_are_cached_until_the_words_change(
    scenario: Scenario, cooking: Cooking
) -> None:
    scenario.primary.queue_structured(lines(RANCH))
    recipe = ranch(cooking)
    erin = scenario.member("Erin")
    items = await cooking.groceries.ingredients(erin, recipe)
    scenario.primary.queue_structured({"steps": [{"step": 1, "lines": []}]})
    await cooking.links.ensure(erin, recipe, items)
    calls = len(scenario.primary.requests)
    await cooking.links.ensure(erin, recipe, items)
    assert len(scenario.primary.requests) == calls  # from the cache
    from dataclasses import replace

    changed = replace(recipe, steps=[replace(recipe.steps[0], text="Blend all ingredients well")])
    scenario.primary.queue_structured({"steps": [{"step": 1, "lines": []}]})
    await cooking.links.ensure(erin, changed, items)
    assert len(scenario.primary.requests) == calls + 1  # new words: asked again


async def test_no_model_means_rule_links_only(scenario: Scenario, cooking: Cooking) -> None:
    scenario.primary.queue_structured(lines(RANCH))
    recipe = ranch(cooking)
    erin = scenario.member("Erin")
    items = await cooking.groceries.ingredients(erin, recipe)
    scenario.primary.queue_error(PermanentError("no key"), op="structured")
    scenario.fallback.queue_error(PermanentError("no key"), op="structured")
    await cooking.links.ensure(erin, recipe, items)
    assert cooking.links.links(recipe, items) == {0: []}
    assert cooking.links.cached(recipe) is None  # asked again next time


async def to_steps(scenario: Scenario, cooking: Cooking, *, in_group: bool = False) -> int:
    scenario.primary.queue_structured(lines(ALFREDO))
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    session = await cooking.start(scenario.member("Erin"), alfredo, in_group=in_group)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await cooking.advance(session, action)
    return session.id


async def test_the_amounts_for_this_step(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    await to_steps(scenario, cooking)
    amounts = cooking.state(erin)["amounts"]
    assert [a["line"] for a in amounts["uses"]] == [
        "1 Cup cashews, soaked in water for at least 10 minutes (130g)",
        "1.5 Cups water (355mL)",
    ]
    assert len(amounts["groups"]) == 1 and len(amounts["groups"][0]["lines"]) == 9
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_units="grams")
    uses = cooking.state(erin)["amounts"]["uses"]
    assert uses[0]["line"] == "1 Cup (130 g) cashews, soaked in water for at least 10 minutes"


async def test_scale_mid_session(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await to_steps(scenario, cooking)
    state = cooking.state(erin)
    tapped = await cooking.act_from_page(erin, session_id, "scale", state["seq"], {"for": "6"})
    assert not tapped and tapped.said.startswith("Alfredo Sauce doesn't say how many it makes")
    tapped = await cooking.act_from_page(erin, session_id, "scale", state["seq"],
                                         {"said": "double"})  # fmt: skip
    assert tapped and tapped.said == "Now double the recipe."
    state = cooking.state(erin)
    assert state["amounts"]["uses"][0]["line"].startswith("2 Cups cashews")
    assert state["scale_words"] == "double"
    assert [o["on"] for o in state["scales"]["options"]] == [False, False, True]
    assert scenario.edits("Erin")[-1]["text"].startswith("Alfredo Sauce, a double batch of:")
    scenario.app.db.execute("UPDATE recipes SET yield_said = '4' WHERE name = 'Alfredo Sauce'")
    tapped = await cooking.act_from_page(erin, session_id, "scale", state["seq"], {"for": "6"})
    assert tapped.said == "Now for 6." and cooking.state(erin)["scales"]["for"] == 6


async def test_used_ticks_are_shared(scenario: Scenario, cooking: Cooking) -> None:
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    session_id = await to_steps(scenario, cooking, in_group=True)
    seq = cooking.state(husband)["seq"]
    assert await cooking.act_from_page(husband, session_id, "use", seq, {"n": "0"})
    assert [a["used"] for a in cooking.state(erin)["amounts"]["uses"]] == [True, False]
    drawer = cooking.state(erin)["amounts"]["groups"][0]["lines"]
    assert drawer[0]["used"] is True
    seq = cooking.state(erin)["seq"]
    assert await cooking.act_from_page(erin, session_id, "use", seq, {"n": "0"})  # a second tap
    assert cooking.state(husband)["amounts"]["uses"][0]["used"] is False
