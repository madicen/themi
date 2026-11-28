"""F65j (Michael's bug #275): the Together page's shared to-dos are held and dragged with a
real pointer in headless Chrome at the frame's 1080 x 1920, as F64i's person page is. The
server's side is in test_wall_together_moves; `htmx.ajax` is stood in for. Skipped without
Chrome."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.integration.test_wall_person_drag_browser import centre, mouse
from tests.integration.test_wall_screen import screen, task, wall
from tests.integration.test_wall_top_browser import the_wall
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def together_page(s: Scenario, tab: Tab) -> None:
    page = await screen(s)
    sheet = (await get(s, "/wall/view/together")).text
    script = re.search(r'<script src="([^"]*wall\.js[^"]*)"', page)
    assert script is not None
    await the_wall(tab, page, "Wednesday, October 21")
    await tab.value(
        "window.sent = []; window.htmx = { ajax: function (m, u, o) {"
        " window.sent.push([m, u, o.values]); } };"
        f"document.getElementById('wall-view').innerHTML = {json.dumps(sheet)};"
        f"var s = document.createElement('script'); s.src = {json.dumps(script.group(1))};"
        "document.head.appendChild(s); true"
    )
    assert await until(lambda: tab.value("!!document.querySelector('[data-drag]')"))
    await asyncio.sleep(0.3)  # wall.js listening


async def test_bug_275_a_family_to_do_is_dragged_higher_up(wall: Scenario) -> None:
    vac, mimi, gas = [await task(wall, "Erin", t, both="shared") for t in ("Vac", "Box", "Gas")]
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", width=1080, height=1920) as tab:
        await together_page(wall, tab)
        x, y = await centre(tab, f'[data-task="{gas.id}"]')
        _, ty = await centre(tab, f'[data-task="{vac.id}"]')
        await mouse(tab, "mousePressed", x, y)
        await asyncio.sleep(0.6)  # held
        assert await tab.value("!document.querySelector('.drag-to-people').hidden")
        assert await tab.value("!document.querySelector('.drag-delete').hidden")
        for step in range(1, 6):
            await mouse(tab, "mouseMoved", x, y + (ty - 20 - y) * step / 5)
        await mouse(tab, "mouseReleased", x, ty - 20)
        sent = json.loads(await tab.value("JSON.stringify(window.sent)"))
        moved = {"task": str(gas.id), "op": "move", "before": str(vac.id)}
        assert sent == [["POST", "/wall/view/together/move", moved]]
        assert mimi.id


async def test_f65k_a_tap_on_the_words_unfolds_it_and_the_ring_still_ticks(
    wall: Scenario,
) -> None:
    """F65k (idea #276): its words open the editor; its ring is still a tick."""
    (vac,) = [await task(wall, "Erin", "Vacuum maintenance", both="shared")]
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", width=1080, height=1920) as tab:
        await together_page(wall, tab)
        wx, wy = await centre(tab, f'[data-task="{vac.id}"] .wall-title')
        await mouse(tab, "mousePressed", wx, wy)
        await mouse(tab, "mouseReleased", wx, wy)
        sent = json.loads(await tab.value("JSON.stringify(window.sent)"))
        assert sent == [["GET", f"/wall/view/together?edit={vac.id}", None]]
        await tab.value("window.sent = []; true")
        rx, ry = await centre(tab, f'[data-task="{vac.id}"] .ring')
        await mouse(tab, "mousePressed", rx, ry)
        await mouse(tab, "mouseReleased", rx, ry)
        assert await tab.value("JSON.stringify(window.sent)") == "[]"  # htmx's own tick
