"""MP2: turning a group on or off from the Modules page, in one review sheet."""

from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.config import parse_config
from themi.modules.store import DraftStore


@asynccontextmanager
async def admin(scenario: Scenario) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        yield client, csrf


def empty(scenario: Scenario) -> None:
    scenario.app.services.instance_config = parse_config({"template": "empty"})


def ticked(page: str, name: str) -> bool:
    tag = page.split(f'name="pick_{name}"', 1)[1].split(">", 1)[0]
    return " checked" in tag


async def test_the_group_sheet_ticks_the_starter_set(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, _):
        modules = (await site.get("/modules")).text
        page = (await site.get("/modules/group/body_doubling")).text
    assert 'href="/modules/group/body_doubling?to=on">Turn on the group…' in modules
    assert "Turn on Body doubling?" in page
    assert ticked(page, "body_double") and ticked(page, "guided_steps")
    assert not ticked(page, "step_pictures")  # it draws pictures: offered, not ticked
    assert "Turn on what&#39;s ticked" in page


async def test_what_the_ticked_ones_need_from_other_groups_is_listed(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, _):
        page = (await site.get("/modules/group/money")).text
    needed = page.split("Also needed, from other groups", 1)[1].split("</section>", 1)[0]
    # takeout needs meals, which needs the pantry and the grocery list
    assert "Meal ideas" in needed and "Pantry" in needed and "Grocery list" in needed
    assert "Spending" not in needed  # it's in the group


async def test_turning_on_a_group_drafts_whats_ticked_and_what_it_needs(
    scenario: Scenario,
) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        done = await site.post(
            "/modules/group/money/switch",
            data={"csrf": csrf, "to": "on", "pick_spending": "1"},  # takeout unticked
        )
        assert done.status_code == 303
        page = (await site.get("/modules")).text
    draft = DraftStore(scenario.app.db).get()
    assert draft is not None and draft.modules == {"spending": True}
    assert "turned on Money: 1 module (Spending)" in page


async def test_turning_off_a_group_offers_what_was_on_only_for_it(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        await site.post(
            "/modules/group/body_doubling/switch",
            data={"csrf": csrf, "to": "on", "pick_step_pictures": "1"},
        )
        sheet = (await site.get("/modules/group/body_doubling", params={"to": "off"})).text
        assert "No longer needed" in sheet and "Making pictures" in sheet
        await site.post(
            "/modules/group/body_doubling/switch",
            data={
                "csrf": csrf,
                "to": "off",
                "pick_body_double": "1",
                "pick_guided_steps": "1",
                "pick_step_pictures": "1",
                "spare_image_generation": "1",
            },
        )
    draft = DraftStore(scenario.app.db).get()
    assert draft is None  # everything back as the template has it


async def test_the_last_ai_provider_stays_on(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        sheet = (await site.get("/modules/group/ai", params={"to": "off"})).text
        assert "Staying on" in sheet and "at least one AI provider" in sheet
        alone = await site.post("/modules/gemini/switch", data={"csrf": csrf, "to": "off"})
        assert alone.status_code == 303
    assert DraftStore(scenario.app.db).get() is None


async def test_undo_the_last_change_only(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/travel/switch", data={"csrf": csrf, "to": "on"})
        await site.post(
            "/modules/group/money/switch",
            data={"csrf": csrf, "to": "on", "pick_spending": "1", "pick_takeout": "1"},
        )
        page = (await site.get("/modules")).text
        assert "Undo the last change" in page
        await site.post("/modules/undo-last", data={"csrf": csrf})
    draft = DraftStore(scenario.app.db).get()
    assert draft is not None and draft.modules == {"travel": True}


async def test_an_admin_turns_on_cooking_and_restarts(scenario: Scenario, tmp_path: Path) -> None:
    empty(scenario)
    scenario.app.services.environment = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    scenario.app.services.restart = lambda: None
    starter = ["recipes", "recipe_groceries", "cooking", "cooking_timers", "web_recipes"]
    async with admin(scenario) as (site, csrf):
        await site.post(
            "/modules/group/cooking/switch",
            data={"csrf": csrf, "to": "on", **{f"pick_{n}": "1" for n in starter}},
        )
        await site.post("/modules/restart", data={"csrf": csrf})
    written = tomllib.loads((tmp_path / "themi.toml").read_text())
    assert set(written["modules"]) == {f"+{n}" for n in starter}
    rows = scenario.app.db.query("SELECT module, reason FROM module_reasons")
    kept = {row["module"]: row["reason"] for row in rows}
    assert kept == {n: "asked" for n in starter}


# ----- MP3: one module's sheet -------------------------------------------------------------


async def test_turning_on_body_double_offers_its_add_ons(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        sheet = await site.post("/modules/body_double/switch", data={"csrf": csrf, "to": "on"})
        page = sheet.text
        assert "Turn on Body double?" in page
        for add_on in ("guided_steps", "mode_chooser", "music_offers"):
            tag = page.split(f'name="add_{add_on}"', 1)[1].split(">", 1)[0]
            assert " checked" not in tag  # offered, not ticked
        assert 'name="add_step_pictures"' not in page  # it builds on Guided steps instead
        await site.post(
            "/modules/body_double/switch",
            data={"csrf": csrf, "to": "on", "confirmed": "1", "add_guided_steps": "1"},
        )
    draft = DraftStore(scenario.app.db).get()
    assert draft is not None
    assert draft.modules == {"body_double": True, "guided_steps": True}
    assert draft.reasons == {"body_double": "asked", "guided_steps": "asked"}


async def test_what_a_module_does_more_with_is_offered(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        page = (await site.post("/modules/tasks/switch", data={"csrf": csrf, "to": "on"})).text
    assert 'name="add_pictures"' in page and "It does more with it" in page


async def test_a_module_with_nothing_to_offer_skips_the_sheet(scenario: Scenario) -> None:
    empty(scenario)
    async with admin(scenario) as (site, csrf):
        done = await site.post("/modules/travel/switch", data={"csrf": csrf, "to": "on"})
    assert done.status_code == 303
    draft = DraftStore(scenario.app.db).get()
    assert draft is not None and draft.modules == {"travel": True}
