"""CK1: the cook screen's own script, in a real (headless) Chrome: [Next] moves the session,
and a timer counts down from the server's times. CK3: a fired timer's chime and pulse.
Skipped where Chrome isn't installed."""

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


async def short_timer(scenario: Scenario) -> int:
    """A timer that ends in a moment, started as the page's chip would start one."""
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    session = cooking.current(scenario.member("Erin"))
    assert session is not None
    recipe = cooking.recipes.get(session.recipe_id)
    assert recipe is not None
    cooking.timers.start(scenario.member("Erin"), session, recipe, "3", 0.01)
    return session.id


async def fire(scenario: Scenario) -> None:
    async def fired() -> bool:
        await scenario.run_jobs()
        return bool(scenario.app.db.scalar("SELECT COUNT(*) FROM cooking_timers "
                                           "WHERE fired_at IS NOT NULL"))  # fmt: skip

    assert await until(fired)


FAKE_AUDIO = (
    "window.themiCook.playChime = function (v) { window.chimes = (window.chimes || 0) + 1;"
    " window.chimeVolume = v; }; window.themiCook.alertEvery = 400;"
)


async def test_a_fired_timer_chimes_and_pulses_until_tapped(scenario: Scenario) -> None:
    """CK3: when fired_at appears, a chime (faked here) and a slow pulse, again and again,
    until the card is tapped."""
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        await tab.value(FAKE_AUDIO)
        await short_timer(scenario)
        await fire(scenario)
        await tab.value("window.themiCook.poll()")
        assert await until(lambda: tab.value("(window.chimes || 0) >= 3"))  # repeating
        assert await tab.value("window.chimeVolume") == 70
        assert await tab.value("document.querySelector('.cook-pulse').classList.contains('on')")
        assert await tab.value("document.body.classList.contains('cook-alerting')")
        assert (
            await tab.value("getComputedStyle(document.querySelector('.cook-pulse')).animationName")
            == "cook-pulse"
        )
        await tab.value("document.querySelector('.cook-timer-done').click()")
        assert await until(lambda: tab.value("!document.querySelector('.cook-timer[data-fired]')"))
        stopped = await tab.value("window.chimes")
        rang = await until(lambda: tab.value(f"window.chimes > {stopped}"), 1.5)
        assert rang is None  # three more rings in that time, had it gone on
        assert not await tab.value("document.body.classList.contains('cook-alerting')")


async def test_reduced_motion_is_a_steady_border(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        reduce = [{"name": "prefers-reduced-motion", "value": "reduce"}]
        await tab.call("Emulation.setEmulatedMedia", features=reduce)
        await tab.value(FAKE_AUDIO)
        await short_timer(scenario)
        await fire(scenario)
        await tab.value("window.themiCook.poll()")
        assert await until(lambda: tab.value("document.body.classList.contains('cook-alerting')"))
        pulse = "getComputedStyle(document.querySelector('.cook-pulse')).display"
        assert await tab.value(pulse) == "none"
        shadow = await tab.value("getComputedStyle(document.body).boxShadow")
        assert "inset" in shadow and "12px" in shadow
        assert await tab.value("(window.chimes || 0) >= 1")  # the chime still sounds
