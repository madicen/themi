"""CR18a: linking a Google account asks for what the loaded modules need, and no more.
An account linked before a module came is asked to link again for it."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.slack_api import FakeSlack
from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.slack_harness import SlackScenario
from tests.scenarios.test_triage import ERIN
from tests.scenarios.test_work_template import work_app
from themi.app import family_modules
from themi.core import keys
from themi_google.connectors.google import (
    CALENDAR_SCOPES,
    DRIVE_FILE_SCOPE,
    GMAIL_SCOPE,
    TASKS_SCOPE,
)
from themi_google.connectors.google.oauth import LINK_SCOPES


def asked(scenario: Scenario | SlackScenario) -> list[str]:
    google = scenario.app.services.get(keys.google)
    member = scenario.app.store.list_members()[0]
    url = google.link_url(member, "http://themi.test/auth/google/callback")
    return parse_qs(urlsplit(url).query)["scope"][0].split()


def test_the_work_template_asks_for_gmail_calendar_and_tasks_not_drive(
    tmp_path: Path, fake_slack: FakeSlack
) -> None:
    scenario = work_app(
        tmp_path, fake_slack, {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}
    )
    scopes = asked(scenario)
    assert scopes == ["openid", "email", GMAIL_SCOPE, *CALENDAR_SCOPES, TASKS_SCOPE]
    assert DRIVE_FILE_SCOPE not in scopes


@pytest.mark.usefixtures("fake_google")
def test_the_family_asks_for_everything_as_before(scenario: Scenario) -> None:
    assert asked(scenario) == list(LINK_SCOPES)


def test_without_the_cookbook_drive_isnt_asked(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_google: FakeGoogle
) -> None:
    dependents = {
        "recipes",
        "cookbook_save",
        "recipe_groceries",
        "recipe_ideas",
        "cooking",
        "web_recipes",
        "meals",
        "expense_sync",
    }  # fmt: skip — EX4a: expense sheets use Drive too
    modules = family_modules(**connector_options(google=fake_google))
    gone = {m.name for m in modules if m.name in dependents}
    while needing := [m for m in modules if m.name not in gone and gone & set(m.requires)]:
        gone |= {m.name for m in needing}
    assert "recipes" in gone
    scenario = Scenario(
        family, fake_telegram, fake_google, modules=[m for m in modules if m.name not in gone]
    )
    assert DRIVE_FILE_SCOPE not in asked(scenario)
    assert GMAIL_SCOPE in asked(scenario)


async def test_an_account_linked_before_the_cookbook_is_asked_to_link_again_for_it(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    """As if the cookbook came after the link: the account allows all but Drive."""
    (reply,) = await scenario.say("Erin", "/link gmail")
    assert DRIVE_FILE_SCOPE in unquote(reply)  # the next link asks for it
    before = tuple(s for s in LINK_SCOPES if s != DRIVE_FILE_SCOPE)
    callback = urlsplit(fake_google.consent(reply.splitlines()[-1], ERIN, scopes=before))
    await site.get(f"{callback.path}?{callback.query}")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/accounts")).text
    assert "Link again for the cookbook" in page
    assert "Link again for Google Tasks" not in page  # that one it allows
