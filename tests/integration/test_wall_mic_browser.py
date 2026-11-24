"""F60d (Michael's idea #264): the wall's mic says when it's listening and when it's working.
The Talk sheet and the wall's own script, run in a headless Chrome with a stand-in
microphone, recorder and `/wall/say` (the page's script is what's under test). Skipped where
Chrome isn't installed."""

from __future__ import annotations

import json
import re

import pytest

from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.integration.test_wall_list_views import get
from tests.integration.test_wall_screen import screen, wall
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

# A microphone, recorder and fetch that only say what was asked of them.
STAND_INS = """
window.__said = [];
window.__answer = null;
navigator.mediaDevices.getUserMedia = function () {
  return Promise.resolve({ getTracks: function () { return [{ stop: function () {} }]; } });
};
window.MediaRecorder = function () { this.mimeType = "audio/webm"; };
window.MediaRecorder.prototype.start = function () {};
window.MediaRecorder.prototype.stop = function () {
  var self = this;
  setTimeout(function () {
    self.ondataavailable({ data: new Blob(["clip"], { type: "audio/webm" }) });
    self.onstop();
  }, 0);
};
var realFetch = window.fetch.bind(window);
window.fetch = function (url, options) {
  if (String(url).indexOf("/wall/say") < 0) return realFetch(url, options);
  window.__said.push(String(url));
  return new Promise(function (resolve) { window.__answer = resolve; });
};
"""


async def sheet_in_chrome(wall: Scenario, tab: Tab) -> None:
    husband = wall.member("Husband")
    page = await screen(wall)
    script = re.search(r'<script src="([^"]*wall\.js[^"]*)"', page)
    assert script is not None
    sheet = (await get(wall, f"/wall/talk?member={husband.id}")).text
    await tab.value(
        "document.body.innerHTML = '<div id=\"wall-view\"></div>';"
        f"document.getElementById('wall-view').innerHTML = {json.dumps(sheet)};"
        f"var s = document.createElement('script'); s.src = {json.dumps(script.group(1))};"
        "document.head.appendChild(s); true"
    )
    assert await until(lambda: tab.value(
        "!!document.querySelector('[data-talk-mic]') && "
        "(document.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles: true})), true) && "
        "!document.querySelector('[data-talk-mic]').hidden"
    ))  # fmt: skip


async def status(tab: Tab) -> str:
    return str(await tab.value("document.querySelector('[data-talk-status]').textContent"))


async def test_listening_then_working_then_the_answer(wall: Scenario) -> None:
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", before=STAND_INS) as tab:
        await sheet_in_chrome(wall, tab)
        await tab.value("document.querySelector('[data-talk-mic]').click()")
        assert await until(lambda: tab.value(
            "document.querySelector('[data-talk-mic]').classList.contains('on')"
        ))  # fmt: skip
        said = await status(tab)
        assert said.startswith("Listening… tap Send when you're done · 0:0")
        assert "of 0:30" in said
        assert await tab.value("document.querySelector('.talk-mic-words').textContent") == "Send"
        assert await tab.value("!document.querySelector('[data-talk-cancel]').hidden")
        assert await tab.value("document.querySelector('#wall-talk').disabled")
        assert await until(lambda: tab.value(
            "document.querySelector('[data-talk-status]').textContent.indexOf('0:01') > 0"
        ), seconds=3)  # the count moves  # fmt: skip

        await tab.value("document.querySelector('[data-talk-mic]').click()")  # Send
        assert await until(lambda: tab.value("window.__said.length === 1"))
        assert await status(tab) == "Working it out…"
        assert await tab.value("document.querySelector('[data-talk-mic]').disabled")
        assert await tab.value("document.querySelector('[data-talk-mic]').classList.contains('busy')")
        await tab.value(
            "window.__answer({ ok: true, text: function () {"
            " return Promise.resolve('<p class=\"talk-line\">Heard you</p>'); } }); true"
        )
        assert await until(lambda: tab.value(
            "document.getElementById('wall-view').textContent.indexOf('Heard you') >= 0"
        ))  # fmt: skip


async def test_cancel_throws_the_clip_away(wall: Scenario) -> None:
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", before=STAND_INS) as tab:
        await sheet_in_chrome(wall, tab)
        await tab.value("document.querySelector('[data-talk-mic]').click()")
        assert await until(lambda: tab.value(
            "document.querySelector('[data-talk-mic]').classList.contains('on')"
        ))  # fmt: skip
        await tab.value("document.querySelector('[data-talk-cancel]').click()")
        assert await until(lambda: tab.value(
            "!document.querySelector('[data-talk-mic]').classList.contains('on')"
        ))  # fmt: skip
        assert await tab.value("window.__said.length") == 0
        assert await status(tab) == ""
        assert await tab.value("document.querySelector('[data-talk-cancel]').hidden")


async def test_a_refused_post_says_it_didnt_catch_it(wall: Scenario) -> None:
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", before=STAND_INS) as tab:
        await sheet_in_chrome(wall, tab)
        await tab.value("document.querySelector('[data-talk-mic]').click()")
        assert await until(lambda: tab.value(
            "document.querySelector('[data-talk-mic]').classList.contains('on')"
        ))  # fmt: skip
        await tab.value("document.querySelector('[data-talk-mic]').click()")
        assert await until(lambda: tab.value("window.__said.length === 1"))
        await tab.value("window.__answer({ ok: false, status: 500 }); true")
        assert await until(lambda: tab.value(
            "document.querySelector('[data-talk-status]').textContent"
            ".indexOf('catch that') >= 0"
        ))  # fmt: skip
        assert not await tab.value("document.querySelector('[data-talk-mic]').disabled")
