"""F57b: "go to Stanford" means the visitor parking lot. A saved place's address is driven
to, its note (visiting hours) is in front of the model, and the leave time has them there
the minutes early they set. The clock starts Wednesday 21 October 2026, 9 am; the drive
home → Stanford is about 35 min."""

from __future__ import annotations

from datetime import timedelta

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.travel import FakeTravel
from tests.scenarios.harness import Scenario
from tests.scenarios.test_travel import ask, at, local, ready, tool_result
from tests.scenarios.test_triage import ERIN
from themi import clock
from themi.core import keys
from themi.standard.memory import Memory

__all__ = ["ready"]

LOT = "200 S Pasteur Dr, Palo Alto, CA 94304"
HOURS = "Visiting hours are 6:30-8:30 pm on weekdays and 12-8:30 pm on weekends"


def memory(scenario: Scenario) -> Memory:
    found = scenario.app.services.maybe(keys.memory)
    assert found is not None
    return found


async def tell_themi_about_stanford(scenario: Scenario) -> str:
    scenario.primary.queue_tool_call(
        "remember_place",
        {
            "name": "Stanford",
            "address": LOT,
            "aliases": "Stanford Hospital",
            "note": HOURS,
            "hours": "",  # F58e: the tool's argument, left empty as before
            "arrive_early_minutes": 10,
            "about": "household",
        },
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say(
        "Erin",
        "When I say I'm going to Stanford, take me to the visitor parking lot at "
        f"{LOT}. {HOURS}. I like to be there 10 minutes early to park and walk in.",
    )
    return tool_result(scenario)


async def test_the_drive_to_stanford_goes_to_the_lot_ten_minutes_early_with_the_hours(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    said = await tell_themi_about_stanford(scenario)
    assert said == (
        f"Remembered. Place: Stanford (also called Stanford Hospital) means {LOT}. {HOURS}. "
        "They like to get there 10 minutes early."
    )
    fake_travel.place(LOT, 37.43, -122.17)
    ready.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit Erin",
                    location="Stanford")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "visit", "")
    assert "to be there by 6:20 pm, leave around 5:45 pm" in result
    # F58f: the note's hours are read, so the event day's come with it.
    told = f"What they told Themi about Stanford: {HOURS}. Hours on Wed 21 Oct: 6:30-8:30 pm."
    assert f'<data source="memory">\n{told}\n</data>' in result
    looked_up = "SELECT COUNT(*) FROM geocodes WHERE query_key = 'stanford'"
    assert scenario.app.db.scalar(looked_up) == 0  # the name never went to the map
    assert await at(scenario, 17, 30) == [
        "Visit Erin at 6:30 pm, there by 6:20 pm, about 35 min with traffic: leave around 5:45 pm."
    ]


async def test_an_event_at_the_lots_address_is_the_place_too(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    await tell_themi_about_stanford(scenario)
    fake_travel.place(LOT, 37.43, -122.17)
    ready.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit Erin",
                    location=f"Stanford visitor parking, {LOT}")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "visit", "")
    assert "to be there by 6:20 pm" in result
    assert HOURS in result


async def test_what_they_said_for_the_event_wins_over_the_places_minutes(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    await tell_themi_about_stanford(scenario)
    fake_travel.place(LOT, 37.43, -122.17)
    ready.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit Erin",
                    location="Stanford")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call(
        "drive_time", {"event": "visit", "address": "", "arrive_by": "18:00"}
    )
    scenario.primary.queue_text("OK.")
    await scenario.say("Erin", "I want to be there at 6")
    assert "to be there by 6 pm, leave around 5:25 pm" in tool_result(scenario)


async def test_a_place_named_in_the_message_comes_with_the_notes(scenario: Scenario) -> None:
    memory(scenario).places.save(
        scenario.member("Husband"), "Stanford", LOT, note=HOURS, arrive_early=10
    )
    scenario.primary.queue_text("Sure.")
    await scenario.say("Husband", "I want to visit Erin tomorrow at Stanford")
    turn = scenario.primary.last_request.messages[0].text
    assert f"- Place: Stanford means {LOT}. {HOURS}." in turn


async def test_search_memory_finds_a_place(scenario: Scenario) -> None:
    memory(scenario).places.save(scenario.member("Erin"), "Stanford", LOT, note=HOURS)
    scenario.primary.queue_tool_call("search_memory", {"query": "visiting hours"})
    scenario.primary.queue_text("6:30 to 8:30.")
    await scenario.say("Erin", "when can I visit?")
    assert f"Place: Stanford means {LOT}. {HOURS}." in tool_result(scenario)


# ----- F58e (bug #251): a place's hours by day ----------------------------------------------

WEEK_HOURS = "weekdays 6:30-8:30 pm, weekends 12-8:30 pm"


