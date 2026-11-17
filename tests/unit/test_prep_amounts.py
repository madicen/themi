"""F45b (bug #213): a prep job says how much, from the ingredient line it came from."""

from __future__ import annotations

import pytest

from themi_home.cooking import with_amount


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
