"""The family calendar end to end: dated tasks → approval → job queue → fake Google Calendar."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.autonomy import Decision
from themi.connectors.google import GMAIL_SCOPE
from themi.core.tasks import Task, TaskBoard

FRIDAY = date(2026, 10, 30)


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    """Erin (an admin) has linked her Google account, calendar access included."""
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def task(
    scenario: Scenario, title: str = "Call the plumber", due: date | None = FRIDAY
) -> Task:
    return await board(scenario).create(scenario.member("Erin"), title, "call", 2, due)


def calendar_actions(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query(
        "SELECT id, status, summary FROM pending_actions WHERE category = 'calendar_write' "
        "ORDER BY id"
    )


async def approve(scenario: Scenario) -> None:
    (action,) = [a for a in calendar_actions(scenario) if a["status"] == "pending"]
    await scenario.app.services.autonomy.resolve(
        action["id"], Decision.APPROVE, by=scenario.member("Erin")
    )


def summaries(fake_gcal: FakeGcal) -> list[tuple[str, str]]:
    return [(e["summary"], e["start"]["date"]) for e in fake_gcal.events(ERIN)]


# ----- the done-when story --------------------------------------------------------


async def test_tasks_with_dates_appear_on_the_calendar(
    scenario: Scenario, linked: FakeGcal
) -> None:
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "Call the plumber",
            "kind": "call",
            "effort": 2,
            "due_date": "2026-10-30",
            "assign_to": "anyone",
            "steps": [],
            "check_in": False,
            "due_time": "",
            "from_time": "",
        },
    )
    scenario.primary.queue_text("Added, for Friday.")
    await scenario.say("Erin", "remind us to call the plumber on Friday")
    (action,) = calendar_actions(scenario)
    assert action["summary"] == "For the family calendar: Call the plumber, Fri Oct 30"
    assert (
        "For the family calendar: Call the plumber, Fri Oct 30\nGo ahead, or not now?"
        in scenario.inbox("Erin")
    )
    await scenario.run_jobs()
    assert linked.events(ERIN) == []  # nothing before the yes

    await scenario.tap("Erin", "Go ahead")
    await scenario.run_jobs()
    (event,) = linked.events(ERIN)
    assert (event["summary"], event["start"], event["end"]) == (
        "Call the plumber",
        {"date": "2026-10-30"},
        {"date": "2026-10-31"},
    )
    assert event["transparency"] == "transparent"
    assert event["description"].startswith("For ")
    assert linked.calls_to("create_calendar") == 1  # there was no "Themi" calendar yet

    await task(scenario, "Water the plants", due=None)
    assert len(calendar_actions(scenario)) == 1  # undated tasks stay off the calendar


async def test_upserts_are_idempotent(scenario: Scenario, linked: FakeGcal) -> None:
    made_by_hand = linked.add_calendar(ERIN, "Themi")
    first = await task(scenario)
    await approve(scenario)
    await scenario.run_jobs()
    assert linked.calls_to("create_calendar") == 0  # the family's own calendar is used
    assert linked.calendar(ERIN, "Themi").id == made_by_hand  # type: ignore[union-attr]

    for _ in range(3):  # the same write again, as a retry after a crash would
        TaskCalendarHelper(scenario).queue(first.id)
        await scenario.run_jobs()
    assert summaries(linked) == [("Call the plumber", "2026-10-30")]
    assert linked.calls_to("calendarList") == 1  # found once, then remembered

    # Insert-collides path: the update can't find it, the insert finds the id taken.
    linked.fail("update", 404)
    TaskCalendarHelper(scenario).queue(first.id)
    await scenario.run_jobs()
    assert summaries(linked) == [("Call the plumber", "2026-10-30")]
    assert linked.calls_to("insert") == 2  # the first write and the colliding one


class TaskCalendarHelper:
    """Queue a calendar write for a task, the way a task change does."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def queue(self, task_id: int) -> None:
        assert self.scenario.app.scheduler is not None
        self.scenario.app.scheduler.enqueue(
            "calendar.sync", {"source": "task", "id": task_id}, dedupe_key=f"t{task_id}"
        )


# ----- events follow their tasks ---------------------------------------------------


