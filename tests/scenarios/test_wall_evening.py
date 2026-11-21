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
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import (
    EVENING,
    column,
    frame,
    screen,
    step,
    task,
    with_wall,
    words,
)
from tests.integration.test_wall_taps import tap
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys


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
        "To-do 🧹 Vacuum upstairs View full day"  # WL9c: each column's foot
    )
    erin = words(column(page, f"m{wall.member('Erin').id}"))
    assert erin == (
        "E Erin This evening Evening routine Nothing set for this evening "
        "Chores 🚽 Clean the upstairs bathroom To-do ✉️ Process the mail View full day"
    )
    together = words(column(page, "together"))
    assert together == (
        "Together This evening Either of you 🗑️ Bring bins in from yesterday "
        "Family to-do Move Mimi&#39;s box upstairs 🧹 Unjam the vacuum View shared list"
    )
    assert "Bring bins in is still waiting from yesterday." in page
    assert "Walk dog" not in page  # a morning step, not shown in the evening

    # WL9c: Erin ticks her chore. It stays, struck through, so a wrong tap can be undone
    # there; ten minutes on it has folded into "✓ 1 done".
    bathroom = next(
        t
        for t in wall.app.services.get(keys.taskboard).open_for(wall.member("Erin"))
        if t.title == "Clean the upstairs bathroom"
    )
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, f"task-{bathroom.id}")
    erin = words(column(await screen(wall), f"m{wall.member('Erin').id}"))
    assert erin.startswith("E Erin 1 done tonight") and "Clean the upstairs bathroom" in erin
    clock.advance(timedelta(minutes=11))
    erin = words(column(await screen(wall), f"m{wall.member('Erin').id}"))
    assert "Clean the upstairs bathroom" not in erin and "Chores ✓ 1 done" in erin
