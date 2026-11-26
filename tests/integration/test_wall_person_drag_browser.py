"""F64i (Michael's idea #274): a chore or to-do on a person's page is held and dragged with a
real pointer (a mouse, and a finger) in headless Chrome at the frame's 1080 x 1920: picked up,
the chips and Delete show, and a drop says where it went. The server's side is in
test_wall_person_moves; here `htmx.ajax` is stood in for. Skipped without Chrome."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.integration.test_wall_screen import screen, task, wall
from tests.integration.test_wall_top_browser import the_wall
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def person_page(s: Scenario, tab: Tab) -> None:
    page = await screen(s)
    sheet = (await get(s, f"/wall/view/person/{s.member('Erin').id}")).text
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


async def centre(tab: Tab, selector: str) -> tuple[float, float]:
    box = json.loads(await tab.value(
        f"JSON.stringify(document.querySelector({json.dumps(selector)}).getBoundingClientRect())"
    ))  # fmt: skip
    return box["left"] + box["width"] / 2, box["top"] + box["height"] / 2


async def mouse(tab: Tab, kind: str, x: float, y: float) -> None:
    await tab.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left",
                   buttons=0 if kind == "mouseReleased" else 1, clickCount=1)  # fmt: skip


async def finger(tab: Tab, kind: str, x: float, y: float) -> None:
    points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
    await tab.call("Input.dispatchTouchEvent", type=kind, touchPoints=points)


async def test_held_with_a_mouse_and_dropped_higher_up(wall: Scenario) -> None:
    vet, mail, gate = [await task(wall, "Erin", t) for t in ("Vet", "Mail", "Gate")]
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", width=1080, height=1920) as tab:
        await person_page(wall, tab)
        x, y = await centre(tab, f'[data-task="{gate.id}"]')
        _, ty = await centre(tab, f'[data-task="{vet.id}"]')
        await mouse(tab, "mousePressed", x, y)
        await asyncio.sleep(0.6)  # held
        assert await tab.value("!document.querySelector('.drag-to-people').hidden")
        assert await tab.value("!document.querySelector('.drag-delete').hidden")
        for step in range(1, 6):
            await mouse(tab, "mouseMoved", x, y + (ty - 20 - y) * step / 5)
        await mouse(tab, "mouseReleased", x, ty - 20)
        sent = json.loads(await tab.value("JSON.stringify(window.sent)"))
        url = f"/wall/view/person/{wall.member('Erin').id}/move"
        moved = {"task": str(gate.id), "op": "move", "before": str(vet.id)}
        assert sent == [["POST", url, moved]]
        assert await tab.value("document.querySelector('.drag-to-people').hidden")
        assert mail.id


async def test_a_quick_tap_is_still_a_tick(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Vet")
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", width=1080, height=1920) as tab:
        await person_page(wall, tab)
        x, y = await centre(tab, f'[data-task="{vet.id}"]')
        await mouse(tab, "mousePressed", x, y)
        await mouse(tab, "mouseReleased", x, y)
        assert await tab.value("document.querySelector('.drag-to-people').hidden")
        assert await tab.value("JSON.stringify(window.sent)") == "[]"  # no drag


async def test_held_with_a_finger_and_dropped_on_someone_or_delete(wall: Scenario) -> None:
    vet = await task(wall, "Erin", "Vet")
    mail = await task(wall, "Erin", "Mail")
    husband = wall.member("Husband")
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", width=1080, height=1920) as tab:
        await person_page(wall, tab)
        for held, where, want in (
            (vet, f'.drag-to[data-to="{husband.id}"]', {"op": "give", "to": str(husband.id)}),
            (mail, ".drag-delete", {"op": "delete"}),
        ):
            x, y = await centre(tab, f'[data-task="{held.id}"]')
            await finger(tab, "touchStart", x, y)
            await asyncio.sleep(0.6)
            tx, ty = await centre(tab, where)
            for step in range(1, 6):
                await finger(tab, "touchMove", x + (tx - x) * step / 5, y + (ty - y) * step / 5)
            await finger(tab, "touchEnd", tx, ty)
            sent = json.loads(await tab.value("JSON.stringify(window.sent)"))
            assert sent[-1][2] == {"task": str(held.id), **want}
