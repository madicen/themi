"""F42d (Michael's idea #200): the morning message lists the person's own events and the
family calendar's; their partner's are behind an "Everyone's calendar" button. Erin's
morning message is set for 7:15 on Thursday 22 October, so it goes at 8, when her quiet
hours end."""

from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import HUSBAND, PACIFIC, linked
from tests.scenarios.test_morning_message import edited_buttons, to
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.core import keys
from themi.core.calendar_view import CalendarPreferences
from themi.standard.day_summary import DaySummaryPreferences

__all__ = ["linked"]

THU = date(2026, 10, 22)
FAMILY = "family@group.calendar.google.com"


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 22, hour, minute, tzinfo=PACIFIC)


@pytest.fixture
async def both(
    scenario: Scenario, linked: FakeGcal, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Husband", HUSBAND)
    husband = scenario.member("Husband")
    scenario.app.store.save_preferences(
        husband, husband.id, CalendarPreferences, calendar_details="partner"
    )
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="07:15"
    )
    to(at(6))
    return linked


def family_bins(scenario: Scenario) -> None:
    db = scenario.app.db
    for member in (scenario.member("Erin"), scenario.member("Husband")):
        account = db.scalar("SELECT id FROM linked_accounts WHERE member_id = ?", (member.id,))
        db.execute(
            "INSERT INTO member_calendars (account_id, calendar_id, name) VALUES (?, ?, ?)",
            (account, FAMILY, "Madicen Family"),
        )
        db.execute(
            "INSERT INTO calendar_entries (member_id, account_id, calendar_id, event_id, title, "
            "location, starts_at, ends_at, all_day, video, busy, source, fetched_at) "
            "VALUES (?, ?, ?, 'bins', 'Take out Waste Bins', '', ?, ?, 1, 0, 0, NULL, ?)",
            (
                member.id, account, FAMILY, "2026-10-22T07:00:00+00:00",
                "2026-10-23T07:00:00+00:00", clock.now().isoformat(),
            ),
        )  # fmt: skip


async def morning(scenario: Scenario) -> list[str]:
    to(at(7, 15))
    await scenario.run_periodic("calendar.morning")
    return await scenario.advance(minutes=45)


async def test_her_day_and_the_familys_and_his_behind_a_button(
    scenario: Scenario, both: FakeGcal
) -> None:
    both.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist")
    both.add_event(HUSBAND, at(16, 30).isoformat(), at(17).isoformat(), summary="Tea Time!")
    await scenario.run_periodic("calendar.busy")
    family_bins(scenario)
    assert await morning(scenario) == [
        "Morning, Erin.\nThu 22 Oct:\n"
        "- all day: Take out Waste Bins (on the Madicen Family calendar)\n"
        "- 10-11 am: Dentist"
    ]
    assert scenario.last_buttons("Erin")[0] == "Everyone's calendar"
    assert await scenario.tap("Erin", "Everyone's calendar") == [
        "Husband's day, Thu 22 Oct:\n- 4:30-5 pm: Tea Time!"
    ]
    assert "Everyone's calendar" not in edited_buttons(scenario)


async def test_no_button_when_he_has_nothing(scenario: Scenario, both: FakeGcal) -> None:
    both.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist")
    await scenario.run_periodic("calendar.busy")
    await morning(scenario)
    assert "Everyone's calendar" not in scenario.last_buttons("Erin")


async def test_only_his_day_still_sends_with_the_button(scenario: Scenario, both: FakeGcal) -> None:
    both.add_event(HUSBAND, at(16, 30).isoformat(), at(17).isoformat(), summary="Tea Time!")
    await scenario.run_periodic("calendar.busy")
    assert await morning(scenario) == ["Morning, Erin. Nothing on your calendar today."]
    assert scenario.last_buttons("Erin") == ["Everyone's calendar"]


async def test_the_day_card_draws_the_same_events(scenario: Scenario, both: FakeGcal) -> None:
    both.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist")
    both.add_event(HUSBAND, at(16, 30).isoformat(), at(17).isoformat(), summary="Tea Time!")
    await scenario.run_periodic("calendar.busy")
    card = scenario.app.services.get(keys.drawings).day_card
    titles = [e.title for e in card.data(scenario.member("Erin"), THU).events]
    assert "Dentist" in titles and not any(t.startswith("Tea Time!") for t in titles)


async def test_his_details_kept_to_himself_mean_no_button(
    scenario: Scenario, both: FakeGcal
) -> None:
    husband = scenario.member("Husband")
    scenario.app.store.save_preferences(
        husband, husband.id, CalendarPreferences, calendar_details="me"
    )
    both.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist")
    both.add_event(HUSBAND, at(16, 30).isoformat(), at(17).isoformat(), summary="Tea Time!")
    await scenario.run_periodic("calendar.busy")
    await morning(scenario)
    assert "Everyone's calendar" not in scenario.last_buttons("Erin")
