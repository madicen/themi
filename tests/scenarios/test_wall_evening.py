"""WL2: the wall at 7:42 pm, as on the Themi Wall Plan's mock-up.

Erin's husband has an evening routine and two chores (one from yesterday); Erin has a chore
and no evening routine; the bins are either of theirs, from yesterday; the family list has
two to-dos. One look at the frame shows all of it, each in its place.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.integration.test_wall_screen import EVENING, column, screen, step, task, with_wall, words
from tests.scenarios.harness import Scenario
from themi import clock


@pytest.fixture
async def wall(family: SeededFamily, fake_telegram: FakeTelegram) -> AsyncIterator[Scenario]:
    scenario = with_wall(family, fake_telegram)
    await scenario.start()
    try:
        yield scenario
    finally:
        await scenario.stop()


async def test_michael_and_erins_evening_on_one_screen(wall: Scenario) -> None:
    day = wall.today()
    yesterday = day - timedelta(days=1)
    for title in ("Cycle the dishwasher", "Take meds", "Cover the birdcage"):
        step(wall, "Husband", "Evening", title)
    step(wall, "Erin", "Morning", "Walk dog")
    await task(wall, "Husband", "Refill pet feeders", due=day, chore=True)
    await task(wall, "Husband", "Declutter the kitchen", due=yesterday, chore=True)
    await task(wall, "Husband", "Vacuum upstairs")
    await task(wall, "Erin", "Clean the upstairs bathroom", due=day, chore=True)
    await task(wall, "Erin", "Process the mail")
    await task(wall, "Erin", "Bring bins in", due=yesterday, chore=True, both="either")
    await task(wall, "Erin", "Move Mimi's box upstairs", both="shared")
    await task(wall, "Husband", "Unjam the vacuum", both="shared")
    clock.advance(EVENING)

    page = await screen(wall)

    husband = words(column(page, f"m{wall.member('Husband').id}"))
    assert husband == (
        "H Husband This evening Evening routine 🍽️ Cycle the dishwasher 💊 Take meds "
        "🦜 Cover the birdcage Chores Declutter the kitchen from yesterday 🥣 Refill pet feeders "
        "To-do 🧹 Vacuum upstairs"
    )
    erin = words(column(page, f"m{wall.member('Erin').id}"))
    assert erin == (
        "E Erin This evening Evening routine Nothing set for this evening "
        "Chores 🚽 Clean the upstairs bathroom To-do ✉️ Process the mail"
    )
    together = words(column(page, "together"))
    assert together == (
        "Together This evening Either of you 🗑️ Bring bins in from yesterday "
        "Family to-do Move Mimi&#39;s box upstairs 🧹 Unjam the vacuum"
    )
    assert "Bring bins in is still waiting from yesterday." in page
    assert "Walk dog" not in page  # a morning step, not shown in the evening
