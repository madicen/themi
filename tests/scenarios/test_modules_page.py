"""SP4: the Modules page, read only: each module's state, what it needs and what needs it,
its settings (never a secret's value) and its guide."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.modules import StartReport
from themi.modules.store import Draft, DraftStore, ModuleSecrets


def card_of(page: str, name: str) -> str:
    match = re.search(rf'<li class="card module" id="module-{name}"[^>]*>(.*?)</li>', page, re.S)
    assert match, f"no card for {name}"
    return match.group(1)


@asynccontextmanager
async def admin_site(scenario: Scenario) -> AsyncIterator[httpx.AsyncClient]:
    async with web_client(scenario) as client:
        await sign_in(scenario, client, "Erin")
        yield client


async def test_the_page_shows_each_module_by_group_with_its_state(scenario: Scenario) -> None:
    report = StartReport(template="family")
    for module in scenario.app.modules:
        report.note(module.name, "on", type(module).kind)
    report.note("travel", "failed", "connector", "TomTom turned the key down")
    report.note("ourgroceries", "not_set_up", "connector", "its settings aren't there")
    report.note("safeway", "off", "feature", "removed in themi.toml")
    report.note("smarthq", "needs_library", "connector", "the gehomesdk library isn't here")
    scenario.app.services.start_report = report
    async with admin_site(scenario) as site:
        page = (await site.get("/modules")).text
    # MP1: by group (what it's for), not by kind
    assert (
        page.index("<h2>Talking to Themi</h2>")
        < page.index("<h2>AI</h2>")
        < page.index("<h2>Tasks</h2>")
        < page.index("<h2>Cooking</h2>")
        < page.index("<h2>Behind the scenes</h2>")
    )
    assert "<h2>Features</h2>" not in page
    assert "On" in card_of(page, "tasks")
    travel = card_of(page, "travel")
    assert "Couldn&#39;t start" in travel and "TomTom turned the key down" in travel
    assert "Needs settings" in card_of(page, "ourgroceries")
    assert ">Off<" in card_of(page, "safeway")
    smarthq = card_of(page, "smarthq")
    assert "Not in this install" in smarthq and "the gehomesdk library isn" in smarthq
    assert "Needs settings" not in smarthq
    assert ">Off<" in card_of(page, "spotify")  # not in this Themi at all


async def test_search_and_only_whats_in_use(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        found = (await site.get("/modules", params={"q": "grocery"})).text
        assert 'id="module-groceries"' in found and 'id="module-tasks"' not in found
        in_use = (await site.get("/modules", params={"only_on": "1"})).text
        assert 'id="module-tasks"' in in_use and 'id="module-spotify"' not in in_use


async def test_a_change_waiting_for_a_restart_is_marked(scenario: Scenario) -> None:
    DraftStore(scenario.app.db).save(Draft(modules={"travel": True}), None)
    async with admin_site(scenario) as site:
        page = (await site.get("/modules")).text
    assert "Changes are waiting for a restart." in page
    assert "Waiting for restart" in card_of(page, "travel")


async def test_a_modules_page_shows_what_it_needs_and_what_needs_it(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        gmail = (await site.get("/modules/gmail")).text
        google = (await site.get("/modules/google")).text
    needs = gmail.split("It needs", 1)[1].split("</ul>", 1)[0]
    assert "Google accounts" in needs
    needed_by = gmail.split("These need it", 1)[1].split("</ul>", 1)[0]
    assert "Email triage" in needed_by and "Noise digest" in needed_by
    assert "Gmail" in google.split("These need it", 1)[1].split("</ul>", 1)[0]


async def test_the_guide_is_shown_with_this_sites_address(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        page = (await site.get("/modules/google")).text
    assert "<code>http://themi.test/auth/google/callback</code>" in page
    assert "$SITE" not in page
    assert "Google OAuth client id" in page


async def test_a_secrets_value_never_reaches_the_page(scenario: Scenario) -> None:
    ModuleSecrets(scenario.app.db, scenario.app.store.cipher).set(
        "web_search", "tavily_api_key", "tvly-very-secret-9876", None
    )
    scenario.app.services.environment = {"FIRECRAWL_API_KEY": "fc-from-the-server-5555"}
    async with admin_site(scenario) as site:
        page = (await site.get("/modules/web_search")).text
    assert "Saved, ends in …9876" in page
    assert "tvly-very-secret-9876" not in page
    assert "Set on the server" in page and "fc-from-the-server-5555" not in page


@pytest.mark.usefixtures("fake_google")
async def test_a_module_waiting_for_someone_to_link_says_so(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        page = (await site.get("/modules")).text
        google = (await site.get("/modules/google")).text
    assert "Needs an account linked" in card_of(page, "google")
    assert "Each person links a Google account" in google and "Not linked yet" in google


async def test_its_only_for_admins(scenario: Scenario) -> None:
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Husband")
        response = await site.get("/modules")
        assert response.status_code == 403 and "Admins only" in response.text
        assert (await site.get("/modules/tasks")).status_code == 403
        assert "/modules" not in (await site.get("/more")).text


async def test_an_unknown_module_is_a_plain_404(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        response = await site.get("/modules/bogus")
    assert response.status_code == 404 and "There&#39;s no module called bogus" in response.text


async def test_the_dashboards_warning_links_to_the_modules_page(scenario: Scenario) -> None:
    scenario.app.services.start_report.note("travel", "failed", "connector", "bad key")
    async with admin_site(scenario) as site:
        home = (await site.get("/")).text
    assert 'href="/modules"' in home and "travel couldn&#39;t start: bad key" in home


async def test_add_ons_are_indented_and_guests_listed_in_both_groups(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        page = (await site.get("/modules")).text
    cooking = page.split('id="group-cooking"', 1)[1].split("</details>", 1)[0]
    assert cooking.index('id="module-recipes"') < cooking.index('id="module-cooking"')
    assert 'id="module-cooking" data-depth="2"' in cooking
    assert 'id="module-recipes" data-depth' not in cooking
    # the Oven lives in Home and devices and is a guest here
    assert "Oven (SmartHQ)" in cooking and "Listed under Home and devices." in cooking
    assert 'id="module-smarthq"' in page.split('id="group-home"', 1)[1]
    # Behind the scenes starts folded
    assert '<details class="module-group" id="group-behind_the_scenes">' in page
    assert '<details class="module-group" id="group-cooking" open>' in page


def test_the_family_modules_own_what_they_added(scenario: Scenario) -> None:
    """MP4: each module's Settings and Accounts sections and menu entries are found by name."""
    services = scenario.app.services
    assert [s.template for s in services.owned_by("spending").settings] == [
        "settings/expenses.html"
    ]
    assert [a.template for a in services.owned_by("safeway").accounts] == ["accounts/safeway.html"]
    assert any(m.href == "/recipes" for m in services.owned_by("recipes").menu)
    assert services.owned_by("tasks").accounts == ()


