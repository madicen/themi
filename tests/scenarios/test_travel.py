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
from tests.scenarios.test_calendar_events import on_primary
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.core import keys
from themi.core.calendar_view import CalendarPreferences
from themi_google.travel import TravelPreferences

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
    travel = scenario.app.services.maybe(keys.travel)
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
    scenario.app.store.save_preferences(erin, erin.id, TravelPreferences, getting_ready_minutes=30)
    assert len(await at(scenario, 15, 50)) == 1  # leave 4:25, get ready from 3:55
    assert (await at(scenario, 15, 55))[-1] == (
        "Dentist at 5 pm, about 35 min with traffic: leave around 4:25 pm."
    )
    scenario.app.store.save_preferences(erin, erin.id, TravelPreferences, leave_heads_up=False)
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
    travel = scenario.app.services.maybe(keys.travel)
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
    scenario.app.store.save_preferences(
        husband, husband.id, CalendarPreferences, calendar_details="partner"
    )
    result = await ask(scenario, "Erin", "dentist", "")
    assert "Husband: Dentist, Wed 21 Oct, 3-4 pm" in result
    assert "The heads-up to get ready goes to Husband, whose calendar it's on" in result
    scenario.app.store.save_preferences(
        husband, husband.id, TravelPreferences, leave_heads_up=False
    )
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


PARENTS = "790 La Para Ave, Palo Alto, CA 94306"


def remember(scenario: Scenario, fact: str) -> None:
    now = clock.now().isoformat()
    scenario.app.db.execute(
        "INSERT INTO facts (scope, member_id, subject, fact, created_at, updated_at) "
        "VALUES ('family', NULL, 'places', ?, ?, ?)",
        (fact, now, now),
    )


