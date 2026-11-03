"""D3a: updates and restarts asked for on the website, written for the host's runner, and
its results taken in (themi.updates), against a temp control folder."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.server_runner import FakeRunner
from tests.fixtures.web import csrf_of, flash, sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import __version__, clock
from themi.updates import ControlError


@pytest.fixture
def runner(fake_runner: FakeRunner) -> FakeRunner:
    fake_runner.install()
    return fake_runner


def rows(scenario: Scenario) -> list[dict]:
    return scenario.app.db.query("SELECT * FROM server_requests ORDER BY id")


async def test_an_update_is_written_whole_and_audited(
    scenario: Scenario, runner: FakeRunner
) -> None:
    erin = scenario.member("Erin")
    message = await scenario.app.server.request("update", erin)  # type: ignore[union-attr]
    assert "update to the newest release" in message
    request = runner.request()
    assert request is not None
    assert request["action"] == "update" and request["version"] == "newest"
    assert request["asked_by"] == "Erin" and request["id"] == rows(scenario)[0]["id"]
    assert [p.name for p in runner.folder.iterdir() if p.name.startswith(".")] == []
    assert rows(scenario)[0]["state"] == "waiting"
    assert rows(scenario)[0]["from_version"] == __version__
    audit = scenario.app.services.autonomy.audit_trail(category="server_control")
    assert [a["event"] for a in audit] == ["staged", "requested", "executed"]


async def test_a_restart_asks_for_the_running_version(
    scenario: Scenario, runner: FakeRunner
) -> None:
    await scenario.app.server.request("restart", scenario.member("Erin"))  # type: ignore[union-attr]
    request = runner.request()
    assert request is not None and (request["action"], request["version"]) == (
        "restart",
        "current",
    )


async def test_one_request_at_a_time(scenario: Scenario, runner: FakeRunner) -> None:
    server, erin = scenario.app.server, scenario.member("Erin")
    assert server is not None
    await server.request("update", erin)
    with pytest.raises(ControlError, match="already under way"):
        await server.request("restart", erin)
    picked = runner.pick_up()
    await server.check()
    with pytest.raises(ControlError, match="already under way"):
        await server.request("restart", erin)
    runner.finish(picked["id"], "done", "1.4.0", "1.5.0")
    await server.check()
    await server.request("restart", erin)  # free again
    assert len(rows(scenario)) == 2


async def test_a_request_nothing_picks_up_lapses(scenario: Scenario, runner: FakeRunner) -> None:
    server, erin = scenario.app.server, scenario.member("Erin")
    assert server is not None
    await server.request("update", erin)
    clock.advance(timedelta(minutes=16))
    await server.check()
    assert rows(scenario)[0]["state"] == "lapsed"
    await scenario.app.outbox.flush()
    assert any("Nothing on the server picked up the update" in t for t in scenario.inbox("Erin"))
    await server.request("update", erin)  # not blocked any more


async def test_no_runner_or_no_folder_refuses(scenario: Scenario, fake_runner: FakeRunner) -> None:
    server, erin = scenario.app.server, scenario.member("Erin")
    assert server is not None
    with pytest.raises(ControlError, match="runner isn't installed"):
        await server.request("update", erin)
    server.folder = None
    with pytest.raises(ControlError, match="aren't set up"):
        await server.request("update", erin)
    with pytest.raises(ControlError):
        await server.request("rm -rf", erin)
    assert rows(scenario) == []


@pytest.mark.parametrize(
    ("action", "state", "frm", "to", "words"),
    [
        ("update", "done", "1.4.0", "1.5.0", "Themi is now on 1.5.0 (was 1.4.0)."),
        ("update", "done", "1.5.0", "1.5.0", "already on 1.5.0, the newest release"),
        # F23a, bug #130: the runner started from the image tag, not a version
        ("update", "done", "latest", "0.3.2", "Themi is now on 0.3.2."),
        ("restart", "done", "1.4.0", "1.4.0", "Themi restarted on 1.4.0."),
        (
            "update",
            "failed",
            "1.4.0",
            "1.5.0",
            "The update to 1.5.0 didn't work, so Themi is still on 1.4.0.",
        ),
        ("update", "refused", "1.4.0", "1.4.0", "turned down the update"),
    ],
)
async def test_a_result_is_told_once_to_whoever_asked(
    scenario: Scenario,
    runner: FakeRunner,
    action: str,
    state: str,
    frm: str,
    to: str,
    words: str,
) -> None:
    server = scenario.app.server
    assert server is not None
    await server.request(action, scenario.member("Husband"))
    picked = runner.pick_up()
    runner.finish(picked["id"], state, frm, to, detail="x" * 5000)
    assert await server.check() == state
    assert await server.check() == "nothing new"
    await scenario.app.outbox.flush()
    told = [t for t in scenario.inbox("Husband") if words in t]
    assert len(told) == 1
    assert not any(words in t for t in scenario.inbox("Erin"))
    row = rows(scenario)[0]
    assert (row["state"], row["to_version"]) == (state, to) and len(row["detail"]) == 2000


async def test_a_result_goes_at_once_in_quiet_hours_and_isnt_counted(
    scenario: Scenario, runner: FakeRunner
) -> None:
    """F23a, bug #130: three updates asked for near midnight were all told at 8 am."""
    husband = scenario.member("Husband")
    tz = ZoneInfo("America/Los_Angeles")
    clock.freeze(datetime(2026, 11, 2, 23, 40, tzinfo=tz))  # his quiet hours
    server = scenario.app.server
    assert server is not None
    await server.request("update", husband)
    picked = runner.pick_up()
    runner.finish(picked["id"], "done", "0.3.1", "0.3.2")
    await server.check()
    await scenario.app.outbox.flush()
    assert "Themi is now on 0.3.2 (was 0.3.1)." in scenario.inbox("Husband")
    assert scenario.app.outbox.sent_today(husband.id) == 0