# ----- MP6: the list, quicker to use --------------------------------------------------------


def broken_report(scenario: Scenario) -> None:
    report = StartReport(template="family")
    for module in scenario.app.modules:
        report.note(module.name, "on", type(module).kind)
    report.note("travel", "failed", "connector", "TomTom turned the key down")
    report.note("ourgroceries", "not_set_up", "connector", "its settings aren't there")
    scenario.app.services.start_report = report


async def test_needs_attention_links_to_what_fixes_it(scenario: Scenario) -> None:
    broken_report(scenario)
    async with admin_site(scenario) as site:
        page = (await site.get("/modules")).text
    strip = page.split('id="attention"', 1)[1].split("</section>", 1)[0]
    assert 'href="/modules/ourgroceries#server"' in strip
    assert 'href="/modules/travel"' in strip and "TomTom turned the key down" in strip
    assert "1 needs attention" in page.split('id="group-groceries"', 1)[1].split("</summary>")[0]


async def test_each_filter(scenario: Scenario) -> None:
    broken_report(scenario)
    async with admin_site(scenario) as site:
        on = (await site.get("/modules", params={"show": "on"})).text
        off = (await site.get("/modules", params={"show": "off"})).text
        attention = (await site.get("/modules", params={"show": "attention"})).text
        everything = (await site.get("/modules", params={"show": "bogus"})).text
    assert 'id="module-tasks"' in on and 'id="module-spotify"' not in on
    assert 'id="module-spotify"' in off and 'id="module-tasks"' not in off
    assert 'id="module-travel"' in attention and 'id="module-tasks"' not in attention
    assert 'id="module-tasks"' in everything and 'id="module-spotify"' in everything
    assert 'class="chip selected" href="/modules?show=attention"' in attention


async def test_searching_a_groups_name_shows_the_group(scenario: Scenario) -> None:
    async with admin_site(scenario) as site:
        page = (await site.get("/modules", params={"q": "body doubling"})).text
    assert 'id="module-music_offers"' in page and 'id="module-tasks"' not in page


async def test_a_cards_switch_comes_back_to_the_card(scenario: Scenario) -> None:
    async with web_client(scenario) as site:
        csrf = await sign_in(scenario, site, "Erin")
        page = (await site.get("/modules")).text
        assert 'aria-label="Turn off Safeway cart"' in card_of(page, "safeway")
        done = await site.post(
            "/modules/safeway/switch", data={"csrf": csrf, "to": "off", "back": "list"}
        )
        assert done.status_code == 303 and done.headers["location"] == "/modules#module-safeway"
        other = (await site.get("/family")).text
    assert '<a href="/modules/restart">Restart</a>' in other  # the bar, on another admin page


async def test_an_off_card_says_what_it_needs(scenario: Scenario) -> None:
    from themi.config import parse_config

    scenario.app.services.instance_config = parse_config({"template": "empty"})
    async with admin_site(scenario) as site:
        page = (await site.get("/modules")).text
    assert "Needs Family cookbook, Recipe groceries" in card_of(page, "cooking")


async def test_the_safeway_page_says_how_to_install_the_helper(scenario: Scenario) -> None:
    """SW1: installing the Chrome extension was only in the repo's README."""
    async with admin_site(scenario) as site:
        page = (await site.get("/modules/safeway")).text
        safeway = (await site.get("/safeway")).text
    assert "Load unpacked" in page and "chrome://extensions" in page
    assert "https://github.com/madicen/themi/archive/refs/heads/main.zip" in page
    assert "<code>http://themi.test</code>" in page  # what to paste as Themi's address
    # anyone can connect a helper, and the Modules page is for admins: /safeway shows it too
    assert "Load unpacked" in safeway and "<code>http://themi.test</code>" in safeway
    assert "README" not in safeway
    assert '<details class="module-guide card" open>' in safeway  # no helper yet: open
