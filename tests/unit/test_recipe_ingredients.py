# ruff: noqa: RUF001  (the cookbook's own dashes, kept as written)
"""RC2a: ingredient lines read as shopping items."""

from __future__ import annotations

import pytest

from themi.core.recipe_groceries import _from_model, line_key, read_line, words_in_line


@pytest.mark.parametrize(
    ("line", "item", "note"),
    [
        ("1 Cup cashews, soaked in water for at least 10 minutes (130g)", "cashews",
         "soaked in water for at least 10 minutes"),
        ("2 garlic cloves, peeled and left whole", "garlic cloves", "peeled and left whole"),
        ("1 package silken tofu (12.3oz) firm", "silken tofu firm", ""),
        ("¼ –½ Cup fresh herbs- dill, basil", "fresh herbs", "dill, basil"),
        ("1 Cup (250 ml) ,Basmati Rice OR Seeraga samba", "basmati rice", "Seeraga samba"),
        ("1 Tbsp + 1 tsp baking powder (20g)", "baking powder", ""),
        ("14oz (400g) can peeled tomatoes", "peeled tomatoes", ""),
        ("550ml soy milk", "soy milk", ""),
        ("Pinch of ground nutmeg", "ground nutmeg", ""),
        ("1 batch of Bechamel Sauce", "bechamel sauce", ""),
        ("Frozen corn", "frozen corn", ""),
        ("Tortilla chips (for serving)", "tortilla chips", ""),
    ],
)  # fmt: skip
def test_rule_based_reading(line: str, item: str, note: str) -> None:
    read = read_line(line)
    assert (read.item, read.note) == (item, note)


def test_staples_and_optional_lines() -> None:
    assert read_line("½ tsp salt").staple
    assert read_line("Salt and pepper to taste").staple
    assert read_line("1½ Cups (375 ml), water").staple
    assert not read_line("1 tsp black salt a.k.a. kala namak").staple
    assert read_line("Optional: homemade plant cheese").optional
    assert read_line("1 tsp cinnamon (optional)").optional


def test_the_models_item_must_be_in_the_line() -> None:
    line = "1 package silken tofu (12.3oz) firm"
    assert words_in_line("silken tofu", line)
    assert not words_in_line("firm tofu block", line)
    invented = _from_model(line, {"item": "tempeh", "optional": False, "staple": False})
    assert invented.item == "silken tofu firm"  # the rule's reading instead
    kept = _from_model(line, {"item": "Silken Tofu", "quantity": "1", "unit": "package",
                              "note": "firm", "optional": False, "staple": False})  # fmt: skip
    assert (kept.item, kept.note) == ("silken tofu", "firm")
    assert _from_model("½ tsp salt", {"item": "salt", "staple": False}).staple  # always a staple


def test_line_keys_ignore_spacing_and_case() -> None:
    assert line_key("1 Cup  Cashews") == line_key("1 cup cashews ")
