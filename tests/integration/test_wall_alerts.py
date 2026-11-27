"""The wall's alerts (WA1 onwards): leaving from K4's heads-ups, read without a lookup.

Wednesday 21 October 2026 in Los Angeles. Erin's dentist is at 3 pm, 35 minutes away: the
heads-up goes at 2:10 ("leave around 2:25"), and the wall's card shows from then.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.travel import FakeTravel
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import with_wall
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.core import keys
from themi.core.calendar_view import CalendarPreferences
from themi_google.travel import TravelPreferences
from themi_home.wall_view import WallView

PACIFIC = ZoneInfo("America/Los_Angeles")
HOME = "12 Main St, Springfield"


def local(hour: int, minute: int = 0, day: int = 21) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC).isoformat()


@pytest.fixture
async def leaving(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    fake_google: FakeGoogle,
    fake_gcal: FakeGcal,
    fake_travel: FakeTravel,
) -> AsyncIterator[Scenario]:
    """The wall, Erin's calendar linked, home saved, and the dentist on the map."""
    s = with_wall(family, fake_telegram, google=fake_google, gcal=fake_gcal, travel=fake_travel)
    await s.start()
    try:
        async with web_client(s) as site:
            await link(s, site, fake_google, "Erin", ERIN)
        fake_travel.place(HOME, 37.700, -122.400)
        fake_travel.place("Smile Dental", 37.780, -122.420)
        travel = s.app.services.maybe(keys.travel)
        assert travel is not None
        await travel.set_home(HOME)
        fake_travel.minutes = 35
        yield s
    finally:
        await s.stop()


def share(s: Scenario, name: str = "Erin") -> None:
    member = s.member(name)
    s.app.store.save_preferences(member, member.id, CalendarPreferences, calendar_details="partner")


async def at(s: Scenario, hour: int, minute: int = 0, second: int = 0) -> None:
    """Move to that local time, read the calendar, and run the heads-up job."""
    target = datetime(2026, 10, 21, hour, minute, second, tzinfo=PACIFIC)
    clock.advance(target - clock.now())
    await s.run_periodic("calendar.busy")
    await s.run_periodic("travel.heads_up")


def cards(s: Scenario) -> list[tuple[str, str, str]]:
    return [(a.state, a.title, a.numerals) for a in WallView(s.app.services).alerts()]


async def test_the_card_comes_with_the_heads_up_and_counts_to_leave_by(
    leaving: Scenario, fake_gcal: FakeGcal
) -> None:
    share(leaving)
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(leaving, 14)
    assert cards(leaving) == []
    await at(leaving, 14, 10)  # the heads-up is sent, up to five minutes early
    await at(leaving, 14, 12, 20)
    assert cards(leaving) == [("ready", "Dentist at 3:00", "12:40")]
    await at(leaving, 14, 20, 50)
    assert cards(leaving) == [("almost", "Dentist at 3:00", "4:10")]
    await at(leaving, 14, 25)
    assert cards(leaving) == [("go", "Dentist at 3:00", "Time to go")]
    await at(leaving, 14, 28)
    assert cards(leaving) == [("behind", "Leaving now", "3:03")]
    await at(leaving, 15)
    assert cards(leaving) == []


async def test_the_wall_never_looks_a_drive_up(
    leaving: Scenario, fake_gcal: FakeGcal, fake_travel: FakeTravel
) -> None:
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(leaving, 14, 10)
    routes = fake_travel.count("route")
    for _ in range(3):
        WallView(leaving.app.services).alerts()
    assert fake_travel.count("route") == routes


async def test_a_private_event_shows_the_leave_time_only(
    leaving: Scenario, fake_gcal: FakeGcal
) -> None:
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(leaving, 14, 12)
    (alert,) = WallView(leaving.app.services).alerts()
    assert alert.title == "Leaving at 2:25"
    assert "Dentist" not in repr(alert) and "Smile" not in repr(alert)


async def test_heads_ups_off_and_a_moved_or_gone_event_show_nothing(
    leaving: Scenario, fake_gcal: FakeGcal
) -> None:
    eid = fake_gcal.add_event(
        ERIN, local(15), local(16), summary="Dentist", location="Smile Dental"
    )
    await at(leaving, 14, 12)
    assert len(cards(leaving)) == 1
    erin = leaving.member("Erin")
    leaving.app.store.save_preferences(erin, erin.id, TravelPreferences, leave_heads_up=False)
    assert cards(leaving) == []
    leaving.app.store.save_preferences(erin, erin.id, TravelPreferences, leave_heads_up=True)
    fake_gcal.calendar(ERIN, ERIN).events[eid].update(  # type: ignore[union-attr]
        start={"dateTime": local(17)}, end={"dateTime": local(18)}
    )
    await at(leaving, 14, 13)
    assert cards(leaving) == []  # moved to 5 pm: the 3 pm heads-up's card has gone


async def test_a_heads_up_first_sent_late_starts_where_it_stands(
    leaving: Scenario, fake_gcal: FakeGcal
) -> None:
    share(leaving)
    await at(leaving, 14, 21)  # Themi was down: nothing sent yet
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(leaving, 14, 21, 30)
    assert cards(leaving) == [("almost", "Dentist at 3:00", "3:30")]


async def test_two_trips_the_sooner_leave_by_first(
    leaving: Scenario, fake_gcal: FakeGcal, fake_travel: FakeTravel
) -> None:
    share(leaving)
    fake_travel.place("Pharmacy", 37.710, -122.410)
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    fake_gcal.add_event(ERIN, local(15, 20), local(16), summary="Pharmacy", location="Pharmacy")
    await at(leaving, 14, 30)
    await at(leaving, 14, 31)
    shown = WallView(leaving.app.services).alerts()
    assert [(a.state, a.label) for a in shown] == [("behind", "Dentist at 3:00")]
