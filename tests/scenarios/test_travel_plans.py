"""F46 (Michael's bugs #217-#219, 2026-11-17): the drive to the visit at Stanford. An address
they give wins over the event's place (F46b); where they said they'll leave from stays with
the event (F46c); "arrive at 6:15" times the leave for then (F46d). The clock starts
Wednesday 21 October 2026, 9 am; Erin's home is 12 Main St, and her in-laws (Husband's
parents) are at 790 La Para Ave."""

from __future__ import annotations

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.travel import FakeTravel
from tests.scenarios.harness import Scenario
from tests.scenarios.test_travel import ask, at, in_laws, local, ready, remember, tool_result
from tests.scenarios.test_triage import ERIN

__all__ = ["in_laws", "ready"]

STANFORD = "200 S Pasteur Dr, Palo Alto, CA 94304"
PARKING = "Stanford visitor parking"


def stanford(fake: FakeGcal, travel: FakeTravel) -> None:
    """The visit at 6:30 pm, at a place name the map finds 4000 km away."""
    travel.place(PARKING, 40.0, -80.0)
    travel.place(STANFORD, 37.43, -122.17)
    fake.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit at Stanford",
                   location=PARKING)  # fmt: skip


# ----- F46b (bug #217, replies 499 and 500): the address they gave -----------------------


async def test_the_address_they_gave_wins_over_the_events_place(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    stanford(ready, fake_travel)
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "visit", STANFORD)
    assert "km from home" not in result
    assert (
        "About 35 min from home with traffic: leave around 5:55 pm, and start getting ready "
        "around 5:40 pm." in result
    )
    assert (
        f"The calendar has '{PARKING}' for it; change_calendar_event can put this address "
        "there." in result
    )


async def test_an_address_the_same_as_the_events_says_nothing_more(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    fake_travel.place(STANFORD, 37.43, -122.17)
    ready.add_event(ERIN, local(18, 30), local(20, 30), summary="Visit at Stanford",
                    location=STANFORD)  # fmt: skip
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "visit", STANFORD)
    assert "leave around 5:55 pm" in result
    assert "change_calendar_event" not in result


