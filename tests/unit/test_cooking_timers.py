"""RC3c: the times a step names."""

from __future__ import annotations

from tests.fixtures.cookbook import document
from themi_home import cookbook as book
from themi_home.cooking_timers import Found, durations


def test_a_plain_time() -> None:
    assert durations("Cook for 10 minutes, stirring often") == [Found(10, "10 min")]


def test_a_range_offers_its_low_end() -> None:
    assert durations("Cook for 1-2 minutes, or until dry.") == [Found(1, "1 min (1-2)")]
    assert durations("about 2 to 3 minutes") == [Found(2, "2 min (2-3)")]


def test_two_times_in_one_step() -> None:
    step = (
        "Cook on the first side until bubbles form, about 2 to 3 minutes. Flip and cook "
        "until browned, about 1 to 2 minutes more."
    )
    assert durations(step) == [Found(2, "2 min (2-3)"), Found(1, "1 min (1-2)")]


def test_hours_and_long_waits() -> None:
    assert durations("Roast for 1 hour.") == [Found(60, "1 hr")]
    assert durations("Freeze for 24 hours.") == [Found(1440, "24 hrs", reminder=True)]
    assert durations("Soak overnight.") == [Found(0, "overnight", reminder=True)]
    assert durations("Bake for at least four hours.") == []  # words, not digits: no timer


def test_every_fixture_step() -> None:
    found = {
        step.text[:30]: durations(step.text)
        for recipe in book.parse(document()).recipes
        for step in recipe.steps
        if durations(step.text)
    }
    assert found["Transfer the sauce to a medium"] == [Found(10, "10 min")]
    assert found["Secure the lid, close the pres"] == [Found(35, "35 min")]
    assert found["Freeze for 24"[:0] or "Process until smooth and freez"] == [
        Found(1440, "24 hrs", reminder=True)
    ]
    assert all(len(v) <= 2 for v in found.values())
