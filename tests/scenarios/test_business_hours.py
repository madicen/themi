"""F34k (Erin's idea #177): a call before the business closes. The clock starts Wednesday
21 October 2026, 9 am; Erin's quiet hours start at 9:30 pm."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tests.fakes.search import FakeSearch
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi.standard.tasks import Task, TaskBoard

PACIFIC = ZoneInfo("America/Los_Angeles")
WED, THU, SUN = date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 25)
DENTIST = "Rosewood Dental. Hours: Mon-Fri 8am-5pm, Sat 9am-1pm, Sun closed. (650) 555-0100"
NUDGE = "Rosewood Dental closes at 5 pm today. Call now, or later?"


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


@pytest.fixture
def searching(scenario: Scenario, fake_search: FakeSearch) -> FakeSearch:
    search = scenario.app.services.maybe(keys.web_search)
    assert search is not None
    search.backend = fake_search.client()
    fake_search.result("dentist hours", "Rosewood Dental | Palo Alto", "https://rd.example",
                       DENTIST)  # fmt: skip
    return fake_search


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> list[str]:
    before = len(scenario.inbox("Erin"))
    target = datetime(day.year, day.month, day.day, hour, minute, tzinfo=PACIFIC)
    clock.advance(target - clock.now())
    await scenario.run_periodic("tasks.closing")
    await scenario.app.outbox.flush()
    return scenario.inbox("Erin")[before:]


async def call(scenario: Scenario, title: str = "Call the dentist") -> Task:
    erin = scenario.member("Erin")
    return await board(scenario).create(erin, title, "call", 1, assignee=erin, nudge=False)


async def test_the_hours_are_kept_and_the_nudge_comes_before_closing(
    scenario: Scenario, searching: FakeSearch
) -> None:
    task = await call(scenario)
    assert await at(scenario, WED, 9, 15) == []
    (item,) = [i.summary for i in board(scenario).open_items(scenario.member("Erin"))]
    assert "Rosewood Dental: open until 5 pm today" in item
    assert await at(scenario, WED, 15, 15) == []
    assert await at(scenario, WED, 15, 30) == [NUDGE]
    assert scenario.last_buttons("Erin") == ["Call now", "Later, voicemail's fine",
                                             "Next open day"]  # fmt: skip
    assert await at(scenario, WED, 15, 45) == []  # once a day
    assert len(searching.queries()) == 1  # looked up once
    del task


async def test_later_waits_until_after_closing(scenario: Scenario, searching: FakeSearch) -> None:
    task = await call(scenario)
    await at(scenario, WED, 15, 30)
    await scenario.tap("Erin", "Later, voicemail's fine")
    until = board(scenario).put_off_until(board(scenario).get(task.id), scenario.member("Erin"))
    assert until is not None and until.astimezone(PACIFIC).strftime("%H:%M") == "17:05"


async def test_next_open_day_waits_until_an_hour_after_opening(
    scenario: Scenario, searching: FakeSearch
) -> None:
    task = await call(scenario)
    await at(scenario, WED, 15, 30)
    await scenario.tap("Erin", "Next open day")
    until = board(scenario).put_off_until(board(scenario).get(task.id), scenario.member("Erin"))
    assert until is not None
    assert until.astimezone(PACIFIC) == datetime(2026, 10, 22, 9, tzinfo=PACIFIC)
    assert "Thursday after 9 am" in scenario.edits("Erin")[-1]["text"]


async def test_call_now_gives_the_number(scenario: Scenario, searching: FakeSearch) -> None:
    await call(scenario)
    await at(scenario, WED, 15, 30)
    await scenario.tap("Erin", "Call now")
    assert scenario.edits("Erin")[-1]["text"].startswith("Rosewood Dental: (650) 555-0100")


async def test_not_on_a_day_its_closed(scenario: Scenario, searching: FakeSearch) -> None:
    await call(scenario)
    await at(scenario, WED, 9, 15)
    assert await at(scenario, SUN, 15, 30) == []


async def test_unknown_hours_said_once_and_no_nudge(
    scenario: Scenario, searching: FakeSearch
) -> None:
    await call(scenario, "Call Acme Plumbing about the leak")
    sent = await at(scenario, WED, 9, 15)
    assert any("couldn't find Acme Plumbing's hours" in t for t in sent)
    assert await at(scenario, WED, 15, 30) == []
    assert not any("couldn't find" in t for t in await at(scenario, THU, 9, 15))


async def test_not_people_or_tasks_without_a_business(
    scenario: Scenario, searching: FakeSearch
) -> None:
    await call(scenario, "Call mom")
    await call(scenario, "Call back about the quote")
    await at(scenario, WED, 9, 15)
    assert searching.queries() == []


async def test_hours_said_in_chat_are_kept_for_the_place(
    scenario: Scenario, searching: FakeSearch
) -> None:
    task = await call(scenario)
    await at(scenario, WED, 9, 15)
    scenario.primary.queue_tool_call(
        "set_business_hours", {"task_id": task.id, "hours": "Mon-Thu 8-4, Fri 8-noon"}
    )
    scenario.primary.queue_text("Got it.")
    await scenario.say("Erin", "the dentist actually closes at 4 on weekdays, noon Fridays")
    assert await at(scenario, WED, 14, 30) == [
        "Rosewood Dental closes at 4 pm today. Call now, or later?"
    ]
    later = await call(scenario, "Call the dentist about the bill")
    await at(scenario, THU, 9, 15)
    assert len(searching.queries()) == 1  # the place's hours, remembered
    assert "open until 4 pm today" in " ".join(
        i.summary
        for i in board(scenario).open_items(scenario.member("Erin"))
        if f"Task {later.id} " in i.summary
    )


async def test_not_in_quiet_hours(scenario: Scenario, searching: FakeSearch) -> None:
    searching.result("luigi's trattoria hours", "Luigi's Trattoria", "https://luigi.example",
                     "Open daily 11am-11pm")  # fmt: skip
    await call(scenario, "Call Luigi's Trattoria to book a table")
    await at(scenario, WED, 9, 15)
    sent = [*await at(scenario, WED, 21, 30), *await at(scenario, WED, 22, 15)]
    sent += await at(scenario, THU, 8, 0)
    assert not any("closes at" in t for t in sent)