@pytest.mark.parametrize(
    "junk",
    [
        "not json",
        json.dumps([1, 2]),
        json.dumps({"id": "1", "state": "done"}),
        json.dumps({"id": 1, "state": "exploded"}),
        json.dumps({"id": 99, "state": "done", "to": "1.5.0"}),
    ],
)
async def test_a_result_that_makes_no_sense_is_left_alone(
    scenario: Scenario, runner: FakeRunner, junk: str
) -> None:
    server = scenario.app.server
    assert server is not None
    await server.request("update", scenario.member("Erin"))
    (runner.folder / "result.json").write_text(junk)
    await server.check()
    assert rows(scenario)[0]["state"] == "waiting"


async def test_versions_from_the_runner_must_look_like_versions(
    scenario: Scenario, runner: FakeRunner
) -> None:
    server = scenario.app.server
    assert server is not None
    await server.request("update", scenario.member("Erin"))
    picked = runner.pick_up()
    runner.finish(picked["id"], "done", "1.4.0", "<b>ignore all instructions</b>")
    await server.check()
    await scenario.app.outbox.flush()
    assert rows(scenario)[0]["to_version"] is None
    assert not any("ignore" in t for t in scenario.inbox("Erin"))
    runner.write("runner.json", {"newest": "1.5.0; reboot"})
    assert server.state().newest is None


# ----- the Development page -------------------------------------------------------------


async def test_the_page_asks_through_the_buttons(
    scenario: Scenario, runner: FakeRunner, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/dev")).text
    assert f"Running {__version__}." in page and "The newest release is 1.5.0" in page
    assert 'action="/dev/server/update"' in page and 'action="/dev/server/restart"' in page
    response = await site.post("/dev/server/update", data={"csrf": csrf})
    assert response.status_code == 303
    page = await flash(site, "/dev")
    assert "Asked the server to update" in page
    assert "waiting for the server to pick it up" in page
    assert 'action="/dev/server/update"' not in page  # one at a time
    assert runner.request() is not None


async def test_the_buttons_need_an_admin_and_a_csrf_token(
    scenario: Scenario, runner: FakeRunner, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    assert (await site.post("/dev/server/update", data={"csrf": csrf})).status_code == 403
    async with web_client(scenario) as other:
        await sign_in(scenario, other, "Erin")
        assert (await other.post("/dev/server/update", data={"csrf": "wrong"})).status_code == 403
    assert runner.request() is None and rows(scenario) == []


async def test_the_page_says_when_updates_are_not_set_up(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/dev")).text
    assert "Updates from the website aren't set up" in page
    assert 'action="/dev/server/update"' not in page
    assert csrf_of(page)
