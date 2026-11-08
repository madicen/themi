"""SP5: changing a Themi on the Modules page: switches with what comes and goes with them,
the template, settings checked before they're kept, secrets never sent back, and Test."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx

from tests.fixtures.web import csrf_of, sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.config import parse_config
from themi.modules import Module
from themi.modules.portal import Portal
from themi.modules.store import DraftStore
from themi_google.google_settings import TravelSettings


@asynccontextmanager
async def admin(scenario: Scenario) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        yield client, csrf


def draft(scenario: Scenario):
    return DraftStore(scenario.app.db).get()


async def test_turning_on_shows_what_comes_with_it_then_drafts_them(scenario: Scenario) -> None:
    scenario.app.services.instance_config = parse_config({"template": "empty"})
    async with admin(scenario) as (site, csrf):
        ask = await site.post("/modules/email_triage/switch", data={"csrf": csrf, "to": "on"})
        assert ask.status_code == 200 and "Turn on Email triage?" in ask.text
        assert "Google accounts" in ask.text and "Gmail" in ask.text
        assert draft(scenario) is None  # nothing yet
        done = await site.post(
            "/modules/email_triage/switch", data={"csrf": csrf, "to": "on", "confirmed": "1"}
        )
        assert done.status_code == 303
        page = (await site.get("/modules")).text
    saved = draft(scenario)
    assert saved is not None
    assert saved.modules == {"google": True, "gmail": True, "email_triage": True}
    assert "3 changes wait for a restart." in page
    assert "turned on Google accounts, Gmail, Email triage" in page  # the draft and the audit


async def test_turning_off_lists_what_needs_it(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        ask = await site.post("/modules/google/switch", data={"csrf": csrf, "to": "off"})
        assert "These need Google accounts, so they'll be turned off too" in ask.text
        assert "Email triage" in ask.text and "Gmail" in ask.text
        await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})  # alone
    saved = draft(scenario)
    assert saved is not None and saved.modules == {"safeway": False}


async def test_a_template_switch_lists_everything_first(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        ask = await site.post("/modules/template", data={"csrf": csrf, "template": "work"})
        assert "Change to the work template?" in ask.text
        assert "Family cookbook" in ask.text and "Cooking along" in ask.text
        assert draft(scenario) is None
        await site.post(
            "/modules/template", data={"csrf": csrf, "template": "work", "confirmed": "1"}
        )
    saved = draft(scenario)
    assert saved is not None and saved.template == "work"


async def test_settings_are_checked_and_secrets_kept_out_of_sight(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        bad = await site.post(
            "/modules/ourgroceries/settings", data={"csrf": csrf, "username": "erin@example.com"}
        )
        assert bad.status_code == 400 and "set both or neither" in bad.text
        assert draft(scenario) is None
        ok = await site.post(
            "/modules/web_search/settings",
            data={"csrf": csrf, "tavily_api_key": "tvly-secret-4321", "backend": "tavily"},
        )
        assert ok.status_code == 303
        page = (await site.get("/modules/web_search")).text
    assert "tvly-secret-4321" not in page and "Saved, ends in …4321" in page
    assert "Waiting for restart" in page
    saved = draft(scenario)
    assert saved is not None
    assert saved.sections == {"web_search": {"backend": "tavily"}}
    assert "tvly-secret-4321" not in str(saved.secrets)
    cipher = scenario.app.store.cipher
    secret = saved.secret(cipher, "web_search", "tavily_api_key")
    assert secret is not None and secret.reveal() == "tvly-secret-4321"


async def test_shared_settings_go_to_each_module_that_shares_them(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        await site.post(
            "/modules/cozyla_todos/settings",
            data={"csrf": csrf, "email": "wall@example.com", "password": "pw-1234"},
        )
    saved = draft(scenario)
    assert saved is not None
    assert saved.sections["cozyla_chores"]["email"] == "wall@example.com"
    assert set(saved.secrets) == {"cozyla_todos", "cozyla_chores"}


async def test_a_secret_needs_a_recent_sign_in(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        clock.advance(timedelta(minutes=20))
        response = await site.post(
            "/modules/web_search/settings", data={"csrf": csrf, "tavily_api_key": "tvly-x"}
        )
        assert response.status_code == 303
        assert "sign in again" in (await site.get("/modules/web_search")).text
        assert draft(scenario) is None
        plain = await site.post(
            "/modules/web_search/settings", data={"csrf": csrf, "backend": "firecrawl"}
        )
        assert plain.status_code == 303  # a plain value is fine
        template = await site.post("/modules/template", data={"csrf": csrf, "template": "work"})
        assert "sign in again" in (await site.get(template.headers["location"])).text


class Tried(Module):
    name = "travel"
    problem: str | None = None

    async def check(self) -> str | None:
        return self.problem


async def test_test_tries_the_drafts_settings(scenario: Scenario) -> None:
    portal = scenario.app.services.get(Portal)
    seen: list[object] = []

    def build(cls, setup):
        seen.append(setup.read(TravelSettings).tomtom_api_key)
        module = Tried()
        module.problem = "TomTom turned the key down" if len(seen) > 1 else None
        return module

    portal.builder = build
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/travel/settings", data={"csrf": csrf, "tomtom_api_key": "tt-9"})
        first = await site.post("/modules/travel/test", data={"csrf": csrf})
        assert "Travel times worked." in (await site.get(first.headers["location"])).text
        second = await site.post("/modules/travel/test", data={"csrf": csrf})
        page = (await site.get(second.headers["location"])).text
        assert "Travel times didn&#39;t work: TomTom turned the key down" in page
        assert "tested Travel times" in (await site.get("/modules")).text
    assert [s.reveal() for s in seen] == ["tt-9", "tt-9"]  # type: ignore[attr-defined]


async def test_tests_are_limited_to_a_few_a_minute(scenario: Scenario) -> None:
    scenario.app.services.get(Portal).builder = lambda cls, setup: Tried()
    async with admin(scenario) as (site, csrf):
        for _ in range(5):
            await site.post("/modules/travel/test", data={"csrf": csrf})
        last = await site.post("/modules/travel/test", data={"csrf": csrf})
        assert "a lot of tests in a minute" in (await site.get(last.headers["location"])).text


async def test_undo_drops_the_draft(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})
        assert "1 change waits for a restart." in (await site.get("/")).text
        await site.post("/modules/undo", data={"csrf": csrf})
        home = (await site.get("/")).text
    assert draft(scenario) is None and "pending-bar" not in home


async def test_only_admins_change_anything(scenario: Scenario) -> None:
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Husband")
        csrf = csrf_of((await site.get("/settings")).text)
        response = await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})
        assert response.status_code == 403
        assert "pending-bar" not in (await site.get("/")).text
    assert draft(scenario) is None


async def test_an_admin_turns_travel_on_with_a_key_tests_it_and_sees_it_waiting(
    scenario: Scenario,
) -> None:
    scenario.app.services.instance_config = parse_config({"modules": ["-travel"]})
    scenario.app.services.get(Portal).builder = lambda cls, setup: Tried()
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/travel/switch", data={"csrf": csrf, "to": "on"})
        await site.post("/modules/travel/settings", data={"csrf": csrf, "tomtom_api_key": "tt-1"})
        tested = await site.post("/modules/travel/test", data={"csrf": csrf})
        page = (await site.get(tested.headers["location"])).text
        listing = (await site.get("/modules")).text
    assert "Travel times worked." in page
    card = re.search(r'id="module-travel">(.*?)</li>', listing, re.S)
    assert card and "Waiting for restart" in card.group(1)
