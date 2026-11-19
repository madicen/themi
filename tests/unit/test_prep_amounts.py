"""F45b (bug #213): a prep job says how much, from the ingredient line it came from."""

from __future__ import annotations

import pytest

from themi_home.cooking import with_amount
from themi_home.quantities import scale_line, weight_after_unit


@pytest.mark.parametrize(
    ("job", "line", "shown"),
    [
        ("soy milk: measure", "2 cups (480 g) unsweetened soy milk*",
         "Soy milk: measure 2 cups (480 g)"),
        ("vegan butter: measure, melt", "1/2 cup (115 g) vegan butter, melted",
         "Vegan butter: measure 1/2 cup (115 g), melt"),
        ("yeast: measure", "2 packets (4 1/2 tsp) Quick Rise Yeast (I used Red Star)",
         "Yeast: measure 2 packets (4 1/2 tsp) quick rise"),
        ("water: measure", "1½ Cups water", "Water: measure 1½ Cups"),
        ("Onion: dice", "1 large onion", "Onion (1 large): dice"),
        ("Garlic: peel, keep whole", "2 garlic cloves, peeled and left whole",
         "Garlic (2 cloves): peel, keep whole"),
        ("Lemon juice: measure 1 tsp", "1 tsp lemon juice", "Lemon juice: measure 1 tsp"),
        ("salt: measure", "salt to taste", "Salt: measure"),
        ("Eggs: beat", "2 eggs", "Eggs (2): beat"),
    ],
)  # fmt: skip
def test_the_amount_goes_with_the_job(job: str, line: str, shown: str) -> None:
    assert with_amount(job, line) == shown


@pytest.mark.parametrize(
    ("job", "line", "shown"),
    [
        ("sugar: measure", "¾ (150g) Cup sugar", "Sugar: measure ¾ Cup (150g)"),
        ("canola oil: measure", "⅓ (70g) Cup canola oil", "Canola oil: measure ⅓ Cup (70g)"),
        ("dark corn syrup: measure", "2 (40g) Tbsp dark corn syrup",
         "Dark corn syrup: measure 2 Tbsp (40g)"),
        ("cocoa powder: measure", "2 (14g) Tbsp natural cocoa powder",
         "Cocoa powder: measure 2 Tbsp (14g)"),
        ("flour: measure", "1 ¼ (170g) Cups plus 2 Tbsp all-purpose flour",
         "Flour: measure 1 ¼ Cups + 2 Tbsp (170g)"),
        ("vanilla: measure", "1 tsp pure vanilla extract", "Vanilla: measure 1 tsp"),
    ],
)  # fmt: skip
def test_the_unit_stays_when_the_grams_come_first(job: str, line: str, shown: str) -> None:
    """F49c (bug #220): Snowy Earthquake Cookie's lines, as a recipe is read."""
    assert with_amount(job, weight_after_unit(line)) == shown


@pytest.mark.parametrize(
    ("line", "tidied"),
    [
        ("¾ (150g) Cup sugar", "¾ Cup (150g) sugar"),
        ("1 ¼ (170g) Cups plus 2 Tbsp all-purpose flour",
         "1 ¼ Cups + 2 Tbsp (170g) all-purpose flour"),
        ("2 (150 grams) cups oats", "2 cups (150 grams) oats"),
        ("1 (5 oz) can tuna", "1 can (5 oz) tuna"),
        ("about 1 (120g) Cup flour", "about 1 Cup (120g) flour"),
        ("1 Cup (130g) cashews", "1 Cup (130g) cashews"),  # already after: as it was
        ("2 (14 oz) cans coconut milk", "2 cans (14 oz) coconut milk"),
        ("salt to taste", "salt to taste"),
    ],
)  # fmt: skip
def test_a_weight_before_its_unit_moves_after_it(line: str, tidied: str) -> None:
    assert weight_after_unit(line) == tidied


def test_the_recipes_own_grams_scale_with_it() -> None:
    assert scale_line(weight_after_unit("¾ (150g) Cup sugar"), 2).line == "1½ Cups (300g) sugar"
