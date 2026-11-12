"""EX4a: the Google Sheets client against the fake Sheets API, the scope it needs, and its
trust category."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import pytest

from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gsheets_api import FakeGsheets
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_gmail import link
from tests.scenarios.test_triage import ERIN
from themi.autonomy.engine import Tier
from themi.core import keys
from themi_google.connectors.google import DRIVE_FILE_SCOPE
from themi_google.connectors.google.oauth import LINK_SCOPES
from themi_google.connectors.gsheets import (
    Cell,
    SheetsClient,
    SheetsNotFound,
    SheetsRateLimited,
    delete_sheet,
    update_sheet,
)
from themi_home.expense_sync import CATEGORY

GREEN = (0.85, 0.94, 0.83)


@pytest.fixture
async def client(
    scenario: Scenario, fake_google: FakeGoogle, fake_gsheets: FakeGsheets, site: httpx.AsyncClient
) -> SheetsClient:
    await link(scenario, site, fake_google, "Erin", ERIN)
    sync = scenario.app.services.maybe(keys.expense_sync)
    assert sync is not None and sync.ready()
    (account,) = sync.accounts_for(scenario.member("Erin"))
    return sync.client(account.id)


async def test_a_spreadsheet_and_its_tabs(client: SheetsClient, fake_gsheets: FakeGsheets) -> None:
    sid, tabs = await client.create("Business", ["Business", "Income"])
    assert [t.title for t in tabs] == ["Business", "Income"]
    mileage = await client.add_tab(sid, "Mileage", 2)
    assert fake_gsheets.titles(sid) == ["Business", "Income", "Mileage"]
    await client.batch(sid, [update_sheet(mileage, title="Driving", index=1)])
    assert fake_gsheets.titles(sid) == ["Business", "Driving", "Income"]
    await client.batch(sid, [delete_sheet(tabs[1].id)])
    assert [t.title for t in await client.tabs(sid)] == ["Business", "Driving"]


async def test_rows_found_by_their_hidden_id(
    client: SheetsClient, fake_gsheets: FakeGsheets
) -> None:
    sid, (tab, *_) = await client.create("Business", ["Business"])
    header = ["Amount", "Vendor", "Status"]
    await client.upsert(sid, tab, header, {
        "1": [Cell(84.2, "From a receipt email, 95% sure", GREEN), Cell("Merit"), Cell("Checked")],
        "2": [Cell(12), Cell(""), Cell("Missing")],
    })  # fmt: skip
    assert fake_gsheets.values(sid, "Business", shown=True) == [
        ["Amount", "Vendor", "Status"], [84.2, "Merit", "Checked"], [12, "", "Missing"],
    ]  # fmt: skip
    assert fake_gsheets.tab(sid, "Business").hidden == {0}  # the id column
    assert fake_gsheets.colour(sid, "Business", 1, 1) == GREEN
    assert fake_gsheets.note(sid, "Business", 1, 1) == "From a receipt email, 95% sure"

    await client.upsert(sid, tab, header, {"2": [Cell(12), Cell("ParkMobile"), Cell("Checked")]})
    assert fake_gsheets.values(sid, "Business") == [
        ["", "Amount", "Vendor", "Status"],
        ["1", 84.2, "Merit", "Checked"],
        ["2", 12, "ParkMobile", "Checked"],
    ]  # fmt: skip — updated in place, never a second row

    await client.upsert(sid, tab, header, {"3": [Cell(5)]}, remove=["1"])
    assert [row[0] for row in fake_gsheets.values(sid, "Business")] == ["", "2", "3"]


async def test_gone_and_slow_down(client: SheetsClient, fake_gsheets: FakeGsheets) -> None:
    sid, (tab, *_) = await client.create("Business", ["Business"])
    fake_gsheets.fail("batchUpdate", 429)
    with pytest.raises(SheetsRateLimited):
        await client.batch(sid, [update_sheet(tab.id, title="x")])
    fake_gsheets.delete(sid)
    with pytest.raises(SheetsNotFound):
        await client.tabs(sid)


async def test_an_account_without_drive_is_asked_to_link_again(
    scenario: Scenario, fake_google: FakeGoogle, fake_gsheets: FakeGsheets, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/link gmail")
    unticked = tuple(s for s in LINK_SCOPES if s != DRIVE_FILE_SCOPE)
    callback = urlsplit(fake_google.consent(reply.splitlines()[-1], ERIN, scopes=unticked))
    await site.get(f"{callback.path}?{callback.query}")
    sync = scenario.app.services.maybe(keys.expense_sync)
    assert sync is not None and sync.accounts_for(scenario.member("Erin")) == []
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/accounts")).text
    assert "Link again for the cookbook and expense sheets" in page
    assert "keep your expense sheets in Google Sheets" in page


async def test_the_trust_category(scenario: Scenario) -> None:
    autonomy = scenario.app.services.autonomy
    category = autonomy.category(CATEGORY)
    assert (category.scope, category.tier, category.max_tier) == (
        "member",
        Tier.SUPERVISED,
        Tier.AUTOMATIC,
    )
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    rulebook = scenario.app.services.rulebook
    assert rulebook is not None
    rulebook.grant_automatic(erin, CATEGORY)  # it may become automatic, for her alone
    assert autonomy.is_automatic(CATEGORY, erin)
    assert not autonomy.is_automatic(CATEGORY, husband)
