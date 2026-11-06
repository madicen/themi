"""RC1a: the family cookbook, picked on Accounts and read from its Google Doc. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.cookbook import COOKBOOK_ID, LINK, TITLE, cookbook
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi.connectors.google import DRIVE_FILE_SCOPE
from themi.connectors.google.oauth import LINK_SCOPES

READ = (
    "I've read 12 recipes and 3 charts from the cookbook. 3 need a look: Bean Dip (headings typed "
    "as text), Biryani (two Ingredients headings), Ube Gelato (headings typed as text)."
)


def account_id(scenario: Scenario) -> int:
    return int(scenario.app.db.scalar("SELECT id FROM linked_accounts WHERE address = ?", (ERIN,)))


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gdocs: FakeGdocs, site: httpx.AsyncClient
) -> FakeGdocs:
    """Erin's Google account, linked with Google Drive allowed, and the cookbook shared with
    Themi through it (as picking it in Google's file picker does)."""
    await link(scenario, site, fake_google, "Erin", ERIN)
    fake_gdocs.add_doc(COOKBOOK_ID, TITLE, cookbook(), shared_with=[ERIN])
    return fake_gdocs


async def choose(scenario: Scenario, site: httpx.AsyncClient, doc: str = LINK) -> httpx.Response:
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post(
        f"/accounts/{account_id(scenario)}/cookbook", data={"csrf": csrf, "doc": doc}
    )
    assert response.status_code == 303
    return await site.get(response.headers["location"])


def names(scenario: Scenario) -> list[str]:
    recipes = scenario.app.services.recipes
    assert recipes is not None
    return [r.name for r in recipes.all()]


async def test_the_cookbook_is_chosen_and_read(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    page = await choose(scenario, site)
    assert "read 12 recipes and 3 charts" in page.text
    assert "Biryani" in page.text and "two Ingredients headings" in page.text  # needs a look
    inbox = scenario.inbox("Erin")
    assert READ in inbox
    assert inbox[-1] == (
        'The cookbook\'s References has "Weights of Common Ingredients", "Instant Pot Grains '
        'Timings". Want them as guides, so you can ask me about them?'
    )
    assert "Alfredo Sauce" in names(scenario) and "Roasted Vegetables" not in names(scenario)
    settings = scenario.app.services.recipes.settings()  # type: ignore[union-attr]
    assert settings["doc_id"] == COOKBOOK_ID and settings["title"] == TITLE
    assert settings["revision"] == "rev1"


async def test_the_references_become_guides(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    await choose(scenario, site)
    await scenario.tap("Erin", "Save as guides")
    guides = scenario.app.services.guides
    assert guides is not None
    saved = {g.name: g.text for g in guides.visible(scenario.member("Husband"))}
    assert set(saved) == {"Weights of Common Ingredients", "Instant Pot Grains Timings"}
    assert (
        "Brown Rice: Grain : Water Ratio 1:1, High Pressure Time 15m"
        in saved["Instant Pot Grains Timings"]
    )
    assert scenario.edits("Erin")[-1]["text"].startswith("Saved as guides:")


async def test_a_guide_already_there_isnt_offered_again(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    guides = scenario.app.services.guides
    assert guides is not None
    guides.save(scenario.member("Erin"), "Instant Pot grains", "Quinoa 1 min", personal=False)
    guides.save(scenario.member("Erin"), "Ingredient weights", "Flour 120g", personal=False)
    await choose(scenario, site)
    assert scenario.inbox("Erin")[-1] == READ


async def test_only_a_new_version_is_read_again(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    await choose(scenario, site)
    reads = linked.calls.count(("get", COOKBOOK_ID))
    await scenario.run_periodic("recipes.sync")
    assert linked.calls.count(("get", COOKBOOK_ID)) == reads  # same version: not read
    recipes = scenario.app.services.recipes
    assert recipes is not None
    alfredo = next(r for r in recipes.all() if r.name == "Alfredo Sauce")

    def edit(blocks: list) -> None:  # Hardtack deleted, Toast added under Snacks
        at = next(n for n, b in enumerate(blocks) if getattr(b, "text", "") == "Hardtack")
        blocks[at] = linked.para("H4", "Toast")

    linked.edit(COOKBOOK_ID, edit)
    await scenario.run_periodic("recipes.sync")
    assert linked.calls.count(("get", COOKBOOK_ID)) == reads + 1
    assert "Toast" in names(scenario) and "Hardtack" not in names(scenario)
    gone = scenario.app.db.one("SELECT * FROM recipes WHERE name = 'Hardtack'")
    assert gone is not None and gone["removed_at"] is not None  # kept, marked removed
    assert recipes.get(alfredo.id) == alfredo  # unchanged recipes aren't touched


async def test_a_doc_themi_wasnt_given_says_how(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    linked.add_doc("1AnotherDocNobodyPickedForThemi00", "Other", cookbook())
    page = await choose(
        scenario, site, "https://docs.google.com/document/d/1AnotherDocNobodyPickedForThemi00/edit"
    )
    assert "Google won&#39;t let Themi open that doc" in page.text
    assert scenario.app.services.recipes.doc_id is None  # type: ignore[union-attr]


async def test_a_file_that_isnt_a_doc(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    linked.add_doc(
        "1ASpreadsheetNotADocument0000000", "Budget", [], shared_with=[ERIN],
        mime="application/vnd.google-apps.spreadsheet",
    )  # fmt: skip
    page = await choose(scenario, site, "1ASpreadsheetNotADocument0000000")
    assert "isn&#39;t a Google Doc" in page.text


async def test_a_failed_read_is_kept_and_shown(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    await choose(scenario, site)
    linked.edit(COOKBOOK_ID, lambda blocks: None)
    linked.fail("get", 503)
    await scenario.run_periodic("recipes.sync")
    page = await site.get(f"/accounts/{account_id(scenario)}/cookbook")
    assert "Google Docs returned HTTP 503" in page.text
    assert "Alfredo Sauce" in names(scenario)  # the copy stays


async def test_an_account_linked_before_rc1a_is_asked_to_link_again(
    scenario: Scenario, fake_google: FakeGoogle, fake_gdocs: FakeGdocs, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/link gmail")
    unticked = tuple(s for s in LINK_SCOPES if s != DRIVE_FILE_SCOPE)
    callback = urlsplit(fake_google.consent(reply.splitlines()[-1], ERIN, scopes=unticked))
    await site.get(f"{callback.path}?{callback.query}")
    await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "Google Drive isn't allowed for this account yet" in page.text
    response = await site.get(f"/accounts/{account_id(scenario)}/cookbook")
    assert response.status_code == 303


async def test_the_picker_page_alone_may_load_googles_scripts(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = await site.get(f"/accounts/{account_id(scenario)}/cookbook")
    assert "https://apis.google.com" in page.headers["content-security-policy"]
    assert "x-themi-page" not in page.headers
    accounts = await site.get("/accounts")
    assert "apis.google.com" not in accounts.headers["content-security-policy"]
    assert "Choose the family cookbook" in accounts.text
