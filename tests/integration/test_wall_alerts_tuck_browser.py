"""WA7 (Michael, after WA6 on the frame: "tapping things has effects that can be unintended,
like checking off items when you wanted to dismiss the timers"): a tap on the wall while an
alert shows tucks the alerts into a strip at the top and ticks nothing; the wall can then be
used, and the alerts come back after a while without a touch, on a tap on the strip, or when
something new shows. The real page and wall.js in headless Chrome at the frame's 1080 x 1920.
Skipped without Chrome."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.integration.test_wall_alerts import kitchen
from tests.integration.test_wall_person_drag_browser import centre, mouse
from tests.integration.test_wall_screen import screen, task
from tests.integration.test_wall_top_browser import the_wall
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys

__all__ = ["kitchen"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

TUCKED = "document.body.classList.contains('alerts-tucked')"
CHORE = ".wall-item[data-key]"


async def wall_with_a_timer(s: Scenario, tab: Tab) -> None:
    """The wall with Erin's chore and a 6 minute timer from chat, wall.js listening, and each
    click that reaches a chore counted in window.ticks."""
    cooking = s.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    cooking.timers.start_alone(s.member("Erin"), 6)
    page = await screen(s)
    assert "wall-alert " in page and 'data-tuck-after="30"' in page
    script = re.search(r'<script src="([^"]*wall\.js[^"]*)"', page)
    assert script is not None
    clock.unfreeze()
    await the_wall(tab, page, "Wednesday, October 21")
    await tab.value(
        "window.ticks = 0; document.addEventListener('click', function (e) {"
        f" if (e.target.closest({json.dumps(CHORE)})) window.ticks++; }});"
        f"var s = document.createElement('script'); s.src = {json.dumps(script.group(1))};"
        "document.head.appendChild(s); true"
    )
    assert await until(lambda: tab.value("document.body.classList.contains('alerting')"))


async def tap(tab: Tab, x: float, y: float) -> None:
    await mouse(tab, "mousePressed", x, y)
    await mouse(tab, "mouseReleased", x, y)


async def test_a_tap_on_the_wall_tucks_the_alerts_and_ticks_nothing(kitchen: Scenario) -> None:
    await task(kitchen, "Erin", "Vet")
    async with page_in_chrome(
        kitchen, kitchen.member("Erin"), "body", width=1080, height=1920
    ) as tab:
        await wall_with_a_timer(kitchen, tab)
        x, y = await centre(tab, CHORE)
        await tap(tab, x, y)
        assert await tab.value("window.ticks") == 0, "the tap went through to the chore"
        assert await until(lambda: tab.value(TUCKED))
        # a strip above the clock, the wall not dimmed and moved down under it
        card = json.loads(await tab.value(
            "JSON.stringify(document.querySelector('.wall-alert').getBoundingClientRect())"
        ))  # fmt: skip
        top = await tab.value("document.querySelector('.wall-top').getBoundingClientRect().top")
        assert card["bottom"] <= top and card["height"] < 140
        assert await tab.value(
            "getComputedStyle(document.getElementById('wall-columns')).opacity"
        ) == "1"  # fmt: skip
        shown = await tab.value(
            "JSON.stringify([...document.querySelector('.wall-alert').children]"
            ".filter(e => getComputedStyle(e).display !== 'none').map(e => e.className))"
        )
        assert json.loads(shown) == ["alert-head", "alert-count"]  # its words and countdown
        # now the wall is the wall's
        x, y = await centre(tab, CHORE)
        await tap(tab, x, y)
        assert await tab.value("window.ticks") == 1
        assert await tab.value(TUCKED)
        # a tap on the strip brings the alerts back, and the chore under them is safe again
        cx, cy = await centre(tab, ".wall-alert")
        await tap(tab, cx, cy)
        assert await until(lambda: tab.value(f"!{TUCKED}"))
        x, y = await centre(tab, CHORE)
        await tap(tab, x, y)
        assert await tab.value("window.ticks") == 1
        assert await tab.value(TUCKED)


async def test_they_come_back_after_a_while_without_a_touch(kitchen: Scenario) -> None:
    await task(kitchen, "Erin", "Vet")
    async with page_in_chrome(
        kitchen, kitchen.member("Erin"), "body", width=1080, height=1920
    ) as tab:
        await wall_with_a_timer(kitchen, tab)
        await tab.value(
            "document.querySelector('.wall-alert-list').setAttribute('data-tuck-after', '1'); true"
        )
        await tap(tab, 540, 1880)
        assert await until(lambda: tab.value(TUCKED))
        await asyncio.sleep(0.6)
        x, y = await centre(tab, CHORE)
        await tap(tab, x, y)  # a touch starts the wait again
        await asyncio.sleep(0.6)
        assert await tab.value(TUCKED)
        assert await until(lambda: tab.value(f"!{TUCKED}"), seconds=3)


async def test_a_timer_going_off_comes_back_at_once(kitchen: Scenario) -> None:
    async with page_in_chrome(
        kitchen, kitchen.member("Erin"), "body", width=1080, height=1920
    ) as tab:
        await wall_with_a_timer(kitchen, tab)
        await tap(tab, 540, 1880)
        assert await until(lambda: tab.value(TUCKED))
        # the next poll draws it as up (the server's side is test_wall_alerts)
        await tab.value(
            "var c = document.querySelector('.wall-alert'); c.setAttribute('data-state', 'up');"
            "c.setAttribute('data-sound-key', 'up'); true"
        )
        assert await until(lambda: tab.value(f"!{TUCKED}"), seconds=3)
