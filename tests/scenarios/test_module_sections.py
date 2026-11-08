"""CR17a: the dashboard and the Accounts page are made of the loaded modules' sections.

The family's pages show the same sections in the same order as before, and a module left
out takes its section (and the routes behind it) with it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.thinq import FakeThinq
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.app import family_modules
from themi.localtime import to_utc_iso


def in_order(page: str, *parts: str) -> bool:
    """Each part is on the page, after the one before it."""
    places = [page.find(part) for part in parts]
    return all(p >= 0 for p in places) and places == sorted(places)


@pytest.mark.usefixtures("fake_google")
async def test_the_familys_dashboard_has_its_sections_in_order(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    home = (await site.get("/")).text
    assert in_order(home, "Waiting on you", "On your list", "Grocery list", "Recently")


@pytest.mark.usefixtures(
    "fake_google",
    "fake_gcal",
    "fake_spotify",
    "fake_home_connect",
    "fake_thinq",
    "fake_roborock",
    "fake_tuya",
    "fake_catgenie",
)
async def test_the_familys_accounts_page_has_its_sections_in_order(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/accounts")).text
    rows = ("home-connect", "thinq", "roborock", "tuya", "catgenie", "family-calendar")
    assert in_order(
        page,
        "My Google accounts",
        'id="music"',
        'id="household"',
        *(f'id="{row}"' for row in rows),
        "Safeway helper",
    )
    assert "isn't set up on this server yet" not in page  # Google's own section, not the note
    async with web_client(scenario) as member_site:
        await sign_in(scenario, member_site, "Husband")
        mine = (await member_site.get("/accounts")).text
        assert in_order(mine, "My Google accounts", 'id="music"')
        assert 'id="household"' not in mine and 'id="thinq"' not in mine


@asynccontextmanager
async def without(
    family: SeededFamily, telegram: FakeTelegram, *left_out: str, **fakes: object
) -> AsyncIterator[Scenario]:
    """The family's app on these fakes, with some modules left out (and what needs them)."""
    modules = family_modules(**connector_options(**fakes))  # type: ignore[arg-type]
    gone = set(left_out)
    while needing := [m for m in modules if m.name not in gone and gone & set(m.requires)]:
        gone |= {m.name for m in needing}
    modules = [m for m in modules if m.name not in gone]
    scenario = Scenario(family, telegram, modules=modules, **fakes)  # type: ignore[arg-type]
    await scenario.start()
    try:
        yield scenario
    finally:
        await scenario.stop()


async def test_a_module_left_out_takes_its_section_with_it(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    fake_google: FakeGoogle,
    fake_thinq: FakeThinq,
) -> None:
    async with without(
        family, fake_telegram, "thinq", "appliances", google=fake_google, thinq=fake_thinq
    ) as scenario:
        erin = scenario.member("Erin")
        washer = scenario.app.store.add_device(erin, "lg_thinq", "w-1", "Washer", "washer")
        scenario.app.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?)",
            (washer.id, "running", to_utc_iso(clock.now())),
        )
        async with web_client(scenario) as site:
            csrf = await sign_in(scenario, site, "Erin")
            home = (await site.get("/")).text
            assert "Around the house" not in home  # the appliances module's panel
            assert in_order(home, "Waiting on you", "On your list", "Grocery list")
            page = (await site.get("/accounts")).text
            assert 'id="household"' in page and 'id="thinq"' not in page
            assert "My Google accounts" in page
            gone = await site.post("/family/thinq/link", data={"csrf": csrf, "token": "t"})
            assert gone.status_code == 404  # its routes went with it


async def test_without_the_google_module_accounts_says_linking_isnt_set_up(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_google: FakeGoogle
) -> None:
    async with (
        without(family, fake_telegram, "google", google=fake_google) as scenario,
        web_client(scenario) as site,
    ):
        await sign_in(scenario, site, "Erin")
        page = (await site.get("/accounts")).text
        assert "My Google accounts" in page
        assert "Linking Gmail isn't set up on this server yet" in page.replace("&#39;", "'")
        assert (await site.get("/auth/google")).status_code == 404
