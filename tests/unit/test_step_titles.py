"""F50d (bug #234: "the recipe instruction headings are just the first few words"): every
recipe's steps get model titles in the background, not only the ones cooked."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from themi.ai.errors import PermanentError
from themi.core import keys
from themi_home.cooking import Cooking
from themi_home.cooking_titles import fallback_title
from themi_home.recipes import Recipe


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


def untitled(cooking: Cooking) -> list[Recipe]:
    return [
        r for r in cooking.recipes.all()
        if r.steps and r.kind == "recipe" and cooking.titles.cached(r) is None
    ]  # fmt: skip


def answer(recipes: list[Recipe]) -> dict[str, Any]:
    return {
        "recipes": [
            {"id": r.id, "titles": [f"Step {n} of {r.id}" for n in range(1, len(r.steps) + 1)]}
            for r in recipes
        ]
    }


async def test_a_recipe_never_cooked_gets_titles(scenario: Scenario, cooking: Cooking) -> None:
    cooking.titles.per_call, cooking.titles.calls_per_run = 3, 1
    first = untitled(cooking)[:3]
    scenario.primary.queue_structured(answer(first))
    await scenario.run_periodic("cooking.step_titles")
    asked = scenario.primary.requests[-1]
    assert asked.schema is not None and asked.schema["required"] == ["recipes"]
    assert f'<data source="recipe {first[0].name}">' in asked.prompt  # the recipes are data
    assert all(f"recipe id {r.id}" in asked.prompt for r in first)
    for recipe in first:
        assert cooking.titles.titles(recipe) == answer([recipe])["recipes"][0]["titles"]
    assert untitled(cooking)[0].id not in {r.id for r in first}

    from themi_home.recipe_card import card_svg  # the card picture draws them, as card_png does

    drawn = card_svg(first[0], "light", lambda line: line, cooking.titles.titles(first[0]))
    assert f"Step 1 of {first[0].id}" in drawn


async def test_so_many_a_call_and_a_few_calls_a_run(scenario: Scenario, cooking: Cooking) -> None:
    from themi_home.cooking_titles import CALLS_PER_RUN, PER_CALL

    assert (PER_CALL, CALLS_PER_RUN) == (10, 3)
    waiting = untitled(cooking)
    assert len(waiting) > 8
    for batch in (waiting[:4], waiting[4:8]):
        scenario.primary.queue_structured(answer(batch))
    cooking.titles.per_call, cooking.titles.calls_per_run = 4, 2
    calls = len(scenario.primary.requests)
    await scenario.run_periodic("cooking.step_titles")
    assert len(scenario.primary.requests) == calls + 2
    assert len(untitled(cooking)) == len(waiting) - 8


async def test_a_recipe_whose_words_change_is_titled_again(
    scenario: Scenario, cooking: Cooking
) -> None:
    cooking.titles.per_call, cooking.titles.calls_per_run = 1, 1
    (recipe,) = untitled(cooking)[:1]
    scenario.primary.queue_structured(answer([recipe]))
    await scenario.run_periodic("cooking.step_titles")
    assert cooking.titles.cached(recipe) is not None
    changed = cooking.recipes.get(recipe.id)
    assert changed is not None
    scenario.app.db.execute(
        "UPDATE recipes SET steps = ? WHERE id = ?",
        ('[{"text": "Stir it all together.", "group": ""}]', recipe.id),
    )
    changed = cooking.recipes.get(recipe.id)
    assert changed is not None and cooking.titles.cached(changed) is None
    assert untitled(cooking)[0].id == recipe.id  # oldest first: it goes again next


async def test_a_failed_call_is_tried_again_three_times_at_most(
    scenario: Scenario, cooking: Cooking
) -> None:
    cooking.titles.per_call, cooking.titles.calls_per_run = 1, 1
    (recipe,) = untitled(cooking)[:1]
    for _ in range(3):
        scenario.primary.queue_error(PermanentError("busy"), op="structured")
        scenario.fallback.queue_error(PermanentError("busy"), op="structured")
        await scenario.run_periodic("cooking.step_titles")
        assert cooking.titles.cached(recipe) is None  # nothing stored as final
        assert cooking.titles.titles(recipe) == [fallback_title(s.text) for s in recipe.steps]
    scenario.primary.queue_structured(answer(untitled(cooking)[1:2]))
    await scenario.run_periodic("cooking.step_titles")
    asked = scenario.primary.requests[-1]
    assert f"recipe id {recipe.id}\n" not in asked.prompt  # three tries: left with first words


async def test_near_the_free_limit_it_waits(scenario: Scenario, cooking: Cooking) -> None:
    usage = scenario.app.services.usage
    usage.set_limit("ollama.requests", per_day=4, per_month=None, set_by="test")
    usage.count("ollama.requests", 3, scope="1")
    calls = len(scenario.primary.requests)
    await scenario.run_periodic("cooking.step_titles")
    assert len(scenario.primary.requests) == calls
