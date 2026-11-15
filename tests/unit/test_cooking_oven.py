"""OV4/OV7: a step's oven words read as the mode, °F and oven to use."""

from __future__ import annotations

import pytest

from themi_home.connectors.smarthq import LOWER, UPPER
from themi_home.connectors.smarthq import events as ov
from themi_home.cooking_oven import RISE, heat_for


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Preheat the oven to 400°F.", (ov.BAKE, 400, None)),
        ("Preheat oven to 200C and line a tray.", (ov.BAKE, 390, None)),  # 392°F, to the 5
        ("Preheat the oven to 180°C, fan-assisted.", (ov.CONV_MULTI_BAKE, 355, None)),
        ("Preheat the oven to 425 degrees F, convection setting.", (ov.CONV_MULTI_BAKE, 425, None)),
        ("Preheat the oven to 350°F. Bake on the upper oven rack...", (ov.BAKE, 350, UPPER)),
        ("Preheat the oven to 375°F; use the lower oven.", (ov.BAKE, 375, LOWER)),
        ("Bake for 20 minutes.", None),
    ],
)
def test_a_steps_preheat(text: str, found: tuple | None) -> None:
    assert heat_for(text) == found


@pytest.mark.parametrize(
    "text",
    [
        "Cover and let rise in a warm place for 1 hour.",
        "Let the dough proof until doubled, about 90 minutes.",
        "Shape the rolls and leave for a second rise, 45 minutes.",
    ],
)
def test_a_rising_step(text: str) -> None:
    assert RISE.search(text)


@pytest.mark.parametrize("text", ["Bake until golden.", "Proofread the recipe card."])
def test_not_a_rising_step(text: str) -> None:
    assert not RISE.search(text)
