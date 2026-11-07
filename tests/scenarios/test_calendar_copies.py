"""F34f (Erin's idea #175): a calendar of theirs shown on the family calendar, at the level
of detail they chose. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_calendar_events import PACIFIC, local
from tests.scenarios.test_triage import ERIN, link
from themi.core import keys
from themi.core.calendar_copies import CalendarCopies

GUESTS = [{"email": ERIN, "self": True}, {"email": "boss@example.com"}]


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


def copies(scenario: Scenario) -> CalendarCopies:
    found = scenario.app.services.maybe(keys.calendar_copies)
    assert found is not None
    return found


def account_id(scenario: Scenario) -> int:
    return int(scenario.app.db.scalar("SELECT id FROM linked_accounts WHERE member_id = ?",
                                      (scenario.member("Erin").id,)))  # fmt: skip


async def work_calendar(scenario: Scenario, fake: FakeGcal, level: str = "label") -> str:
    work = fake.add_calendar(ERIN, "Work")
    calendars = scenario.app.services.maybe(keys.calendars)
    assert calendars is not None
    calendars.choose(account_id(scenario), [("primary", "primary"), (work, "Work")])
    await copies(scenario).set_rule(scenario.member("Erin"), account_id(scenario), work, "Work",
                                    level)  # fmt: skip
    return work


async def read(scenario: Scenario) -> None:
    await scenario.run_periodic("calendar.busy")


def family(fake: FakeGcal) -> list[dict]:
    return fake.events(ERIN, "Themi")


async def test_work_events_show_as_labels_on_the_family_calendar(
    scenario: Scenario, linked: FakeGcal
) -> None:
    work = await work_calendar(scenario, linked)
    linked.add_event(ERIN, local(10, day=27), local(11, day=27), summary="1:1 with Dana",
                     calendar=work, attendees=GUESTS, location="Room 4",
                     description="Talk about the reorg")  # fmt: skip
    linked.add_event(ERIN, local(13, day=27), local(15, day=27), summary="Focus time",
                     calendar=work)  # fmt: skip
    linked.add_event(ERIN, local(16, day=27), local(17, day=27), summary="Expense reports",
                     calendar=work)  # fmt: skip
    await read(scenario)
    shown = {e["summary"]: e for e in family(linked)}
    assert set(shown) == {"Erin work meeting", "Erin focus block", "Erin busy"}
    meeting = shown["Erin work meeting"]
    assert meeting["start"]["dateTime"].startswith("2026-10-27T10:00")
    for copy in shown.values():
        assert not copy.get("location") and not copy.get("description")
        assert not copy.get("attendees")
        assert copy["extendedProperties"]["private"]["themi"].startswith("copy:")
        assert copy["transparency"] == "transparent"  # never makes anyone else look busy
    text = repr(family(linked))
    assert "reorg" not in text and "Room 4" not in text and "Dana" not in text


async def test_a_moved_or_deleted_event_takes_its_copy_with_it(
    scenario: Scenario, linked: FakeGcal
) -> None:
    work = await work_calendar(scenario, linked)
    standup = linked.add_event(ERIN, local(9, day=27), local(9, 15, day=27), summary="Standup",
                               calendar=work, attendees=GUESTS)  # fmt: skip
    await read(scenario)
    (copy,) = family(linked)
    linked.move_event(ERIN, standup, local(9, 30, day=27), local(9, 45, day=27), calendar=work)
    await read(scenario)
    (copy,) = family(linked)
    assert copy["start"]["dateTime"].startswith("2026-10-27T09:30")
    linked.delete_event(ERIN, standup, calendar=work)
    await read(scenario)
    assert family(linked) == []


async def test_title_only_busy_only_and_full_details(scenario: Scenario, linked: FakeGcal) -> None:
    work = await work_calendar(scenario, linked, "title")
    linked.add_event(ERIN, local(10, day=27), local(11, day=27), summary="Budget review",
                     calendar=work, location="Room 4", description="numbers")  # fmt: skip
    await read(scenario)
    (copy,) = family(linked)
    assert copy["summary"] == "Budget review" and not copy.get("location")

    await copies(scenario).set_rule(scenario.member("Erin"), account_id(scenario), work, "Work",
                                    "busy")  # fmt: skip
    await read(scenario)
    (copy,) = family(linked)
    assert copy["summary"] == "Busy"

    await copies(scenario).set_rule(scenario.member("Erin"), account_id(scenario), work, "Work",
                                    "full")  # fmt: skip
    await read(scenario)
    (copy,) = family(linked)
    assert (copy["summary"], copy["location"]) == ("Budget review", "Room 4")
    assert "numbers" not in repr(copy)  # notes stay on the work calendar


async def test_a_copy_isnt_copied_back_or_taken_for_a_twin(
    scenario: Scenario, linked: FakeGcal
) -> None:
    """Reading the family calendar too, a full copy is the same title and times as its
    source on two calendars: never offered as a merge (F34e), never copied again."""
    work = await work_calendar(scenario, linked, "full")
    linked.add_event(ERIN, local(10, day=27), local(11, day=27), summary="Budget review",
                     calendar=work)  # fmt: skip
    await read(scenario)
    family_id = scenario.app.db.scalar("SELECT calendar_id FROM calendars")
    calendars = scenario.app.services.maybe(keys.calendars)
    assert calendars is not None
    calendars.choose(account_id(scenario), [("primary", "primary"), (work, "Work"),
                                            (family_id, "Themi")])  # fmt: skip
    before = len(scenario.inbox("Erin"))
    await read(scenario)
    await read(scenario)
    await scenario.app.outbox.flush()
    assert len(family(linked)) == 1
    assert scenario.inbox("Erin")[before:] == []
    start = datetime(2026, 10, 27, tzinfo=PACIFIC)
    shown = calendars.entries(scenario.member("Erin"), start, start + timedelta(days=1))
    assert [e.title for e in shown] == ["Budget review"]  # her own, not its copy as well
    assert (
        scenario.app.db.scalar(
            "SELECT COUNT(*) FROM calendar_entries WHERE title = 'Budget review'"
        )
        == 2
    )  # both were read


async def test_turning_it_off_takes_the_copies_away(scenario: Scenario, linked: FakeGcal) -> None:
    work = await work_calendar(scenario, linked)
    linked.add_event(ERIN, local(10, day=27), local(11, day=27), summary="Standup",
                     calendar=work)  # fmt: skip
    await read(scenario)
    assert len(family(linked)) == 1
    await copies(scenario).set_rule(scenario.member("Erin"), account_id(scenario), work, "Work",
                                    "off")  # fmt: skip
    assert family(linked) == []


async def test_the_calendars_page_sets_the_rule_and_the_labels(
    scenario: Scenario, linked: FakeGcal, site: httpx.AsyncClient
) -> None:
    work = linked.add_calendar(ERIN, "Work")
    calendars = scenario.app.services.maybe(keys.calendars)
    assert calendars is not None
    calendars.choose(account_id(scenario), [("primary", "primary"), (work, "Work")])
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get(f"/accounts/{account_id(scenario)}/calendars")).text
    assert "Shown on the family calendar" in page
    response = await site.post(
        f"/accounts/{account_id(scenario)}/calendars/shown",
        data={"csrf": csrf, f"level_{work}": "label", f"name_{work}": "Work",
              "label_meeting": "Mom in a meeting", "label_focus": "Mom focusing",
              "label_other": "Mom busy"},
    )  # fmt: skip
    assert response.status_code == 303
    linked.add_event(ERIN, local(10, day=27), local(11, day=27), summary="Sync",
                     calendar=work, attendees=GUESTS)  # fmt: skip
    await read(scenario)
    assert [e["summary"] for e in family(linked)] == ["Mom in a meeting"]
