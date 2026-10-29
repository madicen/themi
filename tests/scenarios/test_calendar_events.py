"""K3: events made and changed from chat, and suggested by booking emails. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, link, verdict
from themi.ai.types import ToolResult
from themi.autonomy.engine import Decision

PACIFIC = ZoneInfo("America/Los_Angeles")


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


async def say(scenario: Scenario, said: str, tool: str, args: dict[str, Any]) -> list[str]:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Done.")
    return await scenario.say("Erin", said)


def dentist(**changes: str) -> dict[str, str]:
    return {
        "title": "Dentist",
        "date": "2026-10-27",
        "start": "15:00",
        "end": "",
        "location": "Smile Dental",
        "calendar": "mine",
    } | changes


def on_primary(fake: FakeGcal) -> dict[str, dict[str, Any]]:
    return {e["summary"]: e for e in fake.events(ERIN, ERIN)}


async def test_asked_for_its_made_at_once_and_read_back(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await say(
        scenario,
        "Put the dentist on my calendar Tuesday at 3, at Smile Dental",
        "add_calendar_event",
        dentist(),
    )
    assert "On your calendar: Dentist, Tue 27 Oct, 3-4 pm (at Smile Dental)." in tool_result(
        scenario
    )
    event = on_primary(linked)["Dentist"]
    assert event["start"]["dateTime"] == local(15, day=27)
    assert event["location"] == "Smile Dental"
    assert event["extendedProperties"]["private"]["themi"].startswith("event:")
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "thanks")
    context = scenario.primary.last_request.messages[0].content[0].text  # type: ignore[union-attr]
    assert "Dentist" not in context  # Tuesday is beyond today and tomorrow
    rows = scenario.app.db.query("SELECT title, source FROM calendar_entries")
    assert [(r["title"], r["source"][:6]) for r in rows] == [("Dentist", "event:")]  # known now


async def test_mentioned_but_not_asked_its_a_card(scenario: Scenario, linked: FakeGcal) -> None:
    replies = await say(
        scenario,
        "The plumber's coming Thursday morning",
        "add_calendar_event",
        dentist(title="Plumber", date="2026-10-22", start="09:00", location=""),
    )
    assert replies[0] == "Plumber, Thu 22 Oct, 9-10 am, for your calendar\nGo ahead, or not now?"
    assert "Plumber" not in on_primary(linked)
    await scenario.tap("Erin", "Go ahead")
    assert "Plumber" in on_primary(linked)


async def test_unclear_or_past_times_are_refused(scenario: Scenario, linked: FakeGcal) -> None:
    await say(
        scenario,
        "Put the dentist on my calendar",
        "add_calendar_event",
        dentist(date="next tuesday"),
    )
    assert "isn't a date. Try a date like 2026-11-03" in tool_result(scenario)
    await say(
        scenario, "Put the dentist on my calendar", "add_calendar_event", dentist(date="2026-10-01")
    )
    assert "has already gone by" in tool_result(scenario)
    await say(
        scenario,
        "Put the dentist on my calendar",
        "add_calendar_event",
        dentist(start="15:00", end="14:00"),
    )
    assert "comes before the start" in tool_result(scenario)
    assert on_primary(linked) == {}


async def test_themis_own_events_change_at_once_others_ask_first(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await say(
        scenario, "Put the dentist on my calendar Tuesday at 3", "add_calendar_event", dentist()
    )
    await say(
        scenario,
        "Move the dentist to 4",
        "move_calendar_event",
        {"event": "dentist", "on": "", "date": "2026-10-27", "start": "16:00", "end": ""},
    )
    assert "Moved: Dentist, Tue 27 Oct, 4-5 pm" in tool_result(scenario)
    assert on_primary(linked)["Dentist"]["start"]["dateTime"] == local(16, day=27)

    linked.add_event(ERIN, local(14), local(15), summary="Team sync", description="Agenda inside")
    await scenario.run_periodic("calendar.busy")
    replies = await say(
        scenario,
        "Move my 2pm meeting to 3",
        "move_calendar_event",
        {
            "event": "team sync",
            "on": "2026-10-21",
            "date": "2026-10-21",
            "start": "15:00",
            "end": "16:00",
        },
    )
    assert replies[0] == "Moving Team sync to Wed 21 Oct, 3-4 pm\nGo ahead, or not now?"
    assert on_primary(linked)["Team sync"]["start"]["dateTime"] == local(14)  # untouched yet
    await scenario.tap("Erin", "Go ahead")
    sync = on_primary(linked)["Team sync"]
    assert sync["start"]["dateTime"] == local(15) and sync["description"] == "Agenda inside"

    await say(
        scenario, "Cancel the dentist", "delete_calendar_event", {"event": "dentist", "on": ""}
    )
    assert "Dentist" not in on_primary(linked)


async def test_the_family_calendar(scenario: Scenario, linked: FakeGcal) -> None:
    await say(
        scenario,
        "Put the block party on the family calendar Saturday",
        "add_calendar_event",
        dentist(title="Block party", date="2026-10-24", start="", location="", calendar="family"),
    )
    (event,) = linked.events(ERIN, "Themi")
    assert (event["summary"], event["start"]) == ("Block party", {"date": "2026-10-24"})
    assert "On the family calendar: Block party, Sat 24 Oct, all day." in tool_result(scenario)


async def test_booking_emails_become_cards_then_an_offer_then_automatic(
    scenario: Scenario,
    linked: FakeGcal,
    fake_gmail: FakeGmail,
) -> None:
    await scenario.tap("Erin", "Watch it")
    await scenario.run_periodic("gmail.poll")

    async def booking(n: int) -> None:
        (email,) = await arrive(
            scenario,
            fake_gmail,
            {
                "sender": "Pet Clinic <hi@pets.example>",
                "subject": f"Booked #{n}",
                "text": "See you",
            },
        )
        event = {"title": f"Vet visit {n}", "date": f"2026-10-{25 + n}", "start": "10:00",
                 "end": "10:30", "location": "Pet Clinic"}  # fmt: skip
        scenario.primary.queue_structured(
            {"results": [verdict(email, "confirmation", "Vet booking", event=event)]}
        )
        await scenario.run_periodic("email.triage")

    await booking(1)
    cards = [t for t in scenario.inbox("Erin") if t.startswith("From an email:")]
    assert cards == [
        "From an email: Vet visit 1, Mon 26 Oct, 10-10:30 am (at Pet Clinic), for your "
        "calendar\nGo ahead, or not now?"
    ]

    async def approve_calendar_card() -> None:  # the mark-as-read card comes after it
        (row,) = scenario.app.db.query(
            "SELECT id FROM pending_actions WHERE category = 'calendar_from_email' "
            "AND status = 'pending'"
        )
        await scenario.app.services.autonomy.resolve(
            row["id"], Decision.APPROVE, by=scenario.member("Erin")
        )

    for n in (1, 2, 3):
        if n > 1:
            await booking(n)
        await approve_calendar_card()
    assert {f"Vet visit {n}" for n in (1, 2, 3)} <= set(on_primary(linked))
    assert any("from my booking emails" in t for t in scenario.inbox("Erin"))  # the offer

    await scenario.tap("Erin", "Lock it in")
    await booking(4)
    assert "Vet visit 4" in on_primary(linked)  # no card this time
    said = scenario.app.db.query("SELECT text FROM outbox WHERE kind = 'calendar'")
    assert [r["text"] for r in said] == [  # sent, or waiting for a good moment
        "Added to your calendar from an email: Vet visit 4, Thu 29 Oct, 10-10:30 am (at Pet "
        "Clinic)."
    ]


async def test_a_newer_card_for_the_same_event_takes_the_older_ones_place(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """Bug #35: fixing the time staged a second card and left the first waiting, so a later
    "go ahead" made the old one too."""
    party = dentist(
        title="Block party", date="2026-10-24", start="", location="", calendar="family"
    )
    await say(scenario, "There's a block party Saturday", "add_calendar_event", party)
    replies = await say(
        scenario, "It's at 2, actually", "add_calendar_event", party | {"start": "14:00"}
    )
    assert (
        replies[0]
        == "Block party, Sat 24 Oct, 2-3 pm, for the family calendar\nGo ahead, or not now?"
    )
    (edit,) = scenario.edits("Erin")
    assert edit["text"] == (
        "Block party, Sat 24 Oct, all day, for the family calendar\nReplaced by the newer card."
    )
    assert not edit.get("reply_markup", {}).get("inline_keyboard")
    waiting = scenario.app.db.query(
        "SELECT summary FROM pending_actions WHERE status IN ('pending', 'snoozed')"
    )
    assert [r["summary"] for r in waiting] == [
        "Block party, Sat 24 Oct, 2-3 pm, for the family calendar"
    ]
    await scenario.tap("Erin", "Go ahead")
    assert [e["start"] for e in linked.events(ERIN, "Themi")] == [
        {"dateTime": local(14, day=24), "timeZone": "America/Los_Angeles"}
    ]


async def test_an_event_already_on_the_calendar_isnt_added_again(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """Bug #35: "go ahead and add to calendar" staged a third copy of the lunch."""
    party = dentist(title="Block party", date="2026-10-24", start="14:00", location="")
    await say(
        scenario, "Put the block party on my calendar Saturday at 2", "add_calendar_event", party
    )
    await say(scenario, "Go ahead and add it to my calendar", "add_calendar_event", party)
    assert "Already on your calendar: Block party, Sat 24 Oct, 2-3 pm." in tool_result(scenario)
    await say(
        scenario,
        "Put the block party on my calendar Saturday at 4",
        "add_calendar_event",
        party | {"start": "16:00"},
    )
    assert "already on your calendar (Sat 24 Oct, 2-3 pm)" in tool_result(scenario)
    assert "move_calendar_event" in tool_result(scenario)
    assert len(on_primary(linked)) == 1
    assert not scenario.app.db.query("SELECT 1 FROM pending_actions WHERE status = 'pending'")


@pytest.mark.parametrize(
    ("title", "starts"),
    [("Lunch at Merit", "12:00"), ("Dinner with the Parks", "18:00"), ("Brunch", "10:30")],
)
async def test_a_meal_without_a_time_gets_its_usual_one(
    scenario: Scenario, linked: FakeGcal, title: str, starts: str
) -> None:
    """Bug #35: "a lunch at Merit this Sunday" was all day."""
    await say(
        scenario,
        f"Put {title.lower()} on my calendar Sunday",
        "add_calendar_event",
        dentist(title=title, date="2026-10-25", start="", location=""),
    )
    event = on_primary(linked)[title]
    assert event["start"]["dateTime"][11:16] == starts
