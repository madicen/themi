"""CR4: the menu built from the modules' entries, and pages that come with their module."""

from __future__ import annotations

import httpx

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from tests.scenarios.test_module_lists import build
from themi import clock
from themi.app import App, family_modules
from themi.web import HealthSources, create_app
from themi.web.auth import WebAuth
from themi.web.kit import SiteContext
from themi.web.site import CORE_MENU, Menu

# The More page before CR4, for an admin and for everyone else (copied from the old code).
ADMIN_GROUPS = [
    (
        "You",
        [
            ("/settings", "My settings", "Quiet hours, messages, phrasing"),
            ("/week", "My week", "How Themi sees your week"),
            ("/ai", "My AI", "Which AI does each job"),
        ],
    ),
    (
        "Accounts",
        [
            ("/accounts", "Google accounts", "Gmail, calendars and Google Tasks"),
            ("/accounts#household", "Household connections", "Appliances, vacuum, calendar"),
        ],
    ),
    (
        "Household",
        [
            ("/family", "Family", "The household and its people"),
            ("/knowledge", "Rules & memory", "What Themi keeps to and remembers"),
            ("/guides", "Guides", "Your own cooking charts and how-tos"),
            ("/recipes", "Recipes", "The family cookbook, and cooking with Themi"),
            ("/tiers", "What Themi does alone", "What asks first and what's automatic"),
            ("/maintenance", "Maintenance", "Filters, gutters and other upkeep"),
            ("/spending", "Spending", "Takeout and business expenses"),
            ("/safeway", "Safeway", "The cart helper and remembered products"),
        ],
    ),
    (
        "Admin",
        [
            # SP4: the Modules page joins the menu
            ("/modules", "Modules", "What Themi can do, and setting it up"),
            ("/dev", "Development", "Update or restart the server"),
        ],
    ),
]
MEMBER_GROUPS = [
    (
        "You",
        [
            ("/settings", "My settings", "Quiet hours, messages, phrasing"),
            ("/week", "My week", "How Themi sees your week"),
            ("/ai", "My AI", "Which AI does each job"),
        ],
    ),
    ("Accounts", [("/accounts", "Google accounts", "Gmail, calendars and Google Tasks")]),
    (
        "Household",
        [
            ("/knowledge", "Rules & memory", "What Themi keeps to and remembers"),
            ("/guides", "Guides", "Your own cooking charts and how-tos"),
            ("/recipes", "Recipes", "The family cookbook, and cooking with Themi"),
            ("/tiers", "What Themi does alone", "What asks first and what's automatic"),
            ("/maintenance", "Maintenance", "Filters, gutters and other upkeep"),
            ("/spending", "Spending", "Takeout and business expenses"),
            ("/safeway", "Safeway", "The cart helper and remembered products"),
        ],
    ),
]
MAIN_PAGES = [
    ("/", "Home", "Today, and what's waiting on you"),
    ("/tasks", "Tasks", "Everything to do"),
    ("/lists", "Lists", "Shopping and the other lists"),
]
BAR_LABELS = {
    "/settings": "Settings",
    "/week": "Week",
    "/ai": "AI",
    "/accounts": "Accounts",
    "/knowledge": "Rules",
    "/tiers": "Tiers",
    "/maintenance": "Upkeep",
    "/family": "Family",
    "/dev": "Dev",
    "/modules": "Modules",  # SP4
}


class Someone:
    def __init__(self, admin: bool) -> None:
        self.is_admin = admin
        self.menu_bar = None


def menu_of(app: App) -> Menu:
    return Menu([*CORE_MENU, *(e for p in app.services.web_pages for e in p.menu)])


async def test_the_family_menu_is_as_it_was(scenario: Scenario) -> None:
    menu = menu_of(scenario.app)
    assert menu.more_groups(Someone(True)) == ADMIN_GROUPS  # type: ignore[arg-type]
    assert menu.more_groups(Someone(False)) == MEMBER_GROUPS  # type: ignore[arg-type]
    assert menu.main_pages() == MAIN_PAGES
    assert menu.default_bar() == ("/", "/tasks", "/lists")
    for href, label in BAR_LABELS.items():
        assert menu.by_href[href].bar_label == label
    assert all(menu.by_href[h].icon for h in ("/", "/tasks", "/lists", "/safeway", "/week"))


def site(app: App) -> httpx.AsyncClient:
    web = create_app(
        HealthSources(app.db, None, clock.now()),
        SiteContext(app, base_url="http://themi.test", secure_cookies=False),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=web), base_url="http://themi.test")


async def test_a_module_left_out_takes_its_page_and_menu_entry_with_it(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    modules = [m for m in family_modules() if m.name not in ("safeway", "spending")]
    app = build(family, fake_telegram, modules)
    async with site(app) as client:
        token = WebAuth(app.store).create_link_token(family.erin)
        await client.post(f"/login/{token}")
        assert (await client.get("/safeway")).status_code == 404
        assert (await client.get("/spending")).status_code == 404
        more = (await client.get("/more")).text
        assert "Safeway" not in more and "Spending" not in more
        assert "Recipes" in more and (await client.get("/recipes")).status_code == 200


def test_two_entries_for_one_page_are_refused() -> None:
    import pytest

    with pytest.raises(ValueError, match="two menu entries for /ai"):
        Menu([*CORE_MENU, CORE_MENU[2]])