async def test_updates_and_deletes_follow_tasks(scenario: Scenario, linked: FakeGcal) -> None:
    plumber = await task(scenario)
    await approve(scenario)
    vet = await task(scenario, "Take the cat to the vet", due=FRIDAY + timedelta(days=3))
    await approve(scenario)
    await scenario.run_jobs()
    assert summaries(linked) == [
        ("Call the plumber", "2026-10-30"),
        ("Take the cat to the vet", "2026-11-02"),
    ]

    await board(scenario).reschedule(plumber.id, FRIDAY + timedelta(days=1))
    await scenario.run_jobs()
    assert summaries(linked)[0] == ("Call the plumber", "2026-10-31")

    await board(scenario).complete(plumber.id, scenario.member("Erin"))
    await scenario.run_jobs()
    assert summaries(linked)[0] == ("Done: Call the plumber", "2026-10-31")

    await board(scenario).cancel(vet.id, scenario.member("Erin"))
    await scenario.run_jobs()
    assert summaries(linked) == [("Done: Call the plumber", "2026-10-31")]

    gutters = await task(scenario, "Clear the gutters", due=FRIDAY)
    await approve(scenario)
    await scenario.run_jobs()
    await board(scenario).reschedule(gutters.id, None)  # no date any more: off the calendar
    await scenario.run_jobs()
    assert [s for s, _ in summaries(linked)] == ["Done: Call the plumber"]
    await board(scenario).reschedule(gutters.id, FRIDAY + timedelta(days=7))  # and back on
    await scenario.run_jobs()
    assert ("Clear the gutters", "2026-11-06") in summaries(linked)

    # Keeping approved events true never asked again.
    assert [a["status"] for a in calendar_actions(scenario)] == ["done", "done", "done"]


# ----- the tier --------------------------------------------------------------------


async def test_the_tier_is_honoured(scenario: Scenario, linked: FakeGcal) -> None:
    await task(scenario, "Book the dentist")
    (action,) = calendar_actions(scenario)
    await scenario.app.services.autonomy.resolve(
        action["id"], Decision.DECLINE, by=scenario.member("Erin")
    )
    await scenario.run_jobs()
    assert linked.events(ERIN) == []

    scenario.app.services.autonomy.grant_tier2(
        "calendar_write", via_rule_id=1, by=scenario.member("Erin")
    )
    await task(scenario, "Renew the car registration")
    assert calendar_actions(scenario)[-1]["status"] == "done"  # automatic: nobody was asked
    await scenario.run_jobs()
    assert summaries(linked) == [("Renew the car registration", "2026-10-30")]


# ----- errors ----------------------------------------------------------------------


async def test_errors_are_retried_via_the_job_queue(scenario: Scenario, linked: FakeGcal) -> None:
    await task(scenario)
    linked.fail("calendarList", 503)
    await approve(scenario)
    await scenario.run_jobs()
    (job,) = scenario.app.db.query("SELECT * FROM job_queue WHERE kind = 'calendar.sync'")
    assert (job["status"], job["attempts"], job["last_error"]) == ("queued", 1, "CalendarError")
    assert linked.events(ERIN) == []

    assert await scenario.run_jobs() == []  # backing off
    clock.advance(timedelta(minutes=1))
    linked.fail("insert", 500)
    await scenario.run_jobs()
    assert linked.events(ERIN) == []
    clock.advance(timedelta(minutes=5))
    await scenario.run_jobs()
    assert summaries(linked) == [("Call the plumber", "2026-10-30")]
    assert scenario.app.db.scalar("SELECT status FROM job_queue") == "done"


# ----- setup -----------------------------------------------------------------------


async def test_an_account_without_calendar_access_is_not_used(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/link gmail")
    callback = urlsplit(
        fake_google.consent(reply.splitlines()[-1], ERIN, scopes=("openid", "email", GMAIL_SCOPE))
    )
    await site.get(f"{callback.path}?{callback.query}")
    await task(scenario)
    assert calendar_actions(scenario) == []  # nothing to ask about yet
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/family")).text
    assert "was linked before Themi asked for calendar access" in page


async def test_choosing_the_calendar_on_the_family_page(
    scenario: Scenario, linked: FakeGcal, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/family")).text
    assert f'Writing to "Themi" on {ERIN}.' in page
    account = scenario.app.store.linked_account_by_address("gmail", ERIN)
    assert account is not None
    await site.post(
        "/family/calendar", data={"csrf": csrf, "account": str(account.id), "name": "Cozyla"}
    )
    assert "Saved the calendar settings." in await flash(site, "/family")
    await task(scenario)
    await approve(scenario)
    await scenario.run_jobs()
    assert [e["summary"] for e in linked.events(ERIN, "Cozyla")] == ["Call the plumber"]


async def test_personal_reminders_arent_offered_for_the_family_calendar(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """Idea #23 (Erin's rule 14, for everyone): "drink black tea tomorrow at 7" was offered
    for the family calendar. A task someone makes for themselves stays theirs."""
    erin = scenario.member("Erin")
    await board(scenario).create(
        erin, "Drink black tea", "physical", 1, date(2026, 10, 22), assignee=erin
    )
    assert calendar_actions(scenario) == []
    husband = scenario.member("Husband")
    await board(scenario).create(
        erin, "Fix the fence", "physical", 3, date(2026, 10, 23), assignee=husband
    )  # for someone else: the family calendar is where the other person sees it
    assert [a["summary"] for a in calendar_actions(scenario)] == [
        "For the family calendar: Fix the fence, Fri Oct 23"
    ]
