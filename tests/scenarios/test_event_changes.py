"""F29a: an event's place, title and notes change, on every copy of it (bugs #149, #154,
#158, idea #150). The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_calendar_events import dentist, local, on_primary, say, tool_result
from tests.scenarios.test_triage import ERIN, link
from themi.core.agent import FAILED_TEXT, NOTHING_CHANGED_TEXT
from themi.core.calendar_view import CalendarPreferences


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


SETUP = "Starts at 4:00 pm. The time before it is set-up time."


def change(**changes: str) -> dict[str, str]:
    return {
        "event": "tutoring",
        "on": "",
        "calendar": "",
        "date": "",
        "start": "",
        "end": "",
        "location": "",
        "title": "",
        "notes": "",
        "notes_mode": "",
    } | changes


async def tutoring(scenario: Scenario, calendar: str = "mine") -> None:
    await say(
        scenario,
        f"Put Tutor Gabriel (Illems) on {'my' if calendar == 'mine' else 'the family'} "
        "calendar Thursday 4-4:55",
        "add_calendar_event",
        dentist(
            title="Tutor Gabriel (Illems)", date="2026-10-22", start="16:00", end="16:55",
            location="", calendar=calendar,
        ),
    )  # fmt: skip


def family_events(fake: FakeGcal) -> dict[str, dict[str, Any]]:
    return {e["summary"]: e for e in fake.events(ERIN, "Themi")}


async def test_a_location_on_themis_own_event_changes_at_once_title_kept(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await tutoring(scenario)
    await say(
        scenario,
        "Set the location on tutoring to 790 La Para Ave",
        "change_calendar_event",
        change(location="790 La Para Ave"),
    )
    assert (
        "Changed: Tutor Gabriel (Illems), Thu 22 Oct, 4-4:55 pm (at 790 La Para Ave)."
        in tool_result(scenario)
    )
    event = on_primary(linked)["Tutor Gabriel (Illems)"]
    assert event["location"] == "790 La Para Ave"
    assert event["start"]["dateTime"] == local(16, day=22)  # the time stays
    assert scenario.app.db.scalar("SELECT location FROM themi_events") == "790 La Para Ave"


async def test_someone_elses_event_asks_with_only_the_change(
    scenario: Scenario, linked: FakeGcal
) -> None:
    linked.add_event(ERIN, local(14), local(15), summary="Team sync", description="Agenda inside")
    await scenario.run_periodic("calendar.busy")
    replies = await say(
        scenario,
        "Put the team sync in room 4",
        "change_calendar_event",
        change(event="team sync", location="Room 4"),
    )
    assert replies[0] == (
        "Team sync, Wed 21 Oct, 2-3 pm: location to Room 4\nGo ahead, or not now?"
    )
    await scenario.tap("Erin", "Go ahead")
    sync = on_primary(linked)["Team sync"]
    assert sync["location"] == "Room 4" and sync["description"] == "Agenda inside"
    assert sync["start"]["dateTime"] == local(14)


async def test_the_same_event_on_both_calendars_changes_on_both(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """Bug #154: a copy on the family calendar made every change "more than one matches"."""
    await tutoring(scenario)
    await tutoring(scenario, "family")
    await say(
        scenario,
        "Set the location on the tutoring events to 790 La Para Ave",
        "change_calendar_event",
        change(location="790 La Para Ave"),
    )
    assert "(on both calendars)" in tool_result(scenario)
    assert on_primary(linked)["Tutor Gabriel (Illems)"]["location"] == "790 La Para Ave"
    assert family_events(linked)["Tutor Gabriel (Illems)"]["location"] == "790 La Para Ave"
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM pending_actions WHERE executor = "
                                  "'calendar.move_event'") == 1  # fmt: skip

    await say(
        scenario, "Change only the family one's title", "change_calendar_event",
        change(calendar="family", title="Tutoring"),
    )  # fmt: skip
    assert "Tutoring" in family_events(linked)
    assert "Tutor Gabriel (Illems)" in on_primary(linked)  # the other copy keeps its title

    await say(
        scenario, "Delete tutoring", "delete_calendar_event",
        {"event": "tutor", "on": "", "calendar": "mine"},
    )  # fmt: skip
    assert on_primary(linked) == {} and "Tutoring" in family_events(linked)


