"""F42a (bug #201): a timed event that covers a whole local day or more is an all-day event:
kept, but not busy time, and written as all day. Michael's untitled midnight-to-midnight
holidays held his evening routine check until it expired. The clock starts Wednesday 21
October 2026, 9 am (Los Angeles); Erin's quiet hours start at 21:30, so her Evening routine
ends at 20:30."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_routines import add, at, checks
from tests.scenarios.test_triage import ERIN, link
from themi.core import keys

PACIFIC = ZoneInfo("America/Los_Angeles")
WED = date(2026, 10, 21)


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


def kept(scenario: Scenario) -> list[tuple[object, ...]]:
    rows = scenario.app.db.query("SELECT * FROM calendar_entries ORDER BY starts_at, id")
    return [(r["title"], r["all_day"], r["busy"]) for r in rows]


def busy(scenario: Scenario) -> list[dict[str, object]]:
    return scenario.app.db.query("SELECT * FROM calendar_busy")


def sent(scenario: Scenario, name: str) -> list[tuple[str, str]]:
    rows = scenario.app.db.query(
        "SELECT status, sent_at FROM outbox WHERE member_id = ? AND kind = 'routine' ORDER BY id",
        (scenario.member(name).id,),
    )
    return [(r["status"], r["sent_at"]) for r in rows]


async def test_a_whole_day_timed_event_doesnt_hold_the_evening_check(
    scenario: Scenario, linked: FakeGcal
) -> None:
    linked.add_event(ERIN, local(0), local(0, day=22), summary="(no title)")
    await scenario.run_periodic("calendar.busy")
    assert kept(scenario) == [("(no title)", 1, 0)]
    assert busy(scenario) == []
    add(scenario, "Erin", "Evening", "Take meds")
    await at(scenario, WED, 20, 30)
    assert checks(scenario, "Erin") == ["Evening routine, still open:\n- Take meds\nDone already?"]
    await at(scenario, WED, 20, 45)
    ((status, when),) = sent(scenario, "Erin")
    assert status == "sent"
    assert datetime.fromisoformat(when).astimezone(PACIFIC).date() == WED


async def test_two_whole_days_are_all_day_and_part_days_are_not(
    scenario: Scenario, linked: FakeGcal
) -> None:
    linked.add_event(ERIN, local(0), local(0, day=23), summary="Conference")
    linked.add_event(ERIN, local(22), local(6, day=22), summary="Night shift")
    linked.add_event(  # midnight to midnight UTC isn't a local day
        ERIN, "2026-10-21T00:00:00+00:00", "2026-10-22T00:00:00+00:00", summary="UTC day"
    )
    await scenario.run_periodic("calendar.busy")
    assert sorted(kept(scenario)) == [
        ("Conference", 1, 0),
        ("Night shift", 0, 1),
        ("UTC day", 0, 1),
    ]


async def test_the_morning_message_says_all_day(scenario: Scenario, linked: FakeGcal) -> None:
    linked.add_event(ERIN, local(0), local(0, day=22), summary="Holiday")
    linked.add_event(ERIN, local(10), local(11), summary="Dentist")
    await scenario.run_periodic("calendar.busy")
    summary = scenario.app.services.get(keys.day_summary)
    lines = summary.items(scenario.member("Erin"), WED, partner=True, tasks=False)
    assert lines == ["all day: Holiday", "10-11 am: Dentist"]
