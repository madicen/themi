# ruff: noqa: RUF001  (recipes' own dashes and fractions)
"""RC2b: quantities as recipes write them, scaled."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from themi.core.quantities import NeedsYield, fraction, number, scale_for, scale_line


@pytest.mark.parametrize(
    ("text", "value"),
    [("1½", 1.5), ("1 ½", 1.5), ("1 1/2", 1.5), ("1/2", 0.5), ("1.5", 1.5), ("½", 0.5),
     ("⅓", 1 / 3), ("2", 2.0), ("¾", 0.75)],
)  # fmt: skip
def test_numbers(text: str, value: float) -> None:
    assert number(text) == pytest.approx(value)


@pytest.mark.parametrize(
    ("line", "factor", "scaled"),
    [
        ("1 Cup cashews, soaked in water for at least 10 minutes (130g)", 2,
         "2 Cups cashews, soaked in water for at least 10 minutes (260g)"),
        ("1.5 Cups water (355mL)", 2, "3 Cups water (710mL)"),
        ("½ tsp salt", 2, "1 tsp salt"),
        ("1 11oz package of silken tofu", 2, "2 11oz package of silken tofu"),
        ("1 package silken tofu (12.3oz) firm", 1.5,
         "2 packages (1½ needed) silken tofu (12.3oz) firm"),
        ("¼ –½ Cup fresh herbs- dill", 2, "½-1 Cup fresh herbs- dill"),
        ("1 can chili pinto beans", 1.5, "2 cans (1½ needed) chili pinto beans"),
        ("1 Tbsp + 1 tsp baking powder (20g)", 2, "2 Tbsp + 2 tsp baking powder (40g)"),
        ("1 ½ Cup (180 grams) white whole wheat flour", 2,
         "3 Cups (360 grams) white whole wheat flour"),
        ("14oz (400g) can peeled tomatoes", 0.5, "7 oz (200g) can peeled tomatoes"),
        ("3-4 Medjool dates (42 grams) - remove pits", 2,
         "6-8 Medjool dates (42 grams) - remove pits"),
        ("1⅓ Cup (266g) sugar", 0.5, "⅔ Cup (135g) sugar"),
        ("2½ Cups (300g) all purpose flour", 0.5, "1¼ Cups (150g) all purpose flour"),
        ("550ml soy milk", 0.5, "275ml soy milk"),
        ("1 batch of Bechamel Sauce", 1.5, "2 batches (1½ needed) of Bechamel Sauce"),
        ("1 onion, finely chopped", 0.5, "½ onion, finely chopped"),
        ("2 Cups dried chickpeas, soaked overnight", 3, "6 Cups dried chickpeas, soaked overnight"),
    ],
)  # fmt: skip
def test_scaling_lines(line: str, factor: float, scaled: str) -> None:
    assert scale_line(line, factor).line == scaled


def test_lines_without_a_leading_amount_stay_as_written() -> None:
    for line in ("Frozen corn", "Optional: homemade plant cheese", "Zest of 1 small lemon"):
        result = scale_line(line, 2)
        assert (result.line, result.changed) == (line, False)


def test_the_amount_alone() -> None:
    assert scale_line("1 Cup cashews (130g)", 2).amount == "2 Cups (260g)"
    assert scale_line("1 Cup cashews (130g)", 1).amount == "1 Cup (130g)"


@given(st.integers(min_value=0, max_value=40), st.sampled_from([0, 1, 2, 3, 4, 6, 8]))
def test_eighths_and_thirds_round_trip(whole: int, eighths: int) -> None:
    value = whole + eighths / 8
    if value == 0:
        return
    assert number(fraction(value)) == pytest.approx(value)


@given(st.integers(min_value=1, max_value=12), st.sampled_from([1 / 3, 2 / 3]))
def test_thirds_round_trip(whole: int, third: float) -> None:
    assert number(fraction(whole + third)) == pytest.approx(whole + third)


def test_what_they_asked_for() -> None:
    assert scale_for("half batch", None) == 0.5
    assert scale_for("a double batch", None) == 2
    assert scale_for("x3", None) == 3 == scale_for("3x", None)
    assert scale_for("for 6", 4) == 1.5
    assert scale_for("", None) == 1
    with pytest.raises(NeedsYield):
        scale_for("for 6", None)
    with pytest.raises(ValueError, match="isn't an amount"):
        scale_for("lots", None)
