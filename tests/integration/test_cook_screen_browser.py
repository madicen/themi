"""CK1: the cook screen's own script, in a real (headless) Chrome: [Next] moves the session,
and a timer counts down from the server's times. Skipped where Chrome isn't installed."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.integration.test_session_page_browser import CHROME, page_in_chrome, until
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from themi import clock
from themi.core import keys

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def to_step_three(scenario: Scenario) -> None:
    load(scenario.app.services)
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(scenario.member("Erin"), alfredo)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await cooking.advance(session, action)
    await cooking.advance(session, "goto:2")


async def test_next_on_the_page_moves_the_session(scenario: Scenario) -> None:
    clock.unfreeze()  # the browser keeps real time
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        count = "document.querySelector('.cook-count').textContent"
        assert (await tab.value(count)).startswith("Step 2 of 3")
        await tab.value("document.querySelector('form[data-move=next] button').click()")
        assert await until(lambda: tab.value(f"({count}).startsWith('Step 3 of 3')"))
        assert await tab.value("!!document.querySelector('form[data-move=finish]')")
    row = scenario.app.db.one("SELECT phase, step FROM cooking_sessions ORDER BY id DESC")
    assert row is not None and (row["phase"], row["step"]) == ("cook", 2)


async def test_a_timer_counts_down_from_the_servers_times(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        await tab.value("document.querySelector('form[data-move=next] button').click()")
        chip = "document.querySelector('.cook-offers .cook-chip')"
        assert await until(lambda: tab.value(f"!!{chip}"))
        await tab.value(f"{chip}.click()")
        left = "(document.querySelector('.cook-timer-left') || {}).textContent || ''"
        first = await until(lambda: tab.value(f"(({left}).match(/^9:5\\d$/) || [''])[0]"))
        assert first, "the timer never showed counting down from 10:00"
        later = await until(lambda: tab.value(f"({left}) !== '{first}' ? ({left}) : ''"), 4)
        assert later and later < first
