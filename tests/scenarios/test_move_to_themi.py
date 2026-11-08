"""SP8a: a Themi set up with .env keeps working as it was, and each value can be moved into
Themi from the Modules page, after which the .env line can go."""

from __future__ import annotations

import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx

from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.config import parse_config, resolve_start
from themi.modules.store import ModuleSecrets
from themi.settings import Settings
from themi.storage.secrets import generate_key


@asynccontextmanager
async def admin(scenario: Scenario) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        yield client, csrf


def on_the_server(scenario: Scenario, tmp_path: Path, **env: str) -> None:
    scenario.app.services.environment = {"THEMI_DB_PATH": str(tmp_path / "themi.db"), **env}


async def test_a_secret_in_env_moves_into_themi_and_wins_once_the_line_goes(
    scenario: Scenario, tmp_path: Path
) -> None:
    on_the_server(scenario, tmp_path, TAVILY_API_KEY="tvly-from-env-7777")
    async with admin(scenario) as (site, csrf):
        before = (await site.get("/modules/web_search")).text
        assert "Move it to Themi" in before and "tvly-from-env-7777" not in before
        moved = await site.post("/modules/web_search/move/tavily_api_key", data={"csrf": csrf})
        page = (await site.get(moved.headers["location"])).text
        assert "delete the TAVILY_API_KEY line from .env" in page
        assert "copied into Themi" in page and "Move it to Themi" not in page
        on_the_server(scenario, tmp_path)  # the .env line deleted, and Themi restarted
        after = (await site.get("/modules/web_search")).text
        assert "Saved, ends in …7777" in after
    stored = ModuleSecrets(scenario.app.db, scenario.app.store.cipher).all()
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key()})
    modules, _ = resolve_start(parse_config({}), settings, stored=stored)
    search = next(m for m in modules if m.name == "web_search")
    assert search.backend is not None  # type: ignore[attr-defined]  # it has a key now


async def test_a_plain_value_in_env_moves_into_themi_toml(
    scenario: Scenario, tmp_path: Path
) -> None:
    on_the_server(scenario, tmp_path, THEMI_SEARCH_BACKEND="firecrawl")
    async with admin(scenario) as (site, csrf):
        await site.post("/modules/web_search/move/backend", data={"csrf": csrf})
    written = tomllib.loads((tmp_path / "themi.toml").read_text())
    assert written["module"]["web_search"] == {"backend": "firecrawl"}


async def test_moving_a_secret_needs_a_recent_sign_in(scenario: Scenario, tmp_path: Path) -> None:
    on_the_server(scenario, tmp_path, TAVILY_API_KEY="tvly-from-env-7777")
    async with admin(scenario) as (site, csrf):
        clock.advance(timedelta(minutes=20))
        moved = await site.post("/modules/web_search/move/tavily_api_key", data={"csrf": csrf})
        assert "sign in again" in (await site.get(moved.headers["location"])).text
    assert ModuleSecrets(scenario.app.db, scenario.app.store.cipher).all() == {}


async def test_nothing_to_move_says_so(scenario: Scenario, tmp_path: Path) -> None:
    on_the_server(scenario, tmp_path)
    async with admin(scenario) as (site, csrf):
        moved = await site.post("/modules/web_search/move/tavily_api_key", data={"csrf": csrf})
        page = (await site.get(moved.headers["location"])).text
    assert "isn&#39;t set on the server" in page
