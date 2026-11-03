"""D3a: Michael's ask (2026-11-02): update the server from the website instead of ssh. An
admin presses Update on the Development page, the host's runner does it, and whoever asked
hears how it went, once."""

from __future__ import annotations

import httpx

from tests.fakes.server_runner import FakeRunner
from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario


async def test_an_update_from_the_website_says_when_it_is_done(
    scenario: Scenario, fake_runner: FakeRunner, site: httpx.AsyncClient
) -> None:
    fake_runner.install(newest="1.5.0")
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/dev/server/update", data={"csrf": csrf})
    assert "Asked the server to update" in await flash(site, "/dev")

    request = fake_runner.pick_up()
    await scenario.run_periodic("server.results")
    assert "under way" in (await site.get("/dev")).text

    # Themi stops and starts on 1.5.0; the runner writes how it went.
    fake_runner.finish(request["id"], "done", "1.4.0", "1.5.0")
    await scenario.run_periodic("server.results")
    await scenario.run_periodic("server.results")
    await scenario.advance(minutes=1)
    assert scenario.inbox("Erin").count("Themi is now on 1.5.0 (was 1.4.0).") == 1
    assert not any("1.5.0" in t for t in scenario.inbox("Husband"))
    page = (await site.get("/dev")).text
    assert "1.4.0 → 1.5.0" in page and 'action="/dev/server/update"' in page
