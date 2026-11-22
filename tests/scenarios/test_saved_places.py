"""F57b: "go to Stanford" means the visitor parking lot. A saved place's address is driven
to, its note (visiting hours) is in front of the model, and the leave time has them there
the minutes early they set. The clock starts Wednesday 21 October 2026, 9 am; the drive
home → Stanford is about 35 min."""

from __future__ import annotations

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.travel import FakeTravel
from tests.scenarios.harness import Scenario
from tests.scenarios.test_travel import ask, at, local, ready, tool_result
from tests.scenarios.test_triage import ERIN
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
    assert f'<data source="memory">\nWhat they told Themi about Stanford: {HOURS}\n</data>' in (
        result
    )
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
