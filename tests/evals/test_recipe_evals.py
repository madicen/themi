"""RC2a: ingredient lines read as shopping items by a real model. Opt-in, like the other
evals:

    make evals EVAL_ARGS='-k recipe_items'

40 lines from the family cookbook (2026-11-06). Each passes when the item is one of the
accepted names and has no amount in it; the whole set passes at 36 of 40. An item whose
words aren't in the line falls back to the rule-based reading (so nothing is invented), and
is scored like any other.
"""

from __future__ import annotations

import asyncio
import re

from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.runner import use_backend
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.core.recipe_groceries import line_key

LINES: list[tuple[str, tuple[str, ...]]] = [
    ("1 Cup cashews, soaked in water for at least 10 minutes (130g)", ("cashews",)),
    ("2 garlic cloves, peeled and left whole", ("garlic", "garlic cloves")),
    ("1 tsp mild/yellow miso", ("miso", "yellow miso", "mild miso", "mild/yellow miso")),
    ("¼ tsp ground nutmeg", ("nutmeg", "ground nutmeg")),
    ("½ Cup (120 ml) room temperature soy milk", ("soy milk",)),
    ("1½ tsp Dijon mustard or substitute ½ tsp dry mustard", ("dijon mustard",)),
    ("1 Cup neutral oil like sunflower, grapeseed or vegetable oil",
     ("neutral oil", "oil", "sunflower oil")),
    ("1 11oz package of silken tofu", ("silken tofu",)),
    ("1 package silken tofu (12.3oz) firm",
     ("silken tofu", "firm silken tofu", "silken tofu firm")),
    ("2 fat garlic cloves ( or 2 tsp granulated garlic)", ("garlic", "garlic cloves")),
    ("1½ Tbsp apple cider or sherry vinegar", ("apple cider vinegar", "apple cider")),
    ("1 Tbsp nutritional yeast", ("nutritional yeast",)),
    ("16oz silken tofu", ("silken tofu",)),
    ("⅓ Cup sriracha sauce", ("sriracha", "sriracha sauce")),
    ("½ tsp maple syrup", ("maple syrup",)),
    ("¼ Cup soy sauce- shoyu, tamari, or Braggs liquid amino acids", ("soy sauce",)),
    ("1 4 x 8 inch sheet of dried  kombu ( seaweed) or wakame seaweed", ("kombu", "dried kombu")),
    ("1 Cupconfectioners' sugar", ("confectioners' sugar", "confectioners sugar")),
    ("2 tsp light corn syrup", ("corn syrup", "light corn syrup")),
    ("2 Cups (480g) pure apple juice", ("apple juice", "pure apple juice")),
    ("2 licorice tea bags", ("licorice tea", "licorice tea bags")),
    ("1 can chili pinto beans", ("chili pinto beans", "pinto beans")),
    ("1 can refried beans", ("refried beans",)),
    ("Frozen corn", ("frozen corn", "corn")),
    ("Tortilla chips (for serving)", ("tortilla chips",)),
    ("550ml soy milk", ("soy milk",)),
    ("50g all purpose flour", ("all purpose flour", "flour", "all-purpose flour")),
    ("1 ½ Cup (180 grams) white whole wheat flour -- or regular whole wheat flour",
     ("white whole wheat flour", "whole wheat flour")),
    ("1 Tbsp + 1 tsp baking powder (20g)", ("baking powder",)),
    ("2 Cups unsweetened almond milk -- or other plant based milk",
     ("almond milk", "unsweetened almond milk")),
    ("¼ Cup (70g) unsweetened applesauce (or ¼ Cup (85g) pure maple syrup)",
     ("applesauce", "unsweetened applesauce")),
    ("Zest of 1 small lemon -- scant 1 tsp (optional)", ("lemon",)),
    ("3/4 Cup split mung beans, rinsed", ("split mung beans", "mung beans")),
    ("1 - 1 ¼ tsp black salt a.k.a. kala namak", ("black salt", "kala namak")),
    ("1 ⅓ Cup canned light coconut milk", ("coconut milk", "light coconut milk")),
    ("2 Cups dried chickpeas, soaked overnight", ("dried chickpeas", "chickpeas")),
    ("2 tsp dried mango powder (amchur)", ("mango powder", "dried mango powder", "amchur")),
    ("8 ounces flat rice noodles", ("flat rice noodles", "rice noodles")),
    ("14oz (400g) can peeled tomatoes", ("peeled tomatoes", "canned tomatoes", "tomatoes")),
    ("Salt and pepper to taste", ("salt and pepper", "salt")),
]  # fmt: skip
NEEDED = 36
AMOUNT = re.compile(r"\d|½|¼|¾|⅓|\bcups?\b|\btbsp\b|\btsp\b|\bgrams?\b", re.IGNORECASE)


async def test_recipe_items(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    try:
        reader = scenario.app.services.maybe(keys.recipe_groceries)
        assert reader is not None
        read = await reader._read(scenario.member("Erin"), [line for line, _ in LINES])
    finally:
        await scenario.stop()
        if eval_backend.pace:
            await asyncio.sleep(eval_backend.pace)
    misses = []
    for line, accepted in LINES:
        item = read[line_key(line)].item
        if item not in accepted or AMOUNT.search(item):
            misses.append(f"{line!r} -> {item!r}")
    print(f"\nrecipe items: {len(LINES) - len(misses)}/{len(LINES)}")
    for miss in misses:
        print("  missed", miss)
    assert len(LINES) - len(misses) >= NEEDED, "; ".join(misses)
