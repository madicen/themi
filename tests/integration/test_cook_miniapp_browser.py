"""CK10: full screen in Telegram, in a real (headless) Chrome with Telegram faked: the page's
bridge (miniapp.js) speaks Telegram's Mini App events itself, and the fake records them.
Skipped where Chrome isn't installed."""

from __future__ import annotations

import json

import pytest

from tests.integration.test_cook_screen_browser import to_step_three
from tests.integration.test_session_page_browser import CHROME, Tab, page_in_chrome, until
from tests.scenarios.harness import Scenario
from themi import clock

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

FAKE_TELEGRAM = (
    "window.sent = [];"
    "window.TelegramWebviewProxy = { postEvent: function (type, data) {"
    " window.sent.push([type, JSON.parse(data)]); } };"
)
SENT = "JSON.stringify(window.sent)"


def telegram(version: str) -> str:
    return f"tgWebAppPlatform=ios&tgWebAppVersion={version}"


async def sent(tab: Tab) -> list[list[object]]:
    return json.loads(await tab.value(SENT))


async def test_the_cook_screen_asks_telegram_for_full_screen(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(
        scenario, erin, ".cook-moves", before=FAKE_TELEGRAM, hash=telegram("8.0")
    ) as tab:
        events = await sent(tab)
        names = [name for name, _ in events]
        assert names[:2] == ["web_app_ready", "web_app_expand"]
        assert ["web_app_setup_swipe_behavior", {"allow_vertical_swipe": False}] in events
        assert "web_app_request_fullscreen" in names
        assert "web_app_request_content_safe_area" in names
        assert await tab.value("document.documentElement.classList.contains('in-telegram')")

        # Telegram answers: full screen, its buttons floating 46 px down under a 20 px notch
        await tab.value(
            "const tg = Telegram.WebView, none = {bottom: 0, left: 0, right: 0};"
            "tg.receiveEvent('fullscreen_changed', {is_fullscreen: true});"
            "tg.receiveEvent('safe_area_changed', {...none, top: 20});"
            "tg.receiveEvent('content_safe_area_changed', {...none, top: 46})"
        )  # fmt: skip
        padding = "getComputedStyle(document.querySelector('.cook')).paddingTop"
        assert await until(lambda: tab.value(f"{padding} === '66px'"))
        assert await tab.value("document.documentElement.classList.contains('tg-fullscreen')")
        assert await tab.value("window.themiMiniApp.isFullscreen()")


async def test_an_older_telegram_only_expands(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(
        scenario, erin, ".cook-moves", before=FAKE_TELEGRAM, hash=telegram("7.0")
    ) as tab:
        assert [name for name, _ in await sent(tab)] == ["web_app_ready", "web_app_expand"]
        assert await tab.value("window.themiMiniApp.canFullscreen") is False


async def test_the_body_double_page_only_expands(scenario: Scenario) -> None:
    clock.unfreeze()
    scenario.primary.queue_tool_call(
        "start_body_double",
        {"mode": "steps", "minutes": 0, "task_id": 0, "what": "the bathroom", "then": []},
    )
    scenario.primary.queue_structured(
        {"steps": [{"text": "Spray the shower", "optional": False},
                   {"text": "Mop the floor", "optional": False}]}
    )  # fmt: skip
    await scenario.say("Erin", "walk me through the bathroom")
    erin = scenario.member("Erin")
    async with page_in_chrome(scenario, erin, before=FAKE_TELEGRAM, hash=telegram("8.0")) as tab:
        assert [name for name, _ in await sent(tab)] == ["web_app_ready", "web_app_expand"]


async def test_outside_telegram_nothing_is_sent(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    spy = "window.posted = 0; window.parent.postMessage = function () { window.posted++; };"
    async with page_in_chrome(scenario, erin, ".cook-moves", before=spy) as tab:
        assert await tab.value("window.themiMiniApp.inTelegram") is False
        assert await tab.value("window.posted") == 0
        assert await tab.value("typeof window.Telegram") == "undefined"
        assert not await tab.value("document.documentElement.classList.contains('in-telegram')")


# ----- F40c, idea #193: a Mini App opens in the phone's browser ---------------------------

SHOWN = "getComputedStyle(document.querySelector('.open-in-browser')).display !== 'none'"


async def opened_link(tab: Tab) -> str:
    await tab.value("document.querySelector('.open-in-browser').click()")
    found = "window.sent.some(function (e) { return e[0] === 'web_app_open_link'; })"
    assert await until(lambda: tab.value(found))
    return next(data["url"] for name, data in await sent(tab) if name == "web_app_open_link")  # type: ignore[index]


def ticket_of(scenario: Scenario, url: str, origin: str) -> str:
    from urllib.parse import parse_qs, urlparse

    from themi.web.auth import WebAuth

    assert url.startswith(origin + "/session?ticket=")
    ticket = parse_qs(urlparse(url).query)["ticket"][0]
    assert WebAuth(scenario.app.store).link_is_valid(ticket)  # one-time, for the browser
    return ticket


async def test_the_cook_screen_opens_in_the_browser(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(
        scenario, erin, ".cook-moves", before=FAKE_TELEGRAM, hash=telegram("8.0")
    ) as tab:
        assert await tab.value(SHOWN)
        url = await opened_link(tab)
        origin = await tab.value("location.origin")
        ticket = ticket_of(scenario, url, origin)
        from themi.web.auth import WebAuth

        member = WebAuth(scenario.app.store).consume_link(ticket)
        assert member is not None and member.id == erin.id


async def test_the_body_double_page_opens_in_the_browser(scenario: Scenario) -> None:
    clock.unfreeze()
    scenario.primary.queue_tool_call(
        "start_body_double",
        {"mode": "steps", "minutes": 0, "task_id": 0, "what": "the bathroom", "then": []},
    )
    scenario.primary.queue_structured(
        {"steps": [{"text": "Spray the shower", "optional": False},
                   {"text": "Mop the floor", "optional": False}]}
    )  # fmt: skip
    await scenario.say("Erin", "walk me through the bathroom")
    erin = scenario.member("Erin")
    async with page_in_chrome(scenario, erin, before=FAKE_TELEGRAM, hash=telegram("8.0")) as tab:
        assert await tab.value(SHOWN)
        ticket_of(scenario, await opened_link(tab), await tab.value("location.origin"))


async def test_outside_telegram_there_is_no_open_in_browser(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(scenario, erin, ".cook-moves") as tab:
        assert not await tab.value(SHOWN)
