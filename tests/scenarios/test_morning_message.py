"""MM: the morning message, its tray and its buttons. Erin's quiet hours are 21:30-08:00 and
her daily limit is 6; her morning message is set for 7:15, so on Thursday 22 October it
waits for her quiet hours to end and goes at 8."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import PACIFIC, board, linked
from tests.scenarios.test_triage import ERIN
from themi import clock
from themi.channels.outbox import Priority
from themi.standard.day_summary import DaySummaryPreferences
from themi.standard.morning import RECAP_TEXT

__all__ = ["linked"]

THU = date(2026, 10, 22)
MORNING = "Morning, Erin.\nThu 22 Oct:\n- 10-11 am: Dentist"
ALL_FOUR = ["Today's tasks", "Email", "Everything else", "Just one thing"]


def at(hour: int, minute: int = 0, day: int = 22) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


def to(moment: datetime) -> None:
    clock.advance(moment - clock.now())


def edited_buttons(scenario: Scenario) -> list[str]:
    markup = scenario.edits("Erin")[-1].get("reply_markup") or {"inline_keyboard": []}
    if isinstance(markup, str):
        markup = json.loads(markup)
    return [b["text"] for row in markup["inline_keyboard"] for b in row]


def counted(scenario: Scenario) -> int:
    return scenario.app.outbox.sent_today(scenario.member("Erin").id)


async def overnight(scenario: Scenario, fake: FakeGcal) -> None:
    """Thursday before dawn: a dentist on the calendar, two tasks due, a dinner idea and an
    email note waiting, and the morning message at 7:15."""
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="07:15"
    )
    to(at(6))
    fake.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist")
    fake.add_event(
        ERIN,
        at(14).isoformat(),
        at(15).isoformat(),
        summary="Call the vet",
        extendedProperties={"private": {"themi": "task-block:1"}},
    )
    await scenario.run_periodic("calendar.busy")
    await board(scenario).create(erin, "Call the vet", "call", 1, THU, assignee=erin)
    await board(scenario).create(erin, "Post the letter", "errand", 1, THU, assignee=erin)
    await scenario.app.outbox.send(
        erin, "Dinner idea: tacos?", priority=Priority.NORMAL, kind="meal"
    )
    await scenario.app.outbox.send(
        erin, "New mail from the bank.", priority=Priority.NORMAL, kind="email"
    )
    to(at(7, 15))
    await scenario.run_periodic("calendar.morning")


@pytest.fixture
def before(scenario: Scenario) -> int:
    """How many messages Erin had before the night (linking her inbox)."""
    return len(scenario.inbox("Erin"))


async def test_one_message_starts_the_day_and_the_rest_waits(
    scenario: Scenario, linked: FakeGcal, before: int
) -> None:
    await overnight(scenario, linked)
    assert scenario.inbox("Erin")[before:] == []  # 7:15 is in her quiet hours
    sent = await scenario.advance(minutes=45)
    assert sent == [MORNING]  # calendar only: no tasks, no task block, nothing else
    assert scenario.last_buttons("Erin") == ALL_FOUR
    assert counted(scenario) == 1


async def test_each_tap_brings_its_part_and_none_of_it_counts(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    assert await scenario.tap("Erin", "Email") == ["New mail from the bank."]
    assert edited_buttons(scenario) == ["Today's tasks", "Everything else", "Just one thing"]
    assert scenario.edits("Erin")[-1]["text"] == MORNING  # the message stays, less a button
    assert await scenario.tap("Erin", "Everything else") == ["Dinner idea: tacos?"]
    assert await scenario.tap("Erin", "Today's tasks") == [
        "This morning:\n- Due today: Call the vet\n- Due today: Post the letter\n"
        "Tap any that are done; the rest can wait."
    ]
    assert await scenario.tap("Erin", "Just one thing") == [
        "For now, just this:\n- Call the vet\nThe other one is kept; nothing's dropped."
    ]
    assert edited_buttons(scenario) == []
    assert counted(scenario) == 1


async def test_nothing_tapped_comes_back_once_at_noon(scenario: Scenario, linked: FakeGcal) -> None:
    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    await scenario.tap("Erin", "Email")
    to(at(11, 55))
    assert await scenario.run_periodic("calendar.morning_recap") == 0
    to(at(12))
    assert await scenario.run_periodic("calendar.morning_recap") == 1
    assert scenario.inbox("Erin")[-1] == RECAP_TEXT
    assert scenario.last_buttons("Erin") == ["Today's tasks", "Everything else", "Just one thing"]
    assert counted(scenario) == 2
    to(at(13))
    assert await scenario.run_periodic("calendar.morning_recap") == 0  # once a day
    assert await scenario.tap("Erin", "Everything else") == ["Dinner idea: tacos?"]


async def test_a_busy_noon_moves_the_recap_to_five(scenario: Scenario, linked: FakeGcal) -> None:
    linked.add_event(ERIN, at(11, 30).isoformat(), at(13).isoformat(), summary="Lunch meeting")
    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    to(at(13, 30))
    assert await scenario.run_periodic("calendar.morning_recap") == 0
    to(at(17))
    assert await scenario.run_periodic("calendar.morning_recap") == 1
    assert scenario.inbox("Erin")[-1] == RECAP_TEXT


async def test_all_looked_at_means_no_recap(scenario: Scenario, linked: FakeGcal) -> None:
    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    for label in ("Email", "Everything else", "Today's tasks"):
        await scenario.tap("Erin", label)
    to(at(12))
    assert await scenario.run_periodic("calendar.morning_recap") == 0
    assert counted(scenario) == 1


async def test_a_tap_on_yesterdays_message_answers_with_today(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    to(at(9, day=23))
    replies = await scenario.tap("Erin", "Everything else")
    assert replies == ["That one was from Thu 22 Oct; here's today.", "Dinner idea: tacos?"]


async def test_urgent_and_timed_messages_never_wait(scenario: Scenario, linked: FakeGcal) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="09:00"
    )
    to(at(8, 30))  # her quiet hours are over; the morning message isn't due yet
    urgent = await scenario.app.outbox.send(erin, "Leak!", priority=Priority.URGENT)
    timely = await scenario.app.outbox.send(
        erin, "Approve now?", priority=Priority.NORMAL, kind="approval", deadline=clock.now()
    )
    held = await scenario.app.outbox.send(erin, "A deal.", priority=Priority.NORMAL, kind="deal")
    assert (urgent.status, timely.status, held.status) == ("sent", "sent", "queued")


async def test_without_the_setting_nothing_is_held(scenario: Scenario, linked: FakeGcal) -> None:
    erin = scenario.member("Erin")
    to(at(8, 30))
    result = await scenario.app.outbox.send(erin, "A deal.", priority=Priority.NORMAL, kind="deal")
    assert result.status == "sent"


async def test_a_missed_morning_lets_everything_go(scenario: Scenario, linked: FakeGcal) -> None:
    """Themi was down from 8 until past the three hours: nothing's lost."""
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="07:15"
    )
    to(at(8))
    await scenario.app.outbox.send(erin, "A deal.", priority=Priority.NORMAL, kind="deal")
    to(at(10, 30))
    await scenario.run_periodic("calendar.morning")
    assert await scenario.advance(minutes=1) == ["A deal."]
    assert not [t for t in scenario.inbox("Erin") if t.startswith("Morning, Erin")]


async def test_nothing_on_and_nothing_waiting_is_skipped_unless_asked(
    scenario: Scenario, linked: FakeGcal
) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="08:15"
    )
    to(at(8, 15))
    await scenario.run_periodic("calendar.morning")
    assert scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'morning'") == []
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary_empty=True
    )
    to(at(8, 15, day=23))
    await scenario.run_periodic("calendar.morning")
    assert scenario.inbox("Erin")[-1] == "Good morning, Erin. Nothing on the calendar today."
