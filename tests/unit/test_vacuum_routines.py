"""F25a: which of the wall's routine items are about the robot's problem."""

from __future__ import annotations

import pytest

from themi.connectors.roborock import BIN, FAULT, JAMMED, NOT_DOCKED, PART, STUCK, WATER_EMPTY
from themi.core.vacuum import about


@pytest.mark.parametrize(
    ("kind", "detail", "title"),
    [
        (WATER_EMPTY, "", "Refill vacuum water"),
        (WATER_EMPTY, "", "Replace the vacuum's water"),
        (JAMMED, "the main brush is jammed", "Unclog the robot vacuum"),
        (STUCK, "it's trapped", "Free the vacuum"),
        (BIN, "the dustbin is out", "Empty the vac's dustbin"),
        (NOT_DOCKED, "", "Put Robbie back on his dock"),
        (PART, "filter", "Replace the vacuum filter"),
        (PART, "main brush", "Clean the robot's brush"),
    ],
)
def test_items_about_it(kind: str, detail: str, title: str) -> None:
    assert about(kind, detail, title, "Robbie")


@pytest.mark.parametrize(
    ("kind", "detail", "title"),
    [
        (WATER_EMPTY, "", "Vacuum upstairs bedroom"),  # a person's chore
        (WATER_EMPTY, "", "Water the plants"),  # not the vacuum
        (JAMMED, "the main brush is jammed", "Refill vacuum water"),  # another problem
        (PART, "mop roller", "Vacuum and mop the kitchen"),  # nothing replaced
        (FAULT, "a sensor error", "Check the vacuum"),  # a fault has no words of its own
    ],
)
def test_items_not_about_it(kind: str, detail: str, title: str) -> None:
    assert not about(kind, detail, title, "Robbie")
