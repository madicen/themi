"""F64h (Michael's idea #272, "the day drill down on the wall frame should be oriented
vertically"): the calendar screen's day runs down the portrait frame, a column per person,
filling the screen down to Due that day and Weather. The real page, its CSS and wall.js in a
headless Chrome at the frame's 1080 x 1920. Skipped where Chrome isn't installed."""

from __future__ import annotations

import json
import re

import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.integration.test_session_page_browser import CHROME, page_in_chrome, until
from tests.integration.test_wall_screen import calendar, screen, share
from tests.integration.test_wall_top_browser import the_wall
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import local
from tests.scenarios.test_triage import ERIN
from themi import clock

__all__ = ["calendar"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

BOX = "JSON.stringify(document.querySelector({}).getBoundingClientRect())"


async def test_the_day_runs_down_the_frame_and_fills_it(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(10, day=23), local(11, day=23), summary="Dentist")
    fake_gcal.add_event(ERIN, local(10, day=23), local(12, day=23), summary="Long call")
    fake_gcal.add_event(ERIN, local(15, day=23), local(16, day=23), summary="Tea Time!")
    await calendar.run_periodic("calendar.busy")
    page = await screen(calendar)
    sheet = (await get(calendar, "/wall/calendar?day=2026-10-23")).text
    script = re.search(r'<script src="([^"]*wall\.js[^"]*)"', page)
    assert script is not None
    clock.unfreeze()
    async with page_in_chrome(
        calendar, calendar.member("Erin"), "body", width=1080, height=1920
    ) as tab:
        await the_wall(tab, page, "Friday, October 23")
        await tab.value(
            f"document.getElementById('wall-view').innerHTML = {json.dumps(sheet)};"
            f"var s = document.createElement('script'); s.src = {json.dumps(script.group(1))};"
            "s.onload = function () { document.getElementById('wall-view').dispatchEvent("
            "new CustomEvent('htmx:afterSwap', {bubbles: true})); };"
            "document.head.appendChild(s); true"
        )
        assert await until(lambda: tab.value(
            "!!document.querySelector('.pl-block') && "
            "document.querySelector('.pl-block').style.top !== ''"
        ))  # fmt: skip
        body = json.loads(await tab.value(BOX.format("'.pl-body'")))
        boxes = json.loads(await tab.value(BOX.format("'.cal-dayplan .sheet-pair'")))
        assert body["height"] > body["width"] * 0.8  # tall, not a band across the top
        assert body["height"] >= 1920 * 0.4
        assert boxes["top"] >= body["bottom"] - 1  # Due that day and Weather below it
        assert boxes["bottom"] <= await tab.value("document.documentElement.scrollHeight")
        cols = await tab.value("document.querySelectorAll('.pl-col').length")
        assert cols >= 2  # a column per person, and the family's
        tops = json.loads(await tab.value(
            "JSON.stringify([...document.querySelectorAll('.pl-block')].map(b => {"
            " const r = b.getBoundingClientRect();"
            " return [b.querySelector('.pl-title').textContent, Math.round(r.top),"
            " Math.round(r.left), Math.round(r.height)]; }))"
        ))  # fmt: skip
        by = {t[0]: t for t in tops}
        assert by["Dentist"][1] < by["Tea Time!"][1]  # down the screen by time
        assert by["Long call"][3] > by["Dentist"][3] * 1.5  # two hours, taller than one
        assert by["Dentist"][2] != by["Long call"][2]  # overlapping: side by side
