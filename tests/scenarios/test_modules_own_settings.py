"""MP5: every setting a module has, on its own Modules page: the household's, the admin's
own preferences, its pages, and who can use it."""

from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.modules.store import DraftStore
from themi.standard.breaks import BreaksPreferences
from themi_home.spending import SpendingSettings


@asynccontextmanager
async def admin(scenario: Scenario) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        yield client, csrf


async def test_the_takeout_budget_saved_on_spendings_page_shows_on_family(
    scenario: Scenario,
) -> None:
    async with admin(scenario) as (site, csrf):
        page = (await site.get("/modules/spending")).text
        assert "For the household" in page and "Takeout budget ($)" in page
        done = await site.post(
            "/modules/spending/household", data={"csrf": csrf, "takeout_budget_cents": "250.50"}
        )
        assert done.status_code == 303
        family = (await site.get("/family")).text
    assert scenario.app.store.household(SpendingSettings).takeout_budget_cents == 25050
    assert 'value="250.50"' in family


async def test_a_bad_household_value_says_why(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        page = await site.post(
            "/modules/spending/household", data={"csrf": csrf, "takeout_budget_cents": "lots"}
        )
    assert page.status_code == 400 and "isn&#39;t an amount" in page.text


async def test_a_preference_saved_there_is_the_admins_own(scenario: Scenario) -> None:
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    async with admin(scenario) as (site, csrf):
        page = (await site.get("/modules/breaks")).text
        assert "Your settings" in page and 'href="/settings#breaks"' in page
        await site.post(
            "/modules/breaks/preferences", data={"csrf": csrf, "break_extend_minutes": "25"}
        )
        settings = (await site.get("/settings")).text
    store = scenario.app.store
    assert store.preferences(erin.id, BreaksPreferences).break_extend_minutes == 25
    assert store.preferences(husband.id, BreaksPreferences).break_extend_minutes == 15
    assert 'name="break_extend_minutes" min="5" max="120" value="25"' in settings


async def test_a_preference_out_of_range_says_why(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        page = await site.post(
            "/modules/breaks/preferences", data={"csrf": csrf, "break_extend_minutes": "500"}
        )
    assert page.status_code == 400 and "between 5 and 120 minutes" in page.text


async def test_a_modules_own_pages_are_listed(scenario: Scenario) -> None:
    async with admin(scenario) as (site, _):
        page = (await site.get("/modules/recipes")).text
    pages = page.split('id="pages"', 1)[1].split("</ul>", 1)[0]
    assert 'href="/recipes"' in pages


async def test_who_can_use_it_waits_for_the_restart_and_lands_in_themi_toml(
    scenario: Scenario, tmp_path: Path
) -> None:
    scenario.app.services.environment = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    scenario.app.services.restart = lambda: None
    async with admin(scenario) as (site, csrf):
        page = (await site.get("/modules/safeway")).text
        assert 'name="role_member" value="1" checked' in page
        await site.post("/modules/safeway/roles", data={"csrf": csrf, "role_admin": "1"})
        draft = DraftStore(scenario.app.db).get()
        assert draft is not None and draft.roles == {"member": ["*", "-safeway"]}
        after = (await site.get("/modules/safeway")).text
        assert 'name="role_member" value="1">' in after and "Waiting for restart" in after
        await site.post("/modules/restart", data={"csrf": csrf})
    written = tomllib.loads((tmp_path / "themi.toml").read_text())
    assert written["roles"] == {"member": {"modules": ["*", "-safeway"]}}


async def test_secrets_still_never_shown_and_members_get_nothing(scenario: Scenario) -> None:
    async with web_client(scenario) as site:
        csrf = await sign_in(scenario, site, "Husband")
        response = await site.post(
            "/modules/breaks/preferences", data={"csrf": csrf, "break_extend_minutes": "25"}
        )
        assert response.status_code == 403
        roles = await site.post("/modules/safeway/roles", data={"csrf": csrf})
        assert roles.status_code == 403
