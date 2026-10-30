"""K4: travel time and "time to get ready". The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.travel import FakeTravel
from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock

PACIFIC = ZoneInfo("America/Los_Angeles")
HOME = "12 Main St, Springfield"


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


@pytest.fixture
async def ready(
    scenario: Scenario,
    fake_google: FakeGoogle,
    fake_gcal: FakeGcal,
    fake_travel: FakeTravel,
    site: httpx.AsyncClient,
) -> FakeGcal:
    """Erin's calendar linked, home saved, and a few places on the map."""
    await link(scenario, site, fake_google, "Erin", ERIN)
    fake_travel.place(HOME, 37.700, -122.400)
    fake_travel.place("Smile Dental", 37.780, -122.420)  # about 9 km away
    fake_travel.place("Next door", 37.7005, -122.4005)
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/family/home", data={"csrf": csrf, "address": HOME})
    fake_travel.minutes = 35
    return fake_gcal


async def at(scenario: Scenario, hour: int, minute: int = 0, day: int = 21) -> list[str]:
    """Move to that local time, read the calendar, run the job; the heads-ups so far."""
    target = datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)
    clock.advance(target - clock.now())
    await scenario.run_periodic("calendar.busy")
    await scenario.run_periodic("travel.heads_up")
    await scenario.app.outbox.flush()
    rows = scenario.app.db.query("SELECT text FROM outbox WHERE kind = 'travel' ORDER BY id")
    return [r["text"] for r in rows]


async def test_the_heads_up_comes_when_its_time_to_get_ready(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    ready.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    assert await at(scenario, 13) == []
    assert fake_travel.count("route") == 0  # not close yet: no lookup
    assert await at(scenario, 14) == []  # leave 2:25, get ready from 2:10
    assert await at(scenario, 14, 10) == [
        "Dentist at 3 pm, about 35 min with traffic: leave around 2:25 pm."
    ]
    assert any(t.startswith("Dentist at 3 pm") for t in scenario.inbox("Erin"))
    assert await at(scenario, 14, 15) == [
        "Dentist at 3 pm, about 35 min with traffic: leave around 2:25 pm."
    ]  # once


async def test_the_heads_up_isnt_held_to_the_leave_time(
    scenario: Scenario, ready: FakeGcal
) -> None:
    """Bug #91 ("traffic was considered, but prep time wasn't"): queued at 3:33 to get ready,
    pacing held it to the leave time, 3:49, so there was no time to get ready."""
    erin = scenario.member("Erin")
    scenario.app.db.execute("UPDATE members SET daily_limit = 0 WHERE id = ?", (erin.id,))
    ready.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(scenario, 14, 10)
    assert any(t.startswith("Dentist at 3 pm") for t in scenario.inbox("Erin"))


async def test_nothing_for_calls_all_day_things_or_home(
    scenario: Scenario, ready: FakeGcal
) -> None:
    ready.add_event(ERIN, local(15), local(16), summary="1:1", location="Smile Dental",
                    hangoutLink="https://meet.google.com/x")  # fmt: skip
    ready.add_event(
        ERIN, "2026-10-21", "2026-10-22", all_day=True, summary="Trip", location="Smile Dental"
    )
    ready.add_event(ERIN, local(15), local(16), summary="Coffee", location="Next door")
    ready.add_event(ERIN, local(15), local(16), summary="Focus time")
    assert await at(scenario, 14, 30) == []


async def test_without_a_key_its_a_rough_guess(
    scenario: Scenario,
    fake_google: FakeGoogle,
    fake_gcal: FakeGcal,
    fake_travel: FakeTravel,
    site: httpx.AsyncClient,
) -> None:
    fake_travel.use_tomtom = False  # too late for the app's client: make a new one
    travel = scenario.app.services.travel
    assert travel is not None
    travel.client = fake_travel.client()
    await link(scenario, site, fake_google, "Erin", ERIN)
    fake_travel.place(HOME, 37.700, -122.400)
    fake_travel.place("Smile Dental", 37.780, -122.420)
    await travel.set_home(HOME)
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    assert await at(scenario, 14, 30) == [
        "Dentist at 3 pm, about 25 min (a rough guess, without traffic): leave around 2:35 pm."
    ]
    assert fake_travel.count("nominatim") == 2 and fake_travel.count("route") == 0


async def test_a_moved_event_gets_a_new_one_and_settings_count(
    scenario: Scenario, ready: FakeGcal
) -> None:
    eid = ready.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(scenario, 14, 10)
    ready.calendar(ERIN, ERIN).events[eid].update(  # type: ignore[union-attr]
        start={"dateTime": local(17)}, end={"dateTime": local(18)}
    )
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, getting_ready_minutes=30)
    assert len(await at(scenario, 15, 50)) == 1  # leave 4:25, get ready from 3:55
    assert (await at(scenario, 15, 55))[-1] == (
        "Dentist at 5 pm, about 35 min with traffic: leave around 4:25 pm."
    )
    scenario.app.store.update_settings(erin, erin.id, leave_heads_up=False)
    ready.add_event(ERIN, local(20), local(21), summary="Dinner", location="Smile Dental")
    assert len(await at(scenario, 19, 30)) == 2  # switched off: nothing new


