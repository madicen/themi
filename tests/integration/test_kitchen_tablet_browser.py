"""CK11: the kitchen tablet in a real (headless) Chrome: the cook screen's [Full screen]
button with the Fullscreen API faked (headless Chrome needs a real tap for the real one), the
same button in Telegram through CK10's bridge, and /session signed out in a plain browser.
Skipped where Chrome isn't installed."""

from __future__ import annotations

import json

import pytest

from tests.integration.test_cook_miniapp_browser import FAKE_TELEGRAM, SENT, telegram
from tests.integration.test_cook_screen_browser import to_step_three
from tests.integration.test_session_page_browser import CHROME, page_in_chrome, until
from tests.scenarios.harness import Scenario
from themi import clock

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")

FAKE_FULLSCREEN = """(() => {
  let shown = null;
  const has = (name, get) =>
    Object.defineProperty(Document.prototype, name, {get, configurable: true});
  has("fullscreenEnabled", () => true);
  has("fullscreenElement", () => shown);
  has("webkitFullscreenEnabled", () => undefined);
  has("webkitFullscreenElement", () => undefined);
  const changed = () => document.dispatchEvent(new Event("fullscreenchange"));
  Element.prototype.requestFullscreen = function () {
    shown = this; changed(); return Promise.resolve();
  };
  Document.prototype.exitFullscreen = function () {
    shown = null; changed(); return Promise.resolve();
  };
})();"""
NO_FULLSCREEN = """for (const name of ["fullscreenEnabled", "webkitFullscreenEnabled"])
  Object.defineProperty(Document.prototype, name, {get: () => false, configurable: true});"""
BUTTON = "document.querySelector('.cook-fullscreen')"


async def test_full_screen_where_the_browser_offers_it(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(scenario, erin, ".cook-moves", before=FAKE_FULLSCREEN) as tab:
        assert await tab.value(f"!{BUTTON}.hidden && {BUTTON}.textContent") == "Full screen"
        await tab.value(f"{BUTTON}.click()")
        assert await until(lambda: tab.value(f"{BUTTON}.textContent === 'Exit full screen'"))
        assert await tab.value("document.fullscreenElement === document.documentElement")
        assert await tab.value(f"{BUTTON}.getAttribute('aria-pressed')") == "true"
        await tab.value("window.themiCook.view()")  # a redraw keeps it right
        assert await until(lambda: tab.value(f"{BUTTON}.textContent === 'Exit full screen'"))
        await tab.value(f"{BUTTON}.click()")
        assert await until(lambda: tab.value(f"{BUTTON}.textContent === 'Full screen'"))
        assert await tab.value("document.fullscreenElement") is None
        manifest = "document.querySelector('link[rel=manifest]').getAttribute('href')"
        assert await tab.value(manifest) == "/session/manifest.webmanifest"


async def test_no_button_where_the_browser_has_no_full_screen(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(scenario, erin, ".cook-moves", before=NO_FULLSCREEN) as tab:
        assert await tab.value(f"{BUTTON}.hidden")


async def test_in_telegram_the_button_asks_telegram(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    erin = scenario.member("Erin")
    async with page_in_chrome(
        scenario, erin, ".cook-moves", before=FAKE_TELEGRAM, hash=telegram("8.0")
    ) as tab:
        assert not await tab.value(f"{BUTTON}.hidden")
        await tab.value(
            "Telegram.WebView.receiveEvent('fullscreen_changed', {is_fullscreen: true})"
        )
        assert await until(lambda: tab.value(f"{BUTTON}.textContent === 'Exit full screen'"))
        await tab.value(f"{BUTTON}.click()")
        names = [name for name, _ in json.loads(await tab.value(SENT))]
        assert names[-1] == "web_app_exit_fullscreen"


async def test_signed_out_in_a_plain_browser_it_says_how_to_sign_in(scenario: Scenario) -> None:
    clock.unfreeze()
    erin = scenario.member("Erin")
    async with page_in_chrome(scenario, erin, ".session") as tab:
        await tab.call("Network.clearBrowserCookies")
        address = await tab.value("location.origin + '/session'")
        await tab.call("Page.navigate", url=address)
        shown = "(document.getElementById('sign-in-help') || {hidden: true}).hidden === false"
        assert await until(lambda: tab.value(shown))
        assert await tab.value("document.getElementById('signing-in').hidden")
        assert await tab.value("!!document.querySelector('#sign-in-help a[href=\"/signed-out\"]')")
