"""CK12: the tablet layout in a real (headless) Chrome: a tap on the step strip jumps to that
step, a timer's bar empties as it counts, an ingredient ticks the moment it's tapped, and
the footer says the screen stays awake only once the wake lock took. Skipped where Chrome
isn't installed."""

from __future__ import annotations

import json

import pytest

from tests.integration.test_cook_screen_browser import short_timer, to_step_three
from tests.integration.test_session_page_browser import CHROME, page_in_chrome, until
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def test_a_tap_on_the_strip_jumps_to_that_step(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)  # Alfredo Sauce, on step 2 of 3
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        strip = "[...document.querySelectorAll('.cook-steps li')]"
        marks = f"JSON.stringify({strip}.map(li => li.className))"
        assert json.loads(await tab.value(marks)) == ["done", "current", "later"]
        boxes = await tab.value(
            f"JSON.stringify({strip}.map(li => Math.round(li.getBoundingClientRect().top)))"
        )
        assert len(set(json.loads(boxes))) == 1  # one row across the top
        await tab.value(f"{strip}[2].querySelector('button').click()")
        count = "document.querySelector('.cook-count').textContent"
        assert await until(lambda: tab.value(f"({count}).startsWith('Step 3 of 3')"))
        assert await until(lambda: tab.value(f"{strip}[2].className === 'current'"))
    row = scenario.app.db.one("SELECT step FROM cooking_sessions ORDER BY id DESC")
    assert row is not None and row["step"] == 2


async def test_a_timers_bar_empties_as_it_counts(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    erin = scenario.member("Erin")
    session = cooking.current(erin)
    assert session is not None
    recipe = cooking.recipes.get(session.recipe_id)
    assert recipe is not None
    cooking.timers.start(erin, session, recipe, "2", 0.1)  # six seconds
    async with page_in_chrome(scenario, erin, ".cook-moves", width=1180, height=820) as tab:
        bar = "parseFloat(document.querySelector('.cook-bar span').style.width || '100')"
        assert await tab.value("document.querySelector('.cook-timer-of').textContent") == (
            "of 0:06 · remaining"
        )
        first = await until(lambda: tab.value(f"{bar} < 100 ? {bar} : 0"))
        assert first, "the bar never moved"
        assert await until(lambda: tab.value(f"{bar} < {first} - 10"))


async def test_an_ingredient_ticks_at_once(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        line = "document.querySelector('.cook-amounts .cook-amount')"
        assert await tab.value(f"{line}.getAttribute('aria-pressed')") == "false"
        total = await tab.value("document.querySelectorAll('.cook-amounts .cook-amount').length")
        # the tick shows in the same moment, before the server answers
        ticked = await tab.value(
            f"(() => {{ {line}.click(); return {line}.getAttribute('aria-pressed'); }})()"
        )
        assert ticked == "true"
        added = "document.querySelector('.cook-added').textContent"
        assert await tab.value(added) == f"1 of {total} added"

        async def saved() -> bool:
            row = scenario.app.db.one("SELECT used FROM cooking_sessions ORDER BY id DESC")
            return row is not None and row["used"] != "[]"

        assert await until(saved)
        assert await until(lambda: tab.value(f"{line}.getAttribute('aria-pressed') === 'true'"))


async def test_the_footer_says_awake_only_with_the_wake_lock(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    await short_timer(scenario)
    with_lock = (
        "navigator.wakeLock = { request: () => Promise.resolve("
        "{ addEventListener: () => {}, release: () => Promise.resolve() }) };"
    )
    no_lock = "delete Navigator.prototype.wakeLock; delete navigator.wakeLock;"
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              before=with_lock) as tab:  # fmt: skip
        assert await until(lambda: tab.value("!document.querySelector('.cook-awake').hidden"))
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              before=no_lock) as tab:  # fmt: skip
        assert await tab.value("document.querySelector('.cook-awake').hidden")
