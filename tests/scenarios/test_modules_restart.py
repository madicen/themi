"""SP6: Restart on the Modules page: a pre-flight, the draft made live (the setup before it
kept), Themi stopped and started again, and the admin told how it went."""

from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import ERIN_TELEGRAM_ID
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.localtime import to_utc_iso
from themi.modules.store import Draft, DraftStore, ModuleSecrets


@pytest.fixture
def restarts(scenario: Scenario, tmp_path: Path) -> list[str]:
    """Themi's data folder in tmp_path, and a restart that only counts."""
    calls: list[str] = []
    scenario.app.services.environment = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    scenario.app.services.restart = lambda: calls.append("restart")
    return calls


@asynccontextmanager
async def admin(scenario: Scenario) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        yield client, csrf


async def test_the_restart_page_says_what_would_not_start(scenario: Scenario) -> None:
    draft = Draft(sections={"home_connect": {"url": "ftp://not-https.test"}})
    draft.put_secret(scenario.app.store.cipher, "home_connect", "client_secret", "s")
    draft.sections["home_connect"]["client_id"] = "id"
    DraftStore(scenario.app.db).save(draft, None)
    async with admin(scenario) as (site, _):
        page = (await site.get("/modules/restart")).text
    assert "home_connect couldn&#39;t start" in page and "https://" in page
    assert "Restart anyway" in page


async def test_restart_makes_the_draft_live_and_keeps_the_last_good(
    scenario: Scenario, restarts: list[str], tmp_path: Path
) -> None:
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})
        await site.post(
            "/modules/web_search/settings", data={"csrf": csrf, "tavily_api_key": "tvly-new-1"}
        )
        page = (await site.post("/modules/restart", data={"csrf": csrf})).text
    assert "Restarting Themi with the changes" in page and restarts == ["restart"]
    written = tomllib.loads((tmp_path / "themi.toml").read_text())
    assert written["template"] == "family" and written["modules"] == ["-safeway"]
    stored = ModuleSecrets(scenario.app.db, scenario.app.store.cipher).all()
    assert stored["web_search"]["tavily_api_key"].reveal() == "tvly-new-1"
    assert DraftStore(scenario.app.db).get() is None
    last = scenario.app.db.one("SELECT toml FROM config_last_good")
    assert last is not None and "safeway" not in last["toml"]


async def test_the_admin_hears_how_it_went_once_themi_is_back(
    scenario: Scenario, restarts: list[str], fake_telegram: FakeTelegram
) -> None:
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})
        await site.post("/modules/restart", data={"csrf": csrf})
    scenario.app.services.start_report.note("travel", "failed", "connector", "bad key")
    await scenario.run_periodic("modules.announce")
    await scenario.app.outbox.flush()
    said = fake_telegram.sent_texts(ERIN_TELEGRAM_ID)[-1]
    assert said.startswith("Themi restarted with your changes: turned off Safeway cart.")
    assert "These couldn't start: travel (bad key)." in said
    await scenario.run_periodic("modules.announce")  # said once
    await scenario.app.outbox.flush()
    assert fake_telegram.sent_texts(ERIN_TELEGRAM_ID)[-1] == said


async def test_a_failed_start_offers_the_last_working_setup(
    scenario: Scenario, restarts: list[str]
) -> None:
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})
        await site.post(
            "/modules/web_search/settings", data={"csrf": csrf, "tavily_api_key": "tvly-new-1"}
        )
        await site.post("/modules/restart", data={"csrf": csrf})
        assert "last working setup" not in (await site.get("/modules")).text
        scenario.app.services.start_report.note("web_search", "failed", "connector", "bad key")
        listing = (await site.get("/modules")).text
        assert "Go back to the last working setup" in listing
        back = await site.post("/modules/last-good", data={"csrf": csrf})
        assert back.headers["location"] == "/modules/restart"
    draft = DraftStore(scenario.app.db).get()
    assert draft is not None
    assert draft.modules == {"safeway": True}
    assert draft.secrets == {"web_search": {"tavily_api_key": None}}  # it had none before


async def test_the_restarting_page_waits_for_a_new_start(scenario: Scenario) -> None:
    started = to_utc_iso(scenario.app.services.start_report.made_at)
    async with admin(scenario) as (site, _):
        same = await site.get("/modules/restart/status", params={"since": started})
        assert same.status_code == 204
        new = await site.get("/modules/restart/status", params={"since": "an earlier start"})
        assert new.headers["HX-Redirect"] == "/modules"


async def test_without_a_runtime_it_saves_and_says_to_restart_by_hand(
    scenario: Scenario, tmp_path: Path
) -> None:
    scenario.app.services.environment = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/safeway/switch", data={"csrf": csrf, "to": "off"})
        page = (await site.post("/modules/restart", data={"csrf": csrf})).text
    assert "Restart Themi on the server" in page
    assert (tmp_path / "themi.toml").exists()
