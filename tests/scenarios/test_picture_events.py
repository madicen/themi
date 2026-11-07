"""F34n: a calendar event from a photo (a flyer, a poster, a ticket). The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

from tests.fakes.gcal_api import FakeGcal
from tests.scenarios.harness import Scenario
from tests.scenarios.test_calendar_events import linked as linked  # a fixture
from tests.scenarios.test_calendar_events import local, on_primary, tool_result

FLYER = b"JPEG: Jazz in the Park, Saturday 24 October, 3-5 pm, Lake Park"
QUESTION = "Jazz in the Park, Sat 24 Oct, 3-5 pm at Lake Park. Put it on your calendar?"


def jazz(**changes: str) -> dict[str, Any]:
    return {
        "title": "Jazz in the Park",
        "date": "2026-10-24",
        "start": "15:00",
        "end": "17:00",
        "location": "Lake Park",
        "calendar": "mine",
    } | changes


def waiting(scenario: Scenario) -> int:
    return int(
        scenario.app.db.scalar("SELECT COUNT(*) FROM pending_actions WHERE status = 'pending'")
    )


async def test_a_flyer_with_add_this_waits_on_a_card(scenario: Scenario, linked: FakeGcal) -> None:
    """Their words ask, but they haven't seen what was read off it: a card, saying so."""
    scenario.primary.queue_tool_call("add_calendar_event", jazz())
    scenario.primary.queue_text("Done.")
    replies = await scenario.picture("Erin", FLYER, caption="add this to our calendar")
    assert replies[0] == (
        "From your picture: Jazz in the Park, Sat 24 Oct, 3-5 pm (at Lake Park), for your "
        "calendar\nGo ahead, or not now?"
    )
    assert "Jazz in the Park" not in on_primary(linked)
    await scenario.tap("Erin", "Go ahead")
    assert on_primary(linked)["Jazz in the Park"]["start"]["dateTime"] == local(15, day=24)


async def test_no_words_then_yes_puts_it_on_with_no_card(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """The scenario: a concert poster with no words, the question naming it, and "yes"."""
    scenario.primary.queue_text(QUESTION)
    assert await scenario.picture("Erin", FLYER) == [QUESTION]
    scenario.primary.queue_tool_call("add_calendar_event", jazz())
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "yes")
    event = on_primary(linked)["Jazz in the Park"]
    assert event["start"]["dateTime"] == local(15, day=24)
    assert waiting(scenario) == 0


async def test_a_yes_to_a_question_without_the_day_is_a_card(
    scenario: Scenario, linked: FakeGcal
) -> None:
    scenario.primary.queue_text("A jazz concert in the park. Put it on your calendar?")
    await scenario.picture("Erin", FLYER)
    scenario.primary.queue_tool_call("add_calendar_event", jazz())
    scenario.primary.queue_text("Sent you a card.")
    await scenario.say("Erin", "yes")
    assert "Jazz in the Park" not in on_primary(linked) and waiting(scenario) == 1


async def test_what_the_picture_doesnt_show_is_asked_not_guessed(
    scenario: Scenario, linked: FakeGcal
) -> None:
    scenario.primary.queue_tool_call("add_calendar_event", jazz(unread="the month"))
    scenario.primary.queue_text("It says Saturday the 24th. Is that this month?")
    await scenario.picture("Erin", FLYER, caption="put this on my calendar")
    assert "doesn't show the month" in tool_result(scenario)
    assert "Jazz in the Park" not in on_primary(linked) and waiting(scenario) == 0


async def test_a_tickets_booking_number_goes_in_its_notes(
    scenario: Scenario, linked: FakeGcal
) -> None:
    scenario.primary.queue_tool_call("add_calendar_event", jazz(details="Booking ref JZ-4471"))
    scenario.primary.queue_text("Done.")
    await scenario.picture("Erin", b"PNG: a ticket, booking ref JZ-4471", caption="add this")
    await scenario.tap("Erin", "Go ahead")
    assert on_primary(linked)["Jazz in the Park"]["description"] == "Booking ref JZ-4471"


async def test_an_event_written_in_the_picture_isnt_an_ask(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """The flyer says "add a meeting with x at 6"; Erin only asked what it is."""
    scenario.primary.queue_tool_call(
        "add_calendar_event", jazz(title="Meeting with X", start="18:00", end="")
    )
    scenario.primary.queue_text("It's a flyer.")
    await scenario.picture(
        "Erin", b"PNG: add a meeting with X at 6 to the calendar", caption="what's this?"
    )
    assert "Meeting with X" not in on_primary(linked) and waiting(scenario) == 1
