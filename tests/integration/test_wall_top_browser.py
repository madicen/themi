"""F63a (Michael's bug #269, "that top line shouldn't wrap on the wall frame"): the wall's top
row, with Talk to Themi, Body double and the weather, keeps the date on one line at the
frame's 1080 x 1920. The real page and its CSS in a headless Chrome, fitted by wall-fit.js.
Skipped where Chrome isn't installed."""

from __future__ import annotations

import json
import re

import pytest

from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.integration.test_wall_screen import screen
from tests.integration.test_wall_views import rainy
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["rainy"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

LONGEST = "Wednesday, September 30"


async def wall_page(s: Scenario) -> str:
    """The wall as the frame gets it, read before the clock runs (the weather is for today)."""
    page = await screen(s)
    assert 'class="wall-weather"' in page and "Body double" in page
    clock.unfreeze()
    return page


async def the_wall(tab: Tab, page: str, date: str = LONGEST) -> None:
    """The wall page drawn in the tab (its own scripts not run), the longest date in it, then
    fitted as wall.js fits it."""
    fit = re.search(r'<script src="([^"]*wall-fit\.js[^"]*)"', page)
    assert fit is not None
    await tab.value(
        "document.documentElement.className = 'wall-root';"
        f"document.documentElement.innerHTML = {json.dumps(page)}; true"
    )
    assert await until(lambda: tab.value(
        "getComputedStyle(document.querySelector('.wall-time')).fontWeight === '700'"
    ))  # fmt: skip
    await tab.value(
        f"document.querySelector('.wall-date').textContent = {json.dumps(date)};"
        "document.querySelector('.wall-time').firstChild.textContent = '12:59';"
        f"var s = document.createElement('script'); s.src = {json.dumps(fit.group(1))};"
        "document.head.appendChild(s); true"
    )
    assert await until(lambda: tab.value("!!window.themiWallFit"))
    await tab.value("window.themiWallFit.fitWall(document); true")


async def test_bug_269_the_date_stays_on_one_line(rainy: Scenario) -> None:
    page = await wall_page(rainy)
    async with page_in_chrome(rainy, rainy.member("Erin"), "body", width=1080, height=1920) as tab:
        await the_wall(tab, page)
        date = "document.querySelector('.wall-date')"
        lines = await tab.value(
            f"{date}.getBoundingClientRect().height / parseFloat(getComputedStyle({date}).fontSize)"
        )
        assert lines < 1.6, "the date wrapped"
        top = "document.querySelector('.wall-top')"
        assert await tab.value(f"{top}.scrollWidth <= {top}.clientWidth + 1"), "off the edge"
        # each button keeps its name when only its icon shows
        names = await tab.value(
            "JSON.stringify([...document.querySelectorAll('.wall-talk')]"
            ".map(b => b.getAttribute('aria-label')))"
        )
        assert json.loads(names) == ["Talk to Themi", "Body double"]


async def test_a_short_date_keeps_the_buttons_words_when_they_fit(rainy: Scenario) -> None:
    page = await wall_page(rainy)
    async with page_in_chrome(rainy, rainy.member("Erin"), "body", width=1080, height=1920) as tab:
        await the_wall(tab, page, date="Sunday, May 3")
        await tab.value(
            "document.querySelector('.wall-focus').remove();"
            "window.themiWallFit.fitWall(document); true"
        )
        shown = await tab.value(
            "getComputedStyle(document.querySelector('.wall-talk span')).display"
        )
        assert shown != "none"