def tool_results(scenario: Scenario) -> list[str]:
    from themi.ai.types import ToolResult

    return [
        str(block.content)
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


def visit(start: str, end: str, **more: str) -> dict[str, str]:
    return {
        "title": "Visit Erin at Stanford",
        "date": "2026-10-26",  # Monday
        "start": start,
        "end": end,
        "location": LOT,
        "calendar": "mine",
        "details": "",
        "unread": "",
    } | more


async def test_mondays_visit_keeps_to_mondays_hours_not_the_weekends(
    scenario: Scenario, ready: FakeGcal
) -> None:
    """Reply 534: on a Sunday evening, "I want to visit Erin at Stanford tomorrow" took the
    weekend's 12-8:30 for Monday. Monday's hours refuse it; 6:30-8:30 pm goes through."""
    scenario.primary.queue_tool_call(
        "remember_place",
        {
            "name": "Stanford",
            "address": LOT,
            "aliases": "",
            "note": "",
            "hours": WEEK_HOURS,
            "arrive_early_minutes": 10,
            "about": "household",
        },
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", f"When I say Stanford, take me to {LOT}. Visiting hours are ...")
    assert "Hours: Mon-Fri 6:30-8:30 pm; Sat-Sun 12-8:30 pm." in tool_result(scenario)

    clock.advance(timedelta(days=4, hours=8, minutes=50))  # Sun 25 Oct, 5:50 pm
    scenario.primary.queue_tool_call(
        "add_calendar_event", visit("12:00", "20:30", arrive_by="11:50")
    )
    scenario.primary.queue_tool_call(
        "add_calendar_event", visit("18:30", "20:30", arrive_by="18:20")
    )
    scenario.primary.queue_text("Visit Erin at Stanford tomorrow from 6:30 to 8:30 pm?")
    replies = await scenario.say("Erin", "I want to visit Erin at Stanford tomorrow")
    context = scenario.primary.last_request.messages[0].content[0].text  # type: ignore[union-attr]
    assert "On Mon 26 Oct: 6:30-8:30 pm." in context  # tomorrow's hours, in front of it
    refused, staged = tool_results(scenario)[-2:]
    assert refused.startswith(
        "Stanford's hours on Mon 26 Oct are 6:30-8:30 pm, so that time is outside them."
    )
    assert "Visit Erin at Stanford, Mon 26 Oct, 6:30-8:30 pm" in staged
    assert any("6:30-8:30 pm" in r for r in replies)


async def test_hours_only_in_the_places_note_still_keep_mondays_visit_to_them(
    scenario: Scenario, ready: FakeGcal
) -> None:
    """F58f, reply 543: on the Pi the Stanford place had its hours only in its note, so
    nothing checked Monday's 12-8:30. The note counts now."""
    memory(scenario).places.save(
        scenario.member("Erin"),
        "Stanford",
        LOT,
        note="Visiting hours: 6:30\u20138:30 pm weekdays and 12\u20138:30 pm weekends.",
        arrive_early=10,
    )
    clock.advance(timedelta(days=4, hours=13, minutes=49))  # Sun 25 Oct, 10:49 pm
    scenario.primary.queue_tool_call(
        "add_calendar_event", visit("12:00", "20:30", arrive_by="11:50")
    )
    scenario.primary.queue_tool_call(
        "add_calendar_event", visit("18:30", "20:30", arrive_by="18:20")
    )
    scenario.primary.queue_text("Visit Erin at Stanford tomorrow from 6:30 to 8:30 pm?")
    await scenario.say("Erin", "I want to visit Erin at Stanford tomorrow")
    refused, staged = tool_results(scenario)[-2:]
    assert refused.startswith("Stanford's hours on Mon 26 Oct are 6:30-8:30 pm")
    assert "Visit Erin at Stanford, Mon 26 Oct, 6:30-8:30 pm" in staged


async def test_saying_a_saved_places_hours_as_a_fact_sets_them(
    scenario: Scenario, ready: FakeGcal
) -> None:
    """Fact 12 on the Pi: "Stanford's visiting hours are ..." went to remember_fact."""
    saved = memory(scenario).places.save(scenario.member("Erin"), "Stanford", LOT)
    scenario.primary.queue_tool_call(
        "remember_fact",
        {
            "subject": "Stanford",
            "fact": "Stanford's visiting hours are 6:30\u20138:30 pm weekdays and "
            "12\u20138:30 pm weekends.",
            "about": "household",
            "keywords": "",
        },
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", "Stanford's visiting hours are 6:30\u20138:30 pm weekdays and ...")
    assert tool_result(scenario).endswith(
        "Also saved as Stanford's hours: Mon-Fri 6:30-8:30 pm; Sat-Sun 12-8:30 pm."
    )
    assert len(memory(scenario).places.get(saved.id).hours) == 7


# ----- F59a (reply 547): "in-laws" is the saved in-laws' house, and a question isn't "Done." --

LA_PARA = "790 La Para Ave, Palo Alto, CA 94306"


async def test_leaving_from_the_in_laws_uses_their_saved_house(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    husband = scenario.member("Husband")
    memory(scenario).places.save(husband, f"{husband.name}'s Parent's House", LA_PARA)
    fake_travel.place(LA_PARA, 37.42, -122.13)
    fake_travel.place(LOT, 37.43, -122.17)
    ready.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit at Stanford",
                    location=LOT)  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call(
        "drive_time", {"event": "Visit at Stanford", "address": "", "from": "in-laws"}
    )
    scenario.primary.queue_text("")
    replies = await scenario.say("Erin", "When should I leave if I'm at my in-law's?")
    result = tool_result(scenario)
    assert "Not sure where" not in result
    assert f"from {husband.name}'s Parent's House" in result or "La Para" in result
    assert "Done." not in replies


async def test_an_unknown_place_is_asked_about_not_done(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    fake_travel.place(LOT, 37.43, -122.17)
    ready.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit at Stanford",
                    location=LOT)  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call("search_memory", {"query": "grandma"})
    scenario.primary.queue_tool_call(
        "drive_time", {"event": "Visit at Stanford", "address": "", "from": "grandma's"}
    )
    scenario.primary.queue_text("")
    replies = await scenario.say("Erin", "It's one of the places in your memory")
    assert replies == ["I don't have an address for grandma's yet. What is it?"]