async def test_a_remembered_address_for_a_named_place_is_used(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    """Reply 499 saved this fact; nothing read it."""
    stanford(ready, fake_travel)
    remember(scenario, f"{PARKING} address is {STANFORD}")
    await scenario.run_periodic("calendar.busy")
    result = await ask(scenario, "Erin", "visit", "")
    assert "leave around 5:55 pm" in result
    assert await at(scenario, 17, 40) == [
        "Visit at Stanford at 6:30 pm, about 35 min with traffic: leave around 5:55 pm."
    ]
    looked_up = "SELECT COUNT(*) FROM geocodes WHERE query_key LIKE '%parking%'"
    assert scenario.app.db.scalar(looked_up) == 0  # never sent to the map


# ----- F46c (bug #218): where they'll leave from stays with the event ---------------------

FROM_IN_LAWS = "about 9 min from the in-laws (790 La Para Ave) with traffic"


async def drive(scenario: Scenario, event: str, start: str = "", **more: str) -> str:
    scenario.primary.queue_tool_call(
        "drive_time", {"event": event, "address": "", "from": start, **more}
    )
    scenario.primary.queue_text("OK.")
    await scenario.say("Erin", "How long is the drive?")
    return tool_result(scenario)


async def test_where_they_said_stays_for_the_next_question(
    scenario: Scenario, in_laws: FakeGcal
) -> None:
    await scenario.run_periodic("calendar.busy")
    assert "A" + FROM_IN_LAWS[1:] in await drive(scenario, "ND psych", "in-laws")
    again = await drive(scenario, "ND psych")
    assert "A" + FROM_IN_LAWS[1:] in again
    assert "from: 'home'" in again  # says it's kept, and how to change it


async def test_the_heads_up_leaves_from_there_too(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", "in-laws")
    assert await at(scenario, 12, 20) == []  # from home it would have gone by now
    assert await at(scenario, 12, 36) == [
        f"ND psych in person at 1 pm, {FROM_IN_LAWS}: leave there around 12:51 pm."
    ]


async def test_from_home_clears_it(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", "in-laws")
    await drive(scenario, "ND psych", "home")
    assert "About 35 min from home" in await drive(scenario, "ND psych")


async def test_another_event_isnt_affected(
    scenario: Scenario, in_laws: FakeGcal, fake_travel: FakeTravel
) -> None:
    in_laws.add_event(ERIN, local(16), local(17), summary="Dentist", location="Smile Dental")
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", "in-laws")
    assert "About 35 min from home" in await drive(scenario, "dentist")


async def test_a_moved_event_keeps_its_plan(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", "in-laws")
    event = next(iter(in_laws._box(ERIN)["primary"].events))
    in_laws.move_event(ERIN, event, local(13, 15), local(14, 15))
    await scenario.run_periodic("calendar.busy")
    assert "leave there around 1:06 pm" in await drive(scenario, "ND psych")


async def test_a_kept_place_no_longer_found_is_from_home_and_says_so(
    scenario: Scenario, in_laws: FakeGcal
) -> None:
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", "in-laws")
    scenario.app.db.execute("DELETE FROM facts")  # the in-laws' address is forgotten
    assert (await at(scenario, 12, 10))[-1] == (
        "ND psych in person at 1 pm, about 35 min from home (the in-laws wasn't found) with "
        "traffic: leave around 12:25 pm."
    )


# ----- F46d (bug #219): there by a time before it starts; no second leave reminder --------

EARLY_LINE = (
    "ND psych in person at 1 pm, there by 12:45 pm: about 35 min with traffic. Leave around "
    "12:10 pm; start getting ready around 11:55 am."
)


async def test_arrive_by_times_the_leave_for_then(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    result = await drive(scenario, "ND psych", arrive_by="12:45")
    assert f'word for word: "{EARLY_LINE}"' in result
    assert await at(scenario, 11, 55) == [
        "ND psych in person at 1 pm, there by 12:45 pm, about 35 min with traffic: leave "
        "around 12:10 pm."
    ]


async def test_arrive_by_is_kept_with_the_event(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", arrive_by="12:45")
    assert f'word for word: "{EARLY_LINE}"' in await drive(scenario, "ND psych")


async def test_with_where_they_leave_from_too(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    await drive(scenario, "ND psych", "in-laws", arrive_by="12:45")
    assert "Leave there around 12:36 pm" in await drive(scenario, "ND psych")


async def test_arrive_by_after_the_start_is_refused(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    assert "after it starts" in await drive(scenario, "ND psych", arrive_by="13:15")
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM travel_plans") == 0


async def remind(scenario: Scenario, text: str, also: bool = False) -> str:
    args: dict[str, object] = {"text": text, "date": "2026-10-21", "time": "12:30"}
    if also:
        args["also"] = True
    scenario.primary.queue_tool_call("add_reminder", args)
    scenario.primary.queue_text("OK.")
    await scenario.say("Erin", "Remind me to leave")
    return tool_result(scenario)


def reminders(scenario: Scenario) -> int:
    return int(scenario.app.db.scalar("SELECT COUNT(*) FROM outbox WHERE kind = 'reminder'"))


async def test_a_leave_reminder_for_a_timed_event_isnt_set(
    scenario: Scenario, in_laws: FakeGcal
) -> None:
    """Replies 497 and 501 set "Leave for Stanford visitor parking" at 6 pm, after the 5:55
    leave time."""
    await scenario.run_periodic("calendar.busy")
    result = await remind(scenario, "Leave for ND psych")
    assert result == (
        "Not set: the heads-up to get ready already comes at 12:10 pm, and says when to "
        "leave; no separate reminder set. If they want one as well, add_reminder with also."
    )
    assert reminders(scenario) == 0
    assert "Reminder set" in await remind(scenario, "Leave for Smile Dental", also=True)
    assert reminders(scenario) == 1


async def test_other_reminders_are_set_as_before(scenario: Scenario, in_laws: FakeGcal) -> None:
    await scenario.run_periodic("calendar.busy")
    assert "Reminder set" in await remind(scenario, "Leave the porch light on")


# ----- F49b (bugs #227, #228): a heads-up through an outage -------------------------------


async def test_a_heads_up_held_up_by_an_outage_goes_when_telegram_is_back(
    scenario: Scenario, ready: FakeGcal, fake_travel: FakeTravel
) -> None:
    """Michael's 18 Nov: Telegram was unreachable from 4:58 pm; the heads-up queued at 5:35,
    its retries backed off to an hour, and it was dropped at the start as too late, while
    Telegram was back at 6:06."""
    stanford(ready, fake_travel)
    remember(scenario, f"{PARKING} address is {STANFORD}")
    await scenario.run_periodic("calendar.busy")
    await ask(scenario, "Erin", "visit", "")
    erin = scenario.member("Erin").id
    before = scenario.app.db.scalar("SELECT MAX(id) FROM message_log")

    def went() -> list[str]:  # what reached Telegram (its fake keeps failed calls too)
        rows = scenario.app.db.query(
            "SELECT text FROM message_log WHERE member_id = ? AND direction = 'out' AND id > ?",
            (erin, before),
        )
        return [r["text"] for r in rows]

    scenario.telegram.fail("sendMessage", 502, "Bad Gateway", times=1000)
    await at(scenario, 17, 40)
    for minute in range(42, 66, 2):  # 5:42 to 6:04, still down
        await at(scenario, 17 + minute // 60, minute % 60)
    assert went() == []
    scenario.telegram.state.failures.clear()  # back at 6:05
    await at(scenario, 18, 6)
    assert went() == ["Visit at Stanford at 6:30 pm, about 35 min with traffic: time to head out."]
