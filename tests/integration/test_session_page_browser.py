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
        "start_body_double",
        {"mode": "steps", "minutes": 0, "task_id": 0, "what": "the bathroom", "then": []},
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
    errors = tempfile.TemporaryFile()  # noqa: SIM115 - closed in the finally below
    # --no-sandbox: CI runners (Ubuntu 24.04) block the user namespaces Chrome's sandbox
    # needs, so it exited at once there; this Chrome only ever loads our own local page.
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
         f"--remote-debugging-port={debug}", f"--user-data-dir={tempfile.mkdtemp()}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=errors,
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

        pages = await until(targets, seconds=30)
        if not pages:  # Chrome couldn't start here: that's the machine, not the page
            errors.seek(0)
            said = errors.read().decode(errors="replace").strip().splitlines()[-3:]
            pytest.skip(f"Chrome didn't start (exit {chrome.poll()}): {' | '.join(said)}")
        async with websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.navigate", url=f"http://127.0.0.1:{port}/session?ticket={ticket}")
            line = "document.querySelector('.session-line') && " \
                   "document.querySelector('.session-line').textContent"  # fmt: skip
            assert (await until(lambda: tab.value(line))).startswith("Here's how I'd break it up")
            # The line is in the server's HTML, but session.js is deferred: a tap before it ran
            # was a plain form post that left the page (flaky on a busy CI runner, 2026-11-07).
            # "complete" comes after deferred scripts have run.
            assert await until(lambda: tab.value("document.readyState === 'complete'"))
            await tab.value("document.querySelector('.session-moves button').click()")
            moved = await until(
                lambda: tab.value(f"({line}) === 'Spray the shower' ? 'moved' : ''")
            )
            assert moved == "moved"
            # BD4b, bug 2026-11-07: the picture was made but never showed. The page loads it
            # with its session header into a blob: address, which the CSP refused.
            await scenario.run_jobs()  # the step pictures (the scripted model's PNG)
            shown = await until(lambda: tab.value(
                "(() => { const i = document.querySelector('.session-picture img');"
                " return !!i && !i.hidden && i.complete && i.naturalWidth > 0; })()"
            ))  # fmt: skip
            assert shown, "the step's picture never loaded on the page"
        row = scenario.app.db.one("SELECT phase, step FROM body_double_sessions ORDER BY id DESC")
        assert row is not None and (row["phase"], row["step"]) == ("work", 0)
    finally:
        chrome.kill()
        errors.close()
        server.should_exit = True
        await serving
