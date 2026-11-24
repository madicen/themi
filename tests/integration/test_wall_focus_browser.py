"""F60e: the body double's built-in loop on the wall, run by the wall's own script in a
headless Chrome. The player is outside the sheet, so a tap or a redraw doesn't stop it, and
the session ending does. Playing is stood in for (headless Chrome has no sound to play).
Skipped where Chrome isn't installed."""

from __future__ import annotations

import json
import re

import pytest

from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.integration.test_wall_list_views import get, post
from tests.integration.test_wall_screen import screen, wall
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

STAND_INS = """
window.__saved = [];
function playing(el, on) {
  el.__playing = on;
  Object.defineProperty(el, "paused", {
    configurable: true, get: function () { return !this.__playing; }
  });
}
HTMLMediaElement.prototype.play = function () { playing(this, true); return Promise.resolve(); };
HTMLMediaElement.prototype.pause = function () { playing(this, false); };
var realFetch = window.fetch.bind(window);
window.fetch = function (url, options) {
  if (String(url).indexOf("/wall/focus/music") < 0) return realFetch(url, options);
  window.__saved.push(String(options && options.body));
  return Promise.resolve({ ok: true, status: 204 });
};
"""


async def running_sheet(wall: Scenario, tab: Tab) -> str:
    husband = wall.member("Husband")
    await post(wall, "/wall/focus/start", member=str(husband.id), what="typed",
               typed="the dishes", mode="silent", minutes="0")  # fmt: skip
    page = await screen(wall)
    script = re.search(r'<script src="([^"]*wall\.js[^"]*)"', page)
    assert script is not None
    sheet = (await get(wall, f"/wall/focus?member={husband.id}")).text
    await tab.value(
        'document.body.innerHTML = \'<div id="wall-view"></div>'
        '<audio id="wall-music" loop preload="none"></audio>\';'
        f"document.getElementById('wall-view').innerHTML = {json.dumps(sheet)};"
        f"var s = document.createElement('script'); s.src = {json.dumps(script.group(1))};"
        "document.head.appendChild(s); true"
    )
    assert await until(lambda: tab.value("!!document.querySelector('[data-music-play]')"))
    return sheet


async def test_play_starts_the_loop_and_a_redraw_doesnt_stop_it(wall: Scenario) -> None:
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", before=STAND_INS) as tab:
        sheet = await running_sheet(wall, tab)

        async def click_play() -> bool:  # again until wall.js has loaded and handles it
            await tab.value("document.querySelector('[data-music-play]').click()")
            return bool(await tab.value("!document.getElementById('wall-music').paused"))

        assert await until(click_play)
        src = await tab.value("document.getElementById('wall-music').getAttribute('src')")
        assert src and "/audio/" in src
        assert await until(lambda: tab.value(
            "document.querySelector('[data-music-play]').textContent === 'Pause'"
        ))  # fmt: skip
        assert await until(lambda: tab.value("window.__saved.some(function (b) {"
                                             " return b.indexOf('played=1') >= 0; })"))  # fmt: skip

        # the sheet is drawn again (a tap's answer): still playing, and the button says so
        await tab.value(
            f"document.getElementById('wall-view').innerHTML = {json.dumps(sheet)};"
            "document.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles: true})); true"
        )
        assert not await tab.value("document.getElementById('wall-music').paused")
        assert await tab.value(
            "document.querySelector('[data-music-play]').textContent === 'Pause'"
        )

        # the session ends: the loop stops with it
        await tab.value(
            "document.getElementById('wall-view').innerHTML ="
            " '<section class=\"wall-sheet\"><div data-focus-finished></div></section>';"
            "document.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles: true})); true"
        )
        assert await tab.value("document.getElementById('wall-music').paused")
