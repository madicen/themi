"""The session page's own script, run in a real (headless) Chrome: a tap on [Go] moves the
session. Bug 2026-11-07: every other test posted to the server directly, so none ran the
script, and a tap posted to "[object HTMLInputElement]" (each form's hidden input named
"action" shadows `form.action`) without anyone noticing. Skipped where Chrome isn't
installed."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from typing import Any

import pytest
import uvicorn
import websockets

from tests.fixtures.web import web_client
from tests.integration.test_session_page import init_data
from tests.scenarios.harness import Scenario
from themi import clock
from themi.web import HealthSources, create_app
from themi.web.kit import SiteContext

CHROME = shutil.which("google-chrome") or shutil.which("chromium")
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Tab:
    """Just enough of the Chrome DevTools protocol to load a page and run a line in it."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.n = 0

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == self.n:
                return message

    async def value(self, expression: str) -> Any:
        answer = await self.call("Runtime.evaluate", expression=expression)
        return answer["result"]["result"].get("value")


async def until(check: Any, seconds: float = 8) -> Any:
    for _ in range(int(seconds * 10)):
        if found := await check():
            return found
        await asyncio.sleep(0.1)
    return None


async def test_go_on_the_page_moves_the_session(scenario: Scenario) -> None:
    assert CHROME is not None
    clock.unfreeze()  # the browser keeps real time
    erin = scenario.member("Erin")
    assert erin.telegram_user_id is not None
    scenario.primary.queue_tool_call(
        "start_body_double", {"mode": "steps", "minutes": 0, "task_id": 0, "what": "the bathroom"}
    )
    scenario.primary.queue_structured(
        {"steps": [{"text": "Spray the shower", "optional": False},
                   {"text": "Mop the floor", "optional": False}]}
    )  # fmt: skip
    await scenario.say("Erin", "walk me through the bathroom")
    port = free_port()
    web = create_app(
        HealthSources(scenario.app.db, None, clock.now()),
        SiteContext(scenario.app, base_url=f"http://127.0.0.1:{port}", secure_cookies=False),
    )
    server = uvicorn.Server(
        uvicorn.Config(web, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    serving = asyncio.create_task(server.serve())
    debug = free_port()
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={debug}",
         f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        assert await until(lambda: asyncio.sleep(0, server.started))
        async with web_client(scenario) as site:
            signed = await site.post(
                "/session/telegram", data={"init_data": init_data(erin.telegram_user_id)}
            )
        ticket = signed.json()["ticket"]

        async def targets() -> list[dict[str, Any]] | None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{debug}/json") as answer:
                    return [t for t in json.loads(answer.read()) if t["type"] == "page"]
            except OSError:
                return None

        pages = await until(targets)
        assert pages
        async with websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.navigate", url=f"http://127.0.0.1:{port}/session?ticket={ticket}")
            line = "document.querySelector('.session-line') && " \
                   "document.querySelector('.session-line').textContent"  # fmt: skip
            assert (await until(lambda: tab.value(line))).startswith("Here's how I'd break it up")
            await tab.value("document.querySelector('.session-moves button').click()")
            moved = await until(
                lambda: tab.value(f"({line}) === 'Spray the shower' ? 'moved' : ''")
            )
            assert moved == "moved"
        row = scenario.app.db.one("SELECT phase, step FROM body_double_sessions ORDER BY id DESC")
        assert row is not None and (row["phase"], row["step"]) == ("work", 0)
    finally:
        chrome.kill()
        server.should_exit = True
        await serving
