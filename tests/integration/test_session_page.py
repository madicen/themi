"""BD3a: the session page: who may see it, the Mini App sign-in, and its state per mode.
The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json
import re
from urllib.parse import urlencode

import httpx
import pytest

from tests.fakes.telegram_api import BOT_TOKEN
from tests.fixtures.web import csrf_of, sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.channels.mini_app import sign_init_data
from themi.core import keys
from themi.web.auth import COOKIE_NAME
from themi_home.body_double import GUIDED, SILENT, SPRINT, BodyDouble, BodyDoublePreferences

ENERGY_WORDS = ("energy", "capacity", "score", "low", "medium", "high")


def bd(scenario: Scenario) -> BodyDouble:
    assert scenario.app.services.maybe(keys.body_double) is not None
    return scenario.app.services.get(keys.body_double)


def init_data(user_id: int, *, token: str = BOT_TOKEN, ago: int = 0) -> str:
    fields = {"auth_date": str(int(clock.now().timestamp()) - ago),
              "user": json.dumps({"id": user_id, "first_name": "Erin"})}  # fmt: skip
    fields["hash"] = sign_init_data(fields, token)
    return urlencode(fields)


async def test_signed_out_it_signs_in_with_the_mini_apps_init_data(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    page = await site.get("/session")
    assert page.status_code == 200 and "Opening your session" in page.text
    assert "frame-ancestors https://web.telegram.org" in page.headers["content-security-policy"]
    assert "img-src 'self' data: blob:;" in page.headers["content-security-policy"]  # BD4b
    other = await site.get("/signed-out")
    assert "blob:" not in other.headers["content-security-policy"]  # only the session page
    assert "x-frame-options" not in page.headers
    erin = scenario.member("Erin")
    assert erin.telegram_user_id is not None
    signed = await site.post(
        "/session/telegram", data={"init_data": init_data(erin.telegram_user_id)}
    )
    assert signed.status_code == 200 and COOKIE_NAME not in signed.cookies
    page = await site.get(f"/session?ticket={signed.json()['ticket']}")
    assert "No session going on" in page.text
    assert COOKIE_NAME in page.cookies  # kept too, where the browser keeps cookies


async def test_bad_init_data_is_403(scenario: Scenario, site: httpx.AsyncClient) -> None:
    erin = scenario.member("Erin")
    assert erin.telegram_user_id is not None
    for data in (
        init_data(erin.telegram_user_id, ago=120),  # stale
        init_data(erin.telegram_user_id, token="1:forged"),  # forged
        init_data(987654321),  # nobody in the family
        "",
    ):
        response = await site.post("/session/telegram", data={"init_data": data})
        assert response.status_code == 403, data
    assert (await site.get("/session/state")).status_code == 303  # still signed out


async def test_the_state_per_mode(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Erin")
    erin = scenario.member("Erin")
    assert (await site.get("/session/state")).json()["active"] is False
    await bd(scenario).start(erin, mode=SILENT, minutes=60, label="my writing")
    state = (await site.get("/session/state")).json()
    assert (state["mode"], state["label"], state["phase"]) == ("silent", "my writing", "work")
    assert state["timer"] == {"kind": "up", "from": "2026-10-21T16:00:00+00:00", "text": "0:00"}
    assert state["line"] == "Quiet until 10 am."
    assert [b["label"] for b in state["buttons"]] == ["Done", "Not finished"]
    await bd(scenario).start(erin, mode=SPRINT, label="the inbox")
    state = (await site.get("/session/state")).json()
    assert state["timer"] == {"kind": "down", "to": "2026-10-21T16:25:00+00:00", "text": "25:00"}
    assert [b["label"] for b in state["buttons"]] == ["Break", "Stop here"]
    board = scenario.app.services.maybe(keys.taskboard)
    assert board is not None
    task = await board.create(erin, "Clean the kitchen", "physical", 3)
    await board.update(task.id, erin, steps=["Clear the counter", "Sweep"])
    await bd(scenario).start(erin, mode=GUIDED, task=task)
    state = (await site.get("/session/state")).json()
    assert (state["step"], state["of"]) == (1, 2)
    assert state["line"] == "Clear the counter"
    assert [b["label"] for b in state["buttons"]] == ["Next", "Done"]
    text = json.dumps(state).lower()
    assert "energy_level" not in text and not any(f'"{w}"' in text for w in ENERGY_WORDS)


async def test_someone_elses_session_is_404(scenario: Scenario, site: httpx.AsyncClient) -> None:
    session, _, _ = await bd(scenario).start(scenario.member("Husband"), mode=SILENT)
    await sign_in(scenario, site, "Erin")
    page = await site.get("/session")
    assert "No session going on" in page.text  # only ever their own
    csrf = csrf_of((await site.get("/settings")).text)
    response = await site.post(
        f"/session/{session.id}/act", data={"csrf": csrf, "action": "done", "seq": session.seq}
    )
    assert response.status_code == 404
    assert bd(scenario).current(scenario.member("Husband")) is not None


async def test_a_page_tap_with_an_old_seq_does_nothing(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    session, _, _ = await bd(scenario).start(scenario.member("Erin"), mode=SPRINT)
    page = await site.get("/session")
    csrf = csrf_of(page.text)
    state = (
        await site.post(
            f"/session/{session.id}/act",
            headers={"X-Requested-With": "fetch"},
            data={"csrf": csrf, "action": "stop", "seq": session.seq - 1},
        )
    ).json()
    assert state["active"] is True


# ----- BD5a: built-in music -------------------------------------------------------------------


async def test_the_sound_is_theirs_and_kept(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    erin = scenario.member("Erin")
    prefs = scenario.app.store.preferences(erin.id, BodyDoublePreferences)
    assert (prefs.body_double_sound, prefs.body_double_volume) == ("lofi", 50)
    await bd(scenario).start(erin, mode=SILENT)
    page = (await site.get("/session")).text
    assert 'class="session-music"' in page and "autoplay" not in page
    assert '<audio loop preload="none" src="/static/home/audio/lofi.m4a?v=' in page
    saved = await site.post("/session/music", data={"csrf": csrf, "sound": "rain", "volume": "30"})
    assert saved.status_code == 204
    music = (await site.get("/session/state")).json()["music"]
    assert (music["sound"], music["volume"], music["file"]) == ("rain", 30, "rain.m4a")
    bad = await site.post("/session/music", data={"csrf": csrf, "sound": "loud", "volume": ""})
    assert bad.status_code == 400
    bad = await site.post("/session/music", data={"csrf": csrf, "sound": "", "volume": "101"})
    assert bad.status_code == 400
    assert sound(scenario) == "rain"
    audio = await site.get("/static/home/audio/rain.m4a")  # CR17b: the home pack's
    assert audio.status_code == 200 and len(audio.content) > 10_000


async def test_play_rain_in_chat_sets_the_page(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("choose_session_sound", {"sound": "rain"})
    scenario.primary.queue_text("Rain it is; tap play on the session page.")
    await scenario.say("Erin", "play rain")
    assert sound(scenario) == "rain"


async def test_the_mini_app_works_when_the_webview_drops_cookies(scenario: Scenario) -> None:
    """Bug (2026-11-07, Michael on the Pi): Telegram's in-app browser didn't send the session
    cookie back, so after signing in the page showed "Opening your session..." again. The
    page now signs in by a one-time ticket in its address and carries the session in a
    header, so nothing depends on the cookie."""
    from tests.fixtures.web import web_client

    erin = scenario.member("Erin")
    assert erin.telegram_user_id is not None
    await bd(scenario).start(erin, mode=SILENT, minutes=30)
    async with web_client(scenario) as site:
        signed = await site.post("/session/telegram",
                                 data={"init_data": init_data(erin.telegram_user_id)})  # fmt: skip
        assert signed.status_code == 200
        ticket = signed.json()["ticket"]
        site.cookies.clear()  # the webview keeps nothing
        page = await site.get(f"/session?ticket={ticket}")
        assert "Quiet company" in page.text and "Opening your session" not in page.text
        token = re.search(r'data-session="([^"]+)"', page.text)
        assert token is not None
        site.cookies.clear()
        state = await site.get("/session/state", headers={"X-Themi-Session": token.group(1)})
        assert state.status_code == 200 and state.json()["active"] is True
        again = await site.get(f"/session?ticket={ticket}")  # a ticket works once
        assert "Opening your session" in again.text


async def test_the_page_reports_its_own_problems_to_the_log(
    scenario: Scenario, site: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await sign_in(scenario, site, "Erin")
    answer = await site.post("/session/report", content=b"tap 3/act answered 403" + b"x" * 900)
    assert answer.status_code == 204
    (record,) = [r for r in caplog.records if r.name == "themi_home.web.session_pages"]
    assert "member 1" in record.getMessage() and "tap 3/act answered 403" in record.getMessage()
    assert len(record.getMessage()) < 700  # short text only


async def test_a_refused_page_tap_says_why_in_the_log(
    scenario: Scenario, site: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="themi_home.body_double")
    csrf = await sign_in(scenario, site, "Erin")
    session, _, _ = await bd(scenario).start(scenario.member("Erin"), mode=SPRINT)
    await site.post(f"/session/{session.id}/act",
                    data={"csrf": csrf, "action": "stop", "seq": session.seq + 5})  # fmt: skip
    assert any("refused: seq" in r.getMessage() for r in caplog.records)


async def test_a_tap_works_beside_an_older_website_cookie(scenario: Scenario) -> None:
    """Bug (2026-11-07, Michael on iPhone and Telegram Web): the in-app browser still held a
    cookie from an earlier /site sign-in. The page's taps carried its own session in the
    header and its own CSRF token, but the server took the old cookie's session, so every tap
    failed the CSRF check, while the page's reads, needing none, kept working."""
    from tests.fixtures.web import web_client

    erin = scenario.member("Erin")
    assert erin.telegram_user_id is not None
    session, _, _ = await bd(scenario).start(erin, mode=SPRINT)
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Erin")  # the older website cookie
        signed = await site.post("/session/telegram",
                                 data={"init_data": init_data(erin.telegram_user_id)})  # fmt: skip
        page = await site.get(f"/session?ticket={signed.json()['ticket']}")
        token = re.search(r'data-session="([^"]+)"', page.text)
        assert token is not None
        csrf = csrf_of(page.text)
        await sign_in(scenario, site, "Erin")  # the old cookie comes back, as in the webview
        tapped = await site.post(
            f"/session/{session.id}/act",
            headers={"X-Themi-Session": token.group(1), "X-Requested-With": "fetch"},
            data={"csrf": csrf, "action": "break", "seq": session.seq},
        )
        assert tapped.status_code == 200 and tapped.json()["phase"] == "break"


def sound(scenario: Scenario) -> str:
    erin = scenario.member("Erin")
    return scenario.app.store.preferences(erin.id, BodyDoublePreferences).body_double_sound
