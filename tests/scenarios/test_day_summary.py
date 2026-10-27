"""K2: a summary of the day, on request and as a morning message. The clock starts
Wednesday 21 October 2026, 9 am; Erin's quiet hours are 21:30-08:00."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.ai.types import ToolResult
from themi.core.progression import parse_plan
from themi.core.repeat import parse
from themi.core.tasks import TaskBoard

PACIFIC = ZoneInfo("America/Los_Angeles")
HUSBAND = "him@gmail.com"
WED = date(2026, 10, 21)
TODAY = (  # Erin's day in the format she asked for (idea #19), untouched by the shield
    "Wed 21 Oct:\n"
    "- 10-11 am: Dentist (at Smile Dental)\n"
    "- 12-1 pm: Standup (video call)\n"
    "- 2 pm: Go for a run (check-in, 1.3 miles this week)\n"
    "- Return the library books (since Mon 19 Oct)\n"
    "- Call the vet"
)


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


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


async def erins_day(scenario: Scenario, fake: FakeGcal) -> None:
    fake.add_event(ERIN, local(10), local(11), summary="Dentist", location="Smile Dental")
    fake.add_event(
        ERIN, local(12), local(13), summary="Standup", hangoutLink="https://meet.google.com/x"
    )
    fake.add_event(ERIN, local(10, day=22), local(11, day=22), summary="Tomorrow's thing")
    await scenario.run_periodic("calendar.busy")
    erin = scenario.member("Erin")
    await board(scenario).create(erin, "Call the vet", "call", 1, WED, assignee=erin)
    await board(scenario).create(
        erin, "Return the library books", "errand", 1, WED - timedelta(days=2), assignee=erin
    )
    await board(scenario).create(erin, "Someday thing", "errand", 1, assignee=erin)  # no date
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(run.id, erin, repeat=parse("every Wednesday at 2pm", WED))
    board(scenario).set_progression(run.id, erin, parse_plan("1.3 miles, then 1.5", WED))


async def test_what_is_on_today_on_request(scenario: Scenario, linked: FakeGcal) -> None:
    await erins_day(scenario, linked)
    scenario.primary.queue_tool_call("day_summary", {"date": "", "partner": False})
    scenario.primary.queue_text("Here's your day.")
    replies = await scenario.say("Erin", "What's my day look like?")
    assert replies[0] == TODAY  # sent as it is (idea #19), in the order of the day
    assert '<data source="day summary">' in tool_result(scenario)
    assert "Don't repeat it" in tool_result(scenario)
    scenario.primary.queue_tool_call("day_summary", {"date": "2026-10-22", "partner": False})
    scenario.primary.queue_text("Tomorrow.")
    replies = await scenario.say("Erin", "And tomorrow?")
    assert replies[0] == "Thu 22 Oct:\n- 10-11 am: Tomorrow's thing"


async def test_a_chore_waiting_for_the_chart_is_in_tomorrows_summary(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """Idea #19: Erin's bird cage, her one chart chore, was missing from tomorrow's list,
    because today it's still waiting its turn."""
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, chart_limit=1)
    cage = await board(scenario).create(
        erin, "Clean the bird cage", "physical", 2, assignee=erin, nudge=False
    )
    await board(scenario).set_schedule(cage.id, erin, repeat=parse("every Thursday", WED))
    summary = scenario.app.services.day_summary
    assert summary is not None
    assert summary.text(erin, date(2026, 10, 22)) == "Thu 22 Oct:\n- Clean the bird cage"


async def test_the_partners_events_only_when_they_share(
    scenario: Scenario, linked: FakeGcal, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    await link(scenario, site, fake_google, "Husband", HUSBAND)
    linked.add_event(HUSBAND, local(15), local(16), summary="Haircut")
    await scenario.run_periodic("calendar.busy")

    async def ask() -> str:
        scenario.primary.queue_tool_call("day_summary", {"date": "", "partner": True})
        scenario.primary.queue_text("Okay.")
        await scenario.say("Erin", "What are we doing today?")
        return tool_result(scenario)

    assert "Haircut" not in await ask()
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(husband, husband.id, calendar_details="partner")
    assert "3-4 pm: Haircut (Husband)" in await ask()


async def test_the_morning_summary(scenario: Scenario, linked: FakeGcal) -> None:
    await erins_day(scenario, linked)
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, morning_summary="08:30")
    await scenario.run_periodic("calendar.morning")  # 9 am: today's is due, and goes
    summaries = [t for t in scenario.inbox("Erin") if t.startswith("Wed 21 Oct:")]
    assert summaries == [TODAY]
    await scenario.run_periodic("calendar.morning")
    assert len([t for t in scenario.inbox("Erin") if t.startswith("Wed 21 Oct:")]) == 1  # once


async def test_a_summary_set_in_quiet_hours_waits_and_empty_days_are_skipped(
    scenario: Scenario,
) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, morning_summary="06:00")
    clock.advance(timedelta(hours=21))  # Thursday 6 am, in her quiet hours; nothing on
    await scenario.run_periodic("calendar.morning")
    assert scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'summary'") == []

    scenario.app.store.update_settings(erin, erin.id, morning_summary_empty=True)
    clock.advance(timedelta(days=1))  # Friday 6 am
    await scenario.run_periodic("calendar.morning")
    (row,) = scenario.app.db.query(
        "SELECT status, send_after, text FROM outbox WHERE kind = 'summary'"
    )
    assert row["text"] == "Fri 23 Oct: nothing on the calendar, nothing due."
    assert row["status"] == "queued"  # until her quiet hours end
    assert datetime.fromisoformat(row["send_after"]) == datetime(2026, 10, 23, 8, tzinfo=PACIFIC)


async def test_the_settings_page(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    form = {
        "csrf": csrf,
        "quiet_start": "21:30",
        "quiet_end": "07:00",
        "daily_limit": "12",
        "morning_summary": "07:45",
        "morning_summary_empty": "on",
        "calendar_details": "me",
    }
    assert 'name="morning_summary"' in page
    await site.post("/settings", data=form)
    erin = scenario.member("Erin")
    assert erin.morning_summary is not None and erin.morning_summary.strftime("%H:%M") == "07:45"
    assert erin.morning_summary_empty
    await site.post("/settings", data={**form, "morning_summary": ""})
    assert scenario.member("Erin").morning_summary is None  # blank: off
