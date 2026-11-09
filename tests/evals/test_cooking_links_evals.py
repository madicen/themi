"""CK2: which ingredient lines each step uses, read by a real model. Opt-in, like the other
evals:

    make evals EVAL_ARGS='-k cooking_links'

15 recipes: the fixture cookbook's 12 with steps and 3 more below. A recipe passes when
every link the model gives is really used in that step (the line's item is named in the
step, or the step speaks of "ingredients", "everything" or "the rest") and none is added;
the set passes at 13 of 15. A link whose item isn't in its line is dropped before scoring,
as it is in use.
"""

from __future__ import annotations

import asyncio
import re

from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.runner import use_backend
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.cookbook import cookbook, load, recipe
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home.cooking_links import words
from themi_home.recipe_groceries import read_line

MORE = [
    *recipe(
        "Scallion Noodles",
        ["8 ounces flat rice noodles", "4 scallions, sliced", "2 Tbsp soy sauce",
         "1 Tbsp toasted sesame oil", "1 tsp sugar"],
        ["Cook the noodles as the packet says, then drain.",
         "Warm the sesame oil in a wok and fry the scallions for 1 minute.",
         "Add the noodles, soy sauce and sugar and toss for 2 minutes."],
    ),
    *recipe(
        "Lemon Rice",
        ["1 Cup basmati rice", "2 Cups water", "1 lemon, zested and juiced", "½ tsp salt",
         "1 Tbsp olive oil"],
        ["Rinse the rice until the water runs clear.",
         "Bring the water and salt to a boil, add the rice, cover and simmer for 15 minutes.",
         "Stir in the lemon zest, lemon juice and olive oil."],
    ),
    *recipe(
        "Garlic Greens",
        ["1 bunch kale, stems removed", "3 garlic cloves, sliced", "1 Tbsp olive oil",
         "Pinch of chili flakes", "Salt to taste"],
        ["Heat the oil over medium heat and add the garlic and chili flakes.",
         "Add the kale and a splash of water; cover for 3 minutes.",
         "Season with salt and serve."],
    ),
]  # fmt: skip
NEEDED = 13
EVERY = re.compile(r"\b(?:ingredients|everything|the rest|remaining)\b", re.IGNORECASE)


async def test_cooking_links(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    misses: list[str] = []
    try:
        load(scenario.app.services, [*cookbook(), *MORE])
        cooking = scenario.app.services.maybe(keys.cooking)
        assert cooking is not None
        recipes = [r for r in cooking.recipes.all() if r.steps and not r.is_chart][:15]
        assert len(recipes) == 15, [r.name for r in recipes]
        for found in recipes:
            data = await cooking.links.ask(scenario.member("Erin"), found)
            assert data is not None, found.name
            items = [read_line(i.text) for i in found.ingredients]
            for step, lines in data.items():
                text = found.steps[int(step)].text
                for n in lines:
                    if not (EVERY.search(text) or words(items[n].item) & words(text)):
                        misses.append(f"{found.name} step {int(step) + 1}: {items[n].item}")
    finally:
        await scenario.stop()
        if eval_backend.pace:
            await asyncio.sleep(eval_backend.pace)
    failed = {m.split(" step ")[0] for m in misses}
    print(f"\ncooking links: {15 - len(failed)}/15 recipes clean")
    for miss in misses:
        print("  added", miss)
    assert 15 - len(failed) >= NEEDED, "; ".join(misses)
