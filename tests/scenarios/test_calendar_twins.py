"""F34e (Erin's idea #175): Themi spots the same event twice after a calendar read and
offers to merge it, once. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_calendar_events import local, on_primary
from tests.scenarios.test_triage import ERIN, link
from themi.accounts import SYSTEM
from themi.core import keys
from themi.core.calendar_view import CalendarPreferences

VISIT = "Return Patient Visit with Thuc Quyen Nguyen, MD"
WHERE = ["Keep on mine", "Keep on family", "Keep on both", "Your call", "Not the same"]


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


def family(scenario: Scenario, fake: FakeGcal) -> str:
    """The family calendar, read along with her own."""
    calendar = fake.add_calendar(ERIN, "Madicen Family")
    db = scenario.app.db
    account = db.scalar("SELECT id FROM linked_accounts WHERE member_id = ?",
                        (scenario.member("Erin").id,))  # fmt: skip
    db.execute(
        "INSERT INTO calendars (account_id, name, calendar_id) VALUES (?, 'Madicen Family', ?)",
        (account, calendar),
    )
    calendars = scenario.app.services.maybe(keys.calendars)
    assert calendars is not None
    calendars.choose(account, [("primary", "primary"), (calendar, "Madicen Family")])
    return calendar


async def read(scenario: Scenario) -> list[str]:
    before = len(scenario.inbox("Erin"))
    await scenario.run_periodic("calendar.busy")
    await scenario.app.outbox.flush()
    return scenario.inbox("Erin")[before:]


async def placeholder_and_visit(scenario: Scenario, fake: FakeGcal) -> None:
    """Bug #174's two: her placeholder on the family calendar, the clinic's on her own."""
    fake.add_event(ERIN, local(13, day=28), local(14, day=28), summary="ND psych in person",
                   calendar=family(scenario, fake), description="Ask about the forms")  # fmt: skip
    fake.add_event(ERIN, local(13, day=28), local(13, 30, day=28), summary=VISIT,
                   location="401 Quarry Rd Palo Alto", description="Arrive early")  # fmt: skip


async def test_a_placeholder_and_the_full_event_get_one_card(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await placeholder_and_visit(scenario, linked)
    sent = await read(scenario)
    assert len(sent) == 1
    assert sent[0].startswith("These look like the same thing, on Wed 28 Oct:")
    assert "ND psych in person, 1-2 pm (the family calendar)" in sent[0]
    assert f"{VISIT}, 1-1:30 pm (your calendar)" in sent[0]
    assert scenario.last_buttons("Erin") == WHERE
    assert await read(scenario) == []  # asked once

    await scenario.tap("Erin", "Keep on mine")
    assert linked.events(ERIN, "Madicen Family") == []
    kept = on_primary(linked)[VISIT]
    assert kept["location"] == "401 Quarry Rd Palo Alto"
    assert kept["description"] == "Arrive early\nAsk about the forms"
    assert scenario.edits("Erin")[-1]["text"].startswith("Merged into one event on your calendar")


async def test_keep_on_both_gives_both_the_details_and_isnt_asked_again(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await placeholder_and_visit(scenario, linked)
    await read(scenario)
    await scenario.tap("Erin", "Keep on both")
    (copy,) = linked.events(ERIN, "Madicen Family")
    assert copy["summary"] == VISIT and copy["location"] == "401 Quarry Rd Palo Alto"
    assert await read(scenario) == []


async def test_not_the_same_leaves_them_and_isnt_asked_again(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await placeholder_and_visit(scenario, linked)
    await read(scenario)
    await scenario.tap("Erin", "Not the same")
    assert len(linked.events(ERIN, "Madicen Family")) == 1 and VISIT in on_primary(linked)
    assert await read(scenario) == []


async def test_identical_twins_on_one_calendar_are_merged_and_told_once(
    scenario: Scenario, linked: FakeGcal
) -> None:
    for _ in range(2):
        linked.add_event(ERIN, local(15, day=27), local(16, day=27), summary="Dentist",
                         location="Smile Dental")  # fmt: skip
    sent = await read(scenario)
    assert sent == ["Dentist was on your calendar twice on Tue 27 Oct, so it's one event now."]
    assert [e["summary"] for e in linked.events(ERIN, ERIN)] == ["Dentist"]
    assert await read(scenario) == []


def meeting(fake: FakeGcal, summary: str, **extra: Any) -> None:
    fake.add_event(ERIN, local(10, day=26), local(11, day=26), summary=summary, **extra)


async def test_meetings_series_and_unrelated_events_are_left_alone(
    scenario: Scenario, linked: FakeGcal
) -> None:
    guests = [{"email": ERIN, "self": True}, {"email": "boss@example.com"}]
    meeting(linked, "Planning", attendees=guests)
    meeting(linked, "Planning", attendees=guests)
    meeting(linked, "Standup", recurringEventId="series1")
    meeting(linked, "Standup", recurringEventId="series1")
    meeting(linked, "Lunch with Sam")
    meeting(linked, "Call mom")
    assert await read(scenario) == []


async def test_keep_both_as_the_setting_asks_nothing(scenario: Scenario, linked: FakeGcal) -> None:
    scenario.app.store.save_preferences(
        SYSTEM, scenario.member("Erin").id, CalendarPreferences, calendar_twins="keep"
    )
    await placeholder_and_visit(scenario, linked)
    assert await read(scenario) == []
    assert len(linked.events(ERIN, "Madicen Family")) == 1


async def test_best_guess_merges_says_where_and_can_be_undone(
    scenario: Scenario, linked: FakeGcal
) -> None:
    scenario.app.store.save_preferences(
        SYSTEM, scenario.member("Erin").id, CalendarPreferences, calendar_twins="guess"
    )
    await placeholder_and_visit(scenario, linked)
    (sent,) = await read(scenario)
    assert sent.startswith(f"Merged ND psych in person into {VISIT}, Wed 28 Oct, 1-1:30 pm")
    assert sent.endswith(", on your calendar. Undo is here for a day.")
    assert scenario.last_buttons("Erin") == ["Undo"]
    assert linked.events(ERIN, "Madicen Family") == []

    await scenario.tap("Erin", "Undo")
    (back,) = linked.events(ERIN, "Madicen Family")
    assert back["summary"] == "ND psych in person"
    assert on_primary(linked)[VISIT]["end"]["dateTime"].startswith("2026-10-28T13:30")
    assert await read(scenario) == []  # not asked about again


async def test_untitled_meetings_are_never_the_same_thing(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """F38a (bug #190): a work calendar that shows Themi no titles. Three untitled meetings
    overlapping on Monday, two of them at the very same times: no card, nothing merged."""
    linked.add_event(ERIN, local(11, 30, day=26), local(15, day=26), summary="")
    linked.add_event(ERIN, local(12, day=26), local(13, day=26), summary="")
    linked.add_event(ERIN, local(12, day=26), local(13, day=26), summary="")
    assert await read(scenario) == []
    assert len(linked.events(ERIN, ERIN)) == 3