async def test_notes_are_added_and_replaced(scenario: Scenario, linked: FakeGcal) -> None:
    linked.add_event(ERIN, local(14), local(15), summary="Team sync", description="Agenda inside")
    await scenario.run_periodic("calendar.busy")
    await say(
        scenario, "Note on team sync: bring the deck", "change_calendar_event",
        change(event="team sync", notes="Bring the deck", notes_mode="add"),
    )  # fmt: skip
    await scenario.tap("Erin", "Go ahead")
    assert on_primary(linked)["Team sync"]["description"] == "Agenda inside\nBring the deck"
    await say(
        scenario, "Make its notes just: room 4", "change_calendar_event",
        change(event="team sync", notes="Room 4", notes_mode="replace"),
    )  # fmt: skip
    await scenario.tap("Erin", "Go ahead")
    assert on_primary(linked)["Team sync"]["description"] == "Room 4"


async def test_an_earlier_start_notes_the_real_one(scenario: Scenario, linked: FakeGcal) -> None:
    """Idea #150: tutoring moved to 3:30 for set-up says it starts at 4, and keeps saying so."""
    await tutoring(scenario)
    await say(
        scenario, "Start tutoring at 3:30, I need set-up time", "change_calendar_event",
        change(date="2026-10-22", start="15:30", end="16:55"),
    )  # fmt: skip
    event = on_primary(linked)["Tutor Gabriel (Illems)"]
    assert event["start"]["dateTime"] == local(15, 30, day=22)
    assert event["description"] == SETUP
    await say(
        scenario, "Even more set-up time", "change_calendar_event",
        change(date="2026-10-22", start="15:00", end="16:55"),
    )  # fmt: skip
    assert on_primary(linked)["Tutor Gabriel (Illems)"]["description"] == SETUP  # still 4
    await say(
        scenario, "Back to 4", "change_calendar_event",
        change(date="2026-10-22", start="16:00", end="16:55"),
    )  # fmt: skip
    assert on_primary(linked)["Tutor Gabriel (Illems)"]["description"] == ""


async def test_the_set_up_note_can_be_turned_off(scenario: Scenario, linked: FakeGcal) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, CalendarPreferences, setup_note=False)
    await tutoring(scenario)
    await say(
        scenario, "I need extra time to set up", "change_calendar_event",
        change(date="2026-10-22", start="15:30", end="16:55"),
    )  # fmt: skip
    assert not on_primary(linked)["Tutor Gabriel (Illems)"].get("description")


async def test_reply_258_a_change_that_changes_nothing_isnt_called_done(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await tutoring(scenario)
    scenario.primary.queue_tool_call(
        "change_calendar_event", change(date="2026-10-22", start="16:00", end="16:55")
    )
    scenario.primary.queue_text(
        'Updated the event description for "Tutor Gabriel (Illems)" today to note that the '
        "session starts at 4:00 PM."
    )
    replies = await scenario.say(
        "Erin", "Can you update the tutoring calendar event today to include a note?"
    )
    assert "is like that already" in tool_result(scenario)
    assert replies == [NOTHING_CHANGED_TEXT]


async def test_reply_276_location_updated_after_every_call_failed(
    scenario: Scenario, linked: FakeGcal
) -> None:
    scenario.primary.queue_tool_call(
        "change_calendar_event", change(event="Tutor Gabriel", location="My parent's house")
    )  # no such event: it fails
    scenario.primary.queue_text("Location updated to your parent's house on the tutoring events.")
    replies = await scenario.say(
        "Erin", "Set the location on the tutoring events to my parent's house"
    )
    assert replies == [FAILED_TEXT]


async def test_the_old_tool_name_still_works(scenario: Scenario, linked: FakeGcal) -> None:
    await tutoring(scenario)
    await say(
        scenario, "Move tutoring to 5", "move_calendar_event",
        {"event": "tutoring", "on": "", "date": "2026-10-22", "start": "17:00", "end": ""},
    )  # fmt: skip
    assert "Moved: Tutor Gabriel (Illems), Thu 22 Oct, 5-6 pm." in tool_result(scenario)


async def test_bug_158_the_location_alone(scenario: Scenario, linked: FakeGcal) -> None:
    """Bug #158: "set the location of the tutoring calendar event to be my in law's house"
    staged a delete and a new event with another title. Now it's one change, on both."""
    await tutoring(scenario)
    await tutoring(scenario, "family")
    replies = await say(
        scenario, "Set the location of the tutoring event to 790 La Para Ave",
        "change_calendar_event", change(location="790 La Para Ave"),
    )  # fmt: skip
    assert len(replies) == 1  # no cards: both are Themi's
    assert {e["summary"] for e in on_primary(linked).values()} == {"Tutor Gabriel (Illems)"}
    assert {e["location"] for e in family_events(linked).values()} == {"790 La Para Ave"}