async def test_a_failed_route_falls_back_to_an_estimate(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    ready.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    fake_travel.fail("route", 500)
    assert await at(scenario, 14, 30) == [
        "Dentist at 3 pm, about 25 min (a rough guess, without traffic): leave around 2:35 pm."
    ]


async def test_the_family_page_saves_home(
    scenario: Scenario, fake_travel: FakeTravel, site: httpx.AsyncClient
) -> None:
    fake_travel.place(HOME, 37.700, -122.400)
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/family/home", data={"csrf": csrf, "address": "Nowhere Lane"})
    assert "found on the map. Try adding the city" in await flash(site, "/family")
    await site.post("/family/home", data={"csrf": csrf, "address": HOME})
    page = await flash(site, "/family")
    assert "Home saved" in page and f'value="{HOME}"' in page
    travel = scenario.app.services.travel
    assert travel is not None and travel.home() is not None


# ----- K4b: drive time on request -------------------------------------------------------


def tool_result(scenario: Scenario) -> str:
    from themi.ai.types import ToolResult

    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def ask(scenario: Scenario, who: str, event: str, address: str) -> str:
    scenario.primary.queue_tool_call("drive_time", {"event": event, "address": address})
    scenario.primary.queue_text("About that long.")
    await scenario.say(who, "How long will it take to drive there?")
    return tool_result(scenario)


async def test_the_drive_to_the_next_matching_event(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    fake_travel.place("Kids Clinic, 4 Elm St", 37.760, -122.430)
    ready.add_event(ERIN, local(10, day=23), local(11, day=23), summary="Pediatrics: Rosie",
                    location="Kids Clinic, 4 Elm St")  # fmt: skip
    ready.add_event(ERIN, local(10, day=30), local(11, day=30), summary="Pediatrics: Rosie",
                    location="Kids Clinic, 4 Elm St")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "pediatrics", "")
    assert '<data source="calendars">\nPediatrics: Rosie, Fri 23 Oct, 10-11 am' in result
    assert (
        "About 35 min from home with traffic: leave around 9:25 am, and start getting ready "
        "around 9:10 am. The heads-up to get ready comes then, at about 9:10 am."
    ) in result  # bug #24: Themi had said there were no advance reminders
    (_, params) = [c for c in fake_travel.calls if c[0] == "route"][-1]
    arrive = datetime.fromisoformat(params["arriveAt"])
    assert arrive == datetime(2026, 10, 23, 10, tzinfo=PACIFIC)  # timed for the start


async def test_a_typed_address_is_right_now(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    result = await ask(scenario, "Erin", "", "Smile Dental")
    assert result == "To Smile Dental: about 35 min from home with traffic, leaving now."


async def test_what_it_cant_answer(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    ready.add_event(
        ERIN, local(15), local(16), summary="Standup", hangoutLink="https://meet.google.com/x"
    )
    ready.add_event(ERIN, local(17), local(18), summary="Pick up the cake")
    await scenario.run_periodic("calendar.busy")
    assert "No upcoming event of theirs matches" in await ask(scenario, "Erin", "pediatrics", "")
    assert "is a video call" in await ask(scenario, "Erin", "standup", "")
    assert "has no address" in await ask(scenario, "Erin", "cake", "")
    assert "wasn't found on the map" in await ask(scenario, "Erin", "", "Nowhere Lane")


async def test_only_events_they_may_see(
    scenario: Scenario,
    ready: FakeGcal,
    fake_google: FakeGoogle,
    site: httpx.AsyncClient,
) -> None:
    await link(scenario, site, fake_google, "Husband", "him@gmail.com")
    ready.add_event(
        "him@gmail.com", local(15), local(16), summary="Dentist", location="Smile Dental"
    )
    await scenario.run_periodic("calendar.busy")
    assert "No upcoming event of theirs matches" in await ask(scenario, "Erin", "dentist", "")
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(husband, husband.id, calendar_details="partner")
    result = await ask(scenario, "Erin", "dentist", "")
    assert "Husband: Dentist, Wed 21 Oct, 3-4 pm" in result
    assert "The heads-up to get ready goes to Husband, whose calendar it's on" in result
    scenario.app.store.update_settings(husband, husband.id, leave_heads_up=False)
    assert "Husband has the heads-up switched off" in await ask(scenario, "Erin", "dentist", "")


async def test_words_match_loosely(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    """Bug #20: "her tutoring appointment" didn't find "Tutor Gabriel (Illems)"."""
    fake_travel.place("790 La Para Ave", 37.705, -122.405)
    ready.add_event(ERIN, local(16, day=29), local(17, day=29), summary="Tutor Gabriel (Illems)",
                    location="790 La Para Ave")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    assert "Tutor Gabriel (Illems), Thu 29 Oct, 4-5 pm" in await ask(
        scenario, "Erin", "tutoring appointment", ""
    )
