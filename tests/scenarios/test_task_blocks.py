"""K5: time blocked on a calendar for a task. The clock starts Wednesday 21 October 2026,
9 am."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.core.tasks import Task, TaskBoard

PACIFIC = ZoneInfo("America/Los_Angeles")
WED = date(2026, 10, 21)


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


async def bathroom(scenario: Scenario) -> Task:
    erin = scenario.member("Erin")
    return await board(scenario).create(
        erin, "Clean the bathroom", "physical", 3, WED, assignee=erin, nudge=False
    )


async def say(scenario: Scenario, said: str, tool: str, args: dict[str, Any]) -> list[str]:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Done.")
    return await scenario.say("Erin", said)


async def at(scenario: Scenario, hour: int, minute: int = 0) -> None:
    target = datetime(2026, 10, 21, hour, minute, tzinfo=PACIFIC)
    clock.advance(target - clock.now())
    await scenario.run_periodic("calendar.busy")
    await scenario.run_periodic("blocks.tick")
    await scenario.app.outbox.flush()


def nudges(scenario: Scenario) -> list[str]:
    """The task's messages that went out (not the family calendar's card)."""
    rows = scenario.app.db.query(
        "SELECT text FROM outbox WHERE kind = 'task' AND status = 'sent' AND member_id = ? "
        "ORDER BY id",
        (scenario.member("Erin").id,),
    )
    return [r["text"] for r in rows if "Clean the bathroom" in r["text"]]


def block_event(fake: FakeGcal) -> dict[str, Any]:
    (event,) = [e for e in fake.events(ERIN, ERIN) if e["summary"] == "Clean the bathroom"]
    return event


async def block_2_to_3(scenario: Scenario, task: Task) -> None:
    await say(
        scenario,
        "Block 2 to 3 today for the bathroom",
        "block_time_for_task",
        {"task_id": task.id, "date": "2026-10-21", "start": "14:00", "end": "15:00"},
    )


async def test_the_nudge_waits_for_the_block_and_asks_after(
    scenario: Scenario, linked: FakeGcal
) -> None:
    task = await bathroom(scenario)
    await block_2_to_3(scenario, task)
    event = block_event(linked)
    assert event["extendedProperties"]["private"]["themi"] == f"task-block:{task.id}"
    await at(scenario, 9, 30)
    assert scenario.app.db.query("SELECT * FROM calendar_busy") == []  # never busy time
    await board(scenario).prompt(board(scenario).get(task.id))  # held while the block is coming
    assert nudges(scenario) == []
    (item,) = [i.summary for i in board(scenario).open_items(scenario.member("Erin"))]
    assert "Time blocked for it on their calendar: Wed 21 Oct, 2-3 pm." in item

    await at(scenario, 13, 55)
    assert nudges(scenario) == []
    await at(scenario, 14)
    assert len(nudges(scenario)) == 1  # as the block begins (and the block doesn't hold it)
    await scenario.tap("Erin", "Later")
    await at(scenario, 15, 5)
    assert (
        nudges(scenario)[-1] == "The time for Clean the bathroom is over. Done, or move the block?"
    )
    await at(scenario, 16)
    assert len(nudges(scenario)) == 2  # asked once


async def test_an_unanswered_nudge_isnt_followed_by_a_second_question(
    scenario: Scenario, linked: FakeGcal
) -> None:
    task = await bathroom(scenario)
    await block_2_to_3(scenario, task)
    await at(scenario, 14)
    await at(scenario, 15, 5)
    assert nudges(scenario) == ["Due today: Clean the bathroom. Done already, or later?"]


async def test_moved_on_the_calendar_the_nudge_moves(scenario: Scenario, linked: FakeGcal) -> None:
    task = await bathroom(scenario)
    await block_2_to_3(scenario, task)
    block_event(linked).update(start={"dateTime": local(16)}, end={"dateTime": local(17)})
    await at(scenario, 14, 5)
    assert nudges(scenario) == []
    await at(scenario, 16)
    assert len(nudges(scenario)) == 1


async def test_deleted_on_the_calendar_nudging_is_as_before(
    scenario: Scenario, linked: FakeGcal
) -> None:
    task = await bathroom(scenario)
    await block_2_to_3(scenario, task)
    await at(scenario, 10)
    block_event(linked)["status"] = "cancelled"
    await at(scenario, 10, 30)
    assert len(nudges(scenario)) == 1  # its usual nudge, now
    assert not board(scenario).held(board(scenario).get(task.id), scenario.member("Erin"))


async def test_found_time_is_a_card_and_avoids_busy_times(
    scenario: Scenario, linked: FakeGcal
) -> None:
    task = await bathroom(scenario)
    linked.add_event(ERIN, local(9, 30), local(12), summary="Meetings")
    await scenario.run_periodic("calendar.busy")
    replies = await say(
        scenario,
        "Find me time for the bathroom",
        "find_time_for_task",
        {"task_id": task.id, "minutes": 60, "days": 2},
    )
    assert replies[0].startswith("Time for Clean the bathroom: ")
    assert replies[0].endswith(", on your calendar\nGo ahead, or not now?")
    (row,) = scenario.app.db.query(
        "SELECT payload FROM pending_actions WHERE executor = 'blocks.add'"
    )
    import json

    starts = datetime.fromisoformat(json.loads(row["payload"])["starts"])
    assert starts >= datetime(2026, 10, 21, 12, tzinfo=PACIFIC)  # after the meetings
    assert starts.minute % 15 == 0
    assert linked.events(ERIN, ERIN)[0]["summary"] == "Meetings"  # nothing made yet
    await scenario.tap("Erin", "Go ahead")
    assert block_event(linked)["start"]["dateTime"] == starts.isoformat()


async def test_mentioned_but_not_asked_its_a_card(scenario: Scenario, linked: FakeGcal) -> None:
    task = await bathroom(scenario)
    replies = await say(
        scenario,
        "I might do the bathroom after lunch",
        "block_time_for_task",
        {"task_id": task.id, "date": "2026-10-21", "start": "13:00", "end": "14:00"},
    )
    assert replies[0] == (
        "Time for Clean the bathroom: Wed 21 Oct, 1-2 pm, on your calendar\nGo ahead, or not now?"
    )


async def test_a_nudge_at_a_time_isnt_a_block(scenario: Scenario, linked: FakeGcal) -> None:
    """Bug #39: "can you prompt me to run at 2pm?" staged an hour on her calendar."""
    task = await bathroom(scenario)
    await say(
        scenario,
        "Can you prompt me to do the bathroom at 2pm?",
        "block_time_for_task",
        {"task_id": task.id, "date": "2026-10-21", "start": "14:00", "end": ""},
    )
    result = scenario.primary.last_request.messages[-1].content[0]
    assert "snooze_task" in result.content  # type: ignore[union-attr]
    assert result.is_error  # type: ignore[union-attr]
    assert not scenario.app.db.query("SELECT 1 FROM pending_actions")
    assert [e for e in linked.events(ERIN, ERIN)] == []


async def test_a_card_for_a_time_thats_past_lapses(scenario: Scenario, linked: FakeGcal) -> None:
    # Bug #64: "Time for Go for a run: Tue 27 Oct, 2-3 pm" still waited a day later, and the
    # model read it as a run not done.
    task = await bathroom(scenario)
    await say(
        scenario,
        "I might do the bathroom after lunch",
        "block_time_for_task",
        {"task_id": task.id, "date": "2026-10-21", "start": "13:00", "end": "14:00"},
    )
    await scenario.advance(hours=5)  # 14:00 has been and gone
    await scenario.run_periodic("approvals.expire")
    (status,) = [r["status"] for r in scenario.app.db.query("SELECT status FROM pending_actions")]
    assert status == "expired"
