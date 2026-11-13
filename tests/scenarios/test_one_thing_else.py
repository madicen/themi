"""F42e (Michael's idea #203): the one-task message ("Just one thing", or focus_now with one)
has a "Something else" button that swaps it for the next one. The clock starts on
Wednesday 21 October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from datetime import timedelta

from tests.scenarios.harness import Scenario
from tests.scenarios.test_focus import board, task
from themi import clock
from themi.core import keys
from themi.standard.focus import ELSE_BUTTON, NO_MORE_TEXT


async def three(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Sort the mail", effort=1)
    await task(scenario, "Erin", "Water the plants", effort=2)
    await task(scenario, "Erin", "Deep clean the oven", effort=3)


async def one(scenario: Scenario) -> str:
    return await scenario.app.services.get(keys.focus).send(scenario.member("Erin"), count=1)


def shown(scenario: Scenario) -> str:
    return scenario.edits("Erin")[-1]["text"]


async def test_something_else_goes_through_them_then_says_thats_all(scenario: Scenario) -> None:
    await three(scenario)
    assert (await one(scenario)).startswith("For now, just this:\n- Sort the mail")
    assert scenario.last_buttons("Erin")[0] == ELSE_BUTTON
    await scenario.tap("Erin", ELSE_BUTTON)
    assert shown(scenario).startswith("For now, just this:\n- Water the plants")
    await scenario.tap("Erin", ELSE_BUTTON)
    assert shown(scenario) == f"For now, just this:\n- Deep clean the oven\n{NO_MORE_TEXT}"
    assert not scenario.edits("Erin")[-1].get("reply_markup")


async def test_the_last_one_has_no_button(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Sort the mail", effort=1)
    await one(scenario)
    buttons = scenario.app.db.scalar("SELECT buttons FROM outbox WHERE kind = 'focus'")
    assert ELSE_BUTTON not in buttons


async def test_one_done_in_between_isnt_offered(scenario: Scenario) -> None:
    await three(scenario)
    await one(scenario)
    water = next(
        t for t in board(scenario).open_for(scenario.member("Erin")) if "plants" in t.title
    )
    await board(scenario).complete(water.id, scenario.member("Erin"))
    await scenario.tap("Erin", ELSE_BUTTON)
    assert shown(scenario).startswith("For now, just this:\n- Deep clean the oven")


async def test_the_next_day_starts_fresh(scenario: Scenario) -> None:
    await three(scenario)
    await one(scenario)
    clock.advance(timedelta(days=1))
    await scenario.tap("Erin", ELSE_BUTTON)
    assert scenario.inbox("Erin")[-1].startswith("For now, just this:\n- Sort the mail")