async def test_bug_154_parents_house_is_the_remembered_address(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    """Bug #154: "parent's house" went to the map, which found a place near Oroville."""
    fake_travel.place(PARENTS, 37.75, -122.45)
    fake_travel.place("parent's house", 39.437, -121.593)  # the wrong one, 230 km away
    remember(scenario, f"Erin's parents' address is {PARENTS}.")
    result = await ask(scenario, "Erin", "", "parent's house")
    assert result == (
        f"To parent's house ({PARENTS}): about 35 min from home with traffic, leaving now."
    )
    looked_up = "SELECT COUNT(*) FROM geocodes WHERE query_key LIKE '%parent%'"
    assert scenario.app.db.scalar(looked_up) == 0  # never sent to the map


async def test_a_named_place_with_no_address_asks_and_isnt_guessed(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    fake_travel.place("parent's house", 39.437, -121.593)
    result = await ask(scenario, "Erin", "", "parent's house")
    assert result.startswith("Not sure where 'parent's house' is")
    looked_up = "SELECT COUNT(*) FROM geocodes WHERE query_key LIKE '%parent%'"
    assert scenario.app.db.scalar(looked_up) == 0  # never sent to the map


async def test_a_vague_place_found_far_away_is_checked(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    fake_travel.place("The Big Barn", 39.437, -121.593)
    result = await ask(scenario, "Erin", "", "The Big Barn")
    assert "km from home, which may be a different place of that name" in result


async def test_an_event_at_parents_house_times_the_drive_from_the_fact(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    """Bug #154: the event's location was "Parent's house"; leave at 2:50, the first time."""
    fake_travel.place(PARENTS, 37.75, -122.45)
    remember(scenario, f"Erin's parents' address is {PARENTS}.")
    ready.add_event(ERIN, local(15, 30), local(16, 55), summary="Tutor Gabriel (Illems)",
                    location="Parent's house")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "tutor gabriel", "")
    assert "leave around 2:55 pm" in result


async def test_a_private_partner_calendar_is_said_so(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    """#155's thread: Michael asked about tutoring "on Erin's calendar"."""
    result = await ask(scenario, "Husband", "tutoring", "")
    assert "Erin keeps calendar details private, so those events aren't searched" in result


# ----- F41c, bug #199: what Themi did, and when to leave, are in the reply -------------------

REQUEST_426 = (
    "We need to drop off our kid at my in-laws before we go to that appointment. Please add "
    "that to our calendar and recalculate the drive times (especially since we'll leave from "
    "my in-laws to go to the appointment)"
)


async def test_reply_426_says_the_new_event_and_not_the_old_answer_again(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    ready.add_event(ERIN, local(13), local(14), summary="ND psych in person",
                    location="Smile Dental")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_text("Leave at 12:25 PM.")
    assert await scenario.say("Erin", "What time do we need to leave?") == ["Leave at 12:25 PM."]
    scenario.primary.queue_tool_calls([
        ("add_calendar_event", {"title": "Drop off kid at in-laws", "date": "2026-10-21",
                                "start": "12:00", "end": "13:00", "location": "Next door",
                                "calendar": "mine", "details": "", "unread": ""}, None),
        ("drive_time", {"event": "", "address": "Smile Dental"}, None),
    ])  # fmt: skip
    scenario.primary.queue_text("Leave at 12:25 PM.")  # word for word the last answer
    replies = await scenario.say("Erin", REQUEST_426)
    assert replies == [
        "On your calendar: Drop off kid at in-laws, Wed 21 Oct, 12-1 pm (at Next door)."
    ]


async def test_drive_time_says_when_to_leave_and_get_ready_itself(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, TravelPreferences, getting_ready_minutes=20)
    ready.add_event(ERIN, local(13), local(14), summary="ND psych in person",
                    location="Smile Dental")  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call("drive_time", {"event": "ND psych", "address": ""})
    scenario.primary.queue_text("Leave at 12:25 PM.")  # the model cut it short
    replies = await scenario.say("Erin", "What time do we need to leave?")
    assert replies == [
        "ND psych in person at 1 pm: about 35 min with traffic. Leave around 12:25 pm; start "
        "getting ready around 12:05 pm."
    ]


async def test_a_drive_to_an_address_has_no_leave_line(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    scenario.primary.queue_tool_call("drive_time", {"event": "", "address": "Smile Dental"})
    scenario.primary.queue_text("About 35 minutes from home.")
    assert await scenario.say("Erin", "How far is Smile Dental?") == ["About 35 minutes from home."]


async def test_an_event_made_and_its_drive_both_said(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    scenario.primary.queue_tool_call(
        "add_calendar_event",
        {"title": "Dentist", "date": "2026-10-21", "start": "15:00", "end": "",
         "location": "Smile Dental", "calendar": "mine", "details": "", "unread": ""},
    )  # fmt: skip
    scenario.primary.queue_tool_call("drive_time", {"event": "dentist", "address": ""})
    scenario.primary.queue_text("Added the dentist at 3. Leave at 2:25.")
    replies = await scenario.say(
        "Erin", "Put the dentist on my calendar today at 3 at Smile Dental, and when do I leave?"
    )
    assert replies == [
        "On your calendar: Dentist, Wed 21 Oct, 3-4 pm (at Smile Dental).\n"
        "Dentist at 3 pm: about 35 min with traffic. Leave around 2:25 pm; start getting "
        "ready around 2:10 pm."
    ]


# ----- F41d, bug #199: a stop on the way; drives from where they'll be ----------------------

IN_LAWS = "790 La Para Ave, Palo Alto, CA 94306"


@pytest.fixture
def in_laws(scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel) -> FakeGcal:
    """Erin's in-laws (Husband's parents) on the map; home → in-laws 10 min, in-laws →
    Smile Dental 9 min, home → Smile Dental 35. ND psych at 1 pm at Smile Dental."""
    fake_travel.place(IN_LAWS, 37.75, -122.45)
    remember(scenario, f"Husband's parents live at {IN_LAWS}.")
    fake_travel.leg(HOME, IN_LAWS, 10)
    fake_travel.leg(IN_LAWS, "Smile Dental", 9)
    ready.add_event(ERIN, local(13), local(14), summary="ND psych in person",
                    location="Smile Dental")  # fmt: skip
    return ready


async def test_drive_time_from_the_in_laws(
    scenario: Scenario, in_laws: FakeGcal, fake_travel: FakeTravel
) -> None:
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call(
        "drive_time", {"event": "ND psych", "address": "", "from": "in-laws"}
    )
    scenario.primary.queue_text("Leave at 12:51.")
    replies = await scenario.say("Erin", "When do we leave the in-laws for ND psych?")
    assert replies == [
        "ND psych in person at 1 pm: about 9 min from the in-laws (790 La Para Ave) with "
        "traffic. Leave there around 12:51 pm; start getting ready around 12:36 pm."
    ]
    assert (
        "About 9 min from the in-laws (790 La Para Ave) with traffic: leave there around "
        "12:51 pm" in tool_result(scenario)
    )


async def test_back_to_back_the_next_drive_is_from_the_first_place(
    scenario: Scenario, in_laws: FakeGcal
) -> None:
    in_laws.add_event(ERIN, local(12, 36), local(12, 51), summary="Drop off kid at in-laws",
                      location=IN_LAWS)  # fmt: skip
    assert await at(scenario, 12, 7) == []  # SLACK: up to 3 minutes early
    assert await at(scenario, 12, 11) == [
        "Drop off kid at in-laws at 12:36 pm, about 10 min with traffic: leave around 12:26 pm."
    ]
    assert len(await at(scenario, 12, 32)) == 1  # leave the in-laws 12:51, get ready 12:36
    assert (await at(scenario, 12, 36))[-1] == (
        "ND psych in person at 1 pm, about 9 min from Drop off kid at in-laws (790 La Para "
        "Ave) with traffic: leave there around 12:51 pm."
    )


async def test_two_hours_apart_its_from_home(scenario: Scenario, in_laws: FakeGcal) -> None:
    in_laws.add_event(ERIN, local(10, 30), local(10, 45), summary="Drop off kid at in-laws",
                      location=IN_LAWS)  # fmt: skip
    await at(scenario, 10, 30)
    assert (await at(scenario, 12, 10))[-1] == (
        "ND psych in person at 1 pm, about 35 min with traffic: leave around 12:25 pm."
    )


async def test_reply_426_the_stop_is_timed_from_the_drives(
    scenario: Scenario, in_laws: FakeGcal, fake_travel: FakeTravel
) -> None:
    """The scenario: Michael's request, with the model calling add_calendar_event with
    `before` and no times. The stop is 12:36-12:51 pm, and the leave times follow."""
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call(
        "add_calendar_event",
        {"title": "Drop off kid at in-laws", "date": "2026-10-21", "start": "", "end": "",
         "location": "in-laws", "calendar": "mine", "details": "", "unread": "",
         "before": "ND psych"},
    )  # fmt: skip
    scenario.primary.queue_text("Leave at 12:26.")
    replies = await scenario.say("Erin", REQUEST_426)
    assert replies == [
        f"On your calendar: Drop off kid at in-laws, Wed 21 Oct, 12:36-12:51 pm (at {IN_LAWS}).\n"
        "Leave home around 12:26 pm (start getting ready around 12:11 pm) to reach the in-laws "
        "by 12:36 pm; leave there around 12:51 pm for ND psych in person at 1 pm."
    ]
    event = on_primary(in_laws)["Drop off kid at in-laws"]
    assert event["start"]["dateTime"] == local(12, 36)
    assert event["end"]["dateTime"] == local(12, 51)
    # The heads-ups follow the same chain: home at 12:11, the in-laws at 12:36.
    assert (await at(scenario, 12, 11))[-1].endswith("leave around 12:26 pm.")
    assert (await at(scenario, 12, 36))[-1] == (
        "ND psych in person at 1 pm, about 9 min from Drop off kid at in-laws (790 La Para "
        "Ave) with traffic: leave there around 12:51 pm."
    )


async def test_a_stop_whose_place_isnt_found_asks_and_adds_nothing(
    scenario: Scenario, in_laws: FakeGcal
) -> None:
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call(
        "add_calendar_event",
        {"title": "Pick up cake", "date": "2026-10-21", "start": "", "end": "",
         "location": "Nowhere Bakery, Faraway", "calendar": "mine", "details": "",
         "unread": "", "before": "ND psych"},
    )  # fmt: skip
    scenario.primary.queue_text("What time should I put it at?")
    await scenario.say("Erin", "Add picking up the cake before ND psych")
    assert "the stop can't be timed" in tool_result(scenario)
    assert "Ask them what time" in tool_result(scenario)
    assert "Pick up cake" not in on_primary(in_laws)
