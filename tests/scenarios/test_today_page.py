"""DC7: today's picture on the website's dashboard, for the signed-in member alone."""

from __future__ import annotations

import httpx

from tests.fakes.gcal_api import FakeGcal
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import linked
from tests.scenarios.test_morning_message import at, to
from tests.scenarios.test_triage import ERIN

__all__ = ["linked"]


async def erins_dentist(scenario: Scenario, fake: FakeGcal) -> None:
    to(at(9))
    fake.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist <3>")
    await scenario.run_periodic("calendar.busy")


async def test_the_dashboard_shows_todays_picture(
    scenario: Scenario, linked: FakeGcal, site: httpx.AsyncClient
) -> None:
    await erins_dentist(scenario, linked)
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/")).text
    assert "<h2>Today</h2>" in page
    card = page[page.index('<div class="today-card"') :]
    card = card[: card.index("</svg>")]
    assert "<svg" in card and "Thursday 22 October" in card
    assert "Dentist &lt;3&gt;" in card  # words from the calendar stay words
    assert "<script" not in card


async def test_no_one_else_sees_it(
    scenario: Scenario, linked: FakeGcal, site: httpx.AsyncClient
) -> None:
    await erins_dentist(scenario, linked)  # Erin's calendar details are hers alone
    await sign_in(scenario, site, "Husband")
    page = (await site.get("/")).text
    assert "<h2>Today</h2>" in page
    assert "Dentist" not in page
    assert "Erin\u2019s day" not in page
