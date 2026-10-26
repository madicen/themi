"""The Shadow Calendar's new inputs (S2): Google Calendar busy blocks, which also hold
Themi's messages, task load, and the wind-down after long busy times."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi.channels.outbox import Priority

PACIFIC = ZoneInfo("America/Los_Angeles")


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


def blocks(scenario: Scenario) -> list[tuple[str, str]]:
    rows = scenario.app.db.query("SELECT * FROM calendar_busy ORDER BY starts_at")
    return [(r["starts_at"], r["ends_at"]) for r in rows]


async def test_busy_events_are_kept_without_their_details(
    scenario: Scenario, linked: FakeGcal
) -> None:
    linked.add_event(ERIN, local(10), local(11), summary="Therapy")
    linked.add_event(ERIN, "2026-10-22", "2026-10-23", all_day=True, summary="Holiday")
    linked.add_event(ERIN, local(13), local(14), transparency="transparent")  # shown as free
    linked.add_event(ERIN, local(15), local(16), declined=True)
    linked.add_event(ERIN, local(17), local(18), status="cancelled")
    await scenario.run_periodic("calendar.busy")
    ((start, end),) = blocks(scenario)
    assert datetime.fromisoformat(start) == datetime(2026, 10, 21, 10, tzinfo=PACIFIC)
    assert datetime.fromisoformat(end) == datetime(2026, 10, 21, 11, tzinfo=PACIFIC)
    columns = [c["name"] for c in scenario.app.db.query("PRAGMA table_info(calendar_busy)")]
    assert not any(c in columns for c in ("summary", "title", "attendees"))


async def test_messages_wait_out_a_busy_event(scenario: Scenario, linked: FakeGcal) -> None:
    linked.add_event(ERIN, local(10), local(11))
    await scenario.run_periodic("calendar.busy")
    await scenario.advance(hours=1, minutes=15)  # 10:15, in the meeting
    erin = scenario.member("Erin")
    held = await scenario.app.outbox.send(erin, "The washer finished.", priority=Priority.NORMAL)
    assert held.status == "queued"
    assert held.send_after == datetime(2026, 10, 21, 11, tzinfo=PACIFIC)
    reply = await scenario.app.outbox.send(erin, "Sure.", priority=Priority.REPLY)
    assert reply.status == "sent"


async def test_the_calendar_switch_turns_it_off(scenario: Scenario, linked: FakeGcal) -> None:
    from themi.accounts import SYSTEM

    linked.add_event(ERIN, local(10), local(11))
    await scenario.run_periodic("calendar.busy")
    scenario.app.store.update_settings(
        SYSTEM, scenario.member("Erin").id, tracking={"calendar": False}
    )
    await scenario.run_periodic("calendar.busy")
    assert blocks(scenario) == []


async def test_a_calendar_outage_keeps_what_was_known(scenario: Scenario, linked: FakeGcal) -> None:
    linked.add_event(ERIN, local(10), local(11))
    await scenario.run_periodic("calendar.busy")
    linked.fail("list_events", 500)
    await scenario.run_periodic("calendar.busy")
    assert len(blocks(scenario)) == 1


async def test_no_google_means_no_calendar_job(scenario: Scenario) -> None:
    assert not any(t.name == "calendar.busy" for t in scenario.app.periodic)


async def test_a_busy_event_lowers_the_estimate(scenario: Scenario, linked: FakeGcal) -> None:
    erin = scenario.member("Erin")
    energy = scenario.app.services.energy
    meeting = datetime(2026, 10, 21, 10, 30, tzinfo=PACIFIC)
    before = energy.capacity(erin, meeting)  # type: ignore[attr-defined]
    linked.add_event(ERIN, local(10), local(12))
    await scenario.run_periodic("calendar.busy")
    assert energy.capacity(erin, meeting) < before  # type: ignore[attr-defined]
    after_it = datetime(2026, 10, 21, 12, 30, tzinfo=PACIFIC)  # the hour after a long one
    assert energy.capacity(erin, after_it) < energy.baseline(erin, after_it)  # type: ignore[attr-defined]


async def test_a_long_busy_time_is_followed_by_a_wind_down(scenario: Scenario) -> None:
    from themi.accounts import SYSTEM, BusyTime

    erin = scenario.app.store.update_settings(
        SYSTEM, scenario.member("Erin").id,
        busy_times=[BusyTime((0, 1, 2, 3, 4), time(9), time(17))],
    )  # fmt: skip
    energy = scenario.app.services.energy
    after_work = datetime(2026, 10, 21, 17, 30, tzinfo=PACIFIC)
    later = after_work + timedelta(hours=2)
    dip = energy.baseline(erin, after_work) - energy.capacity(erin, after_work)  # type: ignore[attr-defined]
    assert dip > 0
    assert energy.capacity(erin, later) == pytest.approx(energy.baseline(erin, later), abs=1)  # type: ignore[attr-defined]


async def test_a_pile_of_overdue_tasks_counts_against_more(scenario: Scenario) -> None:
    from datetime import date

    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    matcher = board.matcher
    before = matcher.spare(erin, "text", 2)
    for n in range(4):
        await board.create(erin, f"Old thing {n}", "errand", 1, date(2026, 10, 1), assignee=erin)
    assert matcher.spare(erin, "text", 2) < before
    for n in range(20):
        await board.create(erin, f"More {n}", "errand", 1, date(2026, 10, 1), assignee=erin)
    assert before - matcher.spare(erin, "text", 2) <= 15  # capped
