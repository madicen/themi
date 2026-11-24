"""F59f (Michael's idea #258): the calendar on the wall opens its own screen: a day at a time
with ‹ ›, or a month, Monday first, to jump around in; from six months back to a year ahead.
The scenario's day is Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re

from tests.fakes.gcal_api import FakeGcal
from tests.integration.test_wall_screen import calendar, share, words
from tests.integration.test_wall_views import get
from tests.integration.test_wall_list_views import post
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import local
from tests.scenarios.test_triage import ERIN
from themi import clock
from datetime import timedelta

__all__ = ["calendar"]  # the fixture


def titles(view: str) -> list[str]:
    return re.findall(r'<span class="tl-title">([^<]+)</span>', view)


def month_cells(view: str) -> list[str]:
    return re.findall(r'class="cal-day[^"]*" role="gridcell" aria-label="([0-9-]+)"', view)


async def test_a_day_has_its_events_in_order_and_moves_a_day_at_a_time(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(15, day=23), local(16, day=23), summary="Tea Time!")
    fake_gcal.add_event(ERIN, local(7, day=23), local(8, day=23), summary="Early swim")
    await calendar.run_periodic("calendar.busy")
    view = (await get(calendar, "/wall/calendar?day=2026-10-23")).text
    assert titles(view) == ["Early swim", "Tea Time!"]
    assert "In 2 days Friday, October 23" in words(view)
    assert 'hx-get="/wall/calendar?day=2026-10-22"' in view
    assert 'hx-get="/wall/calendar?day=2026-10-24"' in view
    assert ">Today</button>" in view  # back to today


async def test_today_has_a_now_line_and_past_days_no_weather(calendar: Scenario) -> None:
    today = (await get(calendar, "/wall/calendar")).text
    assert "tl-now" in today and "Wednesday, October 21" in today
    assert ">Today</button>" not in today
    past = (await get(calendar, "/wall/calendar?day=2026-10-01")).text
    assert "20 days ago" in words(past) and "Weather" not in past


async def test_it_goes_six_months_back_and_a_year_ahead(calendar: Scenario) -> None:
    async def status(query: str) -> int:
        return (await get(calendar, f"/wall/calendar?{query}")).status_code

    assert await status("day=2026-04-01") == 200  # April is six months back
    assert await status("day=2026-03-31") == 404
    assert await status("month=2026-04") == 200
    assert await status("month=2026-03") == 404
    assert await status("month=2027-10") == 200  # a year ahead, to the month's end
    assert await status("day=2027-10-31") == 200
    assert await status("month=2027-11") == 404
    assert await status("day=nonsense") == 404
    edge = (await get(calendar, "/wall/calendar?month=2026-04")).text
    assert "The month before" not in edge and "The month after" in edge


async def test_a_month_starts_on_monday_with_up_to_three_chips_a_day(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    for hour, name in ((8, "One"), (10, "Two"), (12, "Three"), (14, "Four")):
        fake_gcal.add_event(ERIN, local(hour, day=28), local(hour + 1, day=28), summary=name)
    await calendar.run_periodic("calendar.busy")
    view = (await get(calendar, "/wall/calendar?month=2026-10")).text
    cells = month_cells(view)
    assert cells[0] == "2026-09-28" and cells[-1] == "2026-11-01" and len(cells) % 7 == 0
    day = view[view.index('aria-label="2026-10-28"') :]
    day = day[: day.index("</button>")]
    assert re.findall(r'class="cal-ev[^"]*">([^<]+)<', day) == ["One", "Two", "Three"]
    assert "+1" in day
    assert 'hx-get="/wall/calendar?day=2026-10-28"' in view
    assert 'hx-get="/wall/calendar?month=2026-09"' in view  # ‹
    assert 'hx-get="/wall/calendar?month=2026-11"' in view  # ›
    assert "October 2026" in view and "May 2026" in view and "October 2027" in view  # picker


async def test_a_far_month_is_read_from_google_once_in_five_minutes(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(9, day=16).replace("2026-10-16", "2027-03-16"),
                        local(10, day=16).replace("2026-10-16", "2027-03-16"),
                        summary="Spring trip")  # fmt: skip
    await calendar.run_periodic("calendar.busy")
    before = fake_gcal.calls_to("list_events")
    view = (await get(calendar, "/wall/calendar?month=2027-03")).text
    assert "Spring trip" in view
    read = fake_gcal.calls_to("list_events")
    assert read > before
    await get(calendar, "/wall/calendar?day=2027-03-16")  # another range: read once more
    again = fake_gcal.calls_to("list_events")
    await get(calendar, "/wall/calendar?month=2027-03")
    assert fake_gcal.calls_to("list_events") == again  # held
    clock.advance(timedelta(minutes=6))
    await get(calendar, "/wall/calendar?month=2027-03")
    assert fake_gcal.calls_to("list_events") > again
    day = (await get(calendar, "/wall/calendar?day=2027-03-16")).text
    assert titles(day) == ["Spring trip"]


async def test_a_calendar_turned_off_is_left_out_and_offered_back(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    from tests.integration.test_wall_calendars import chips, two_calendars

    work = await two_calendars(calendar, fake_gcal)
    view = (await get(calendar, "/wall/calendar?day=2026-10-23")).text
    assert titles(view) == ["Dentist", "Standup", "Planning", "Review", "Retro"]
    assert len(chips(view)) == 2
    off = (await post(calendar, "/wall/calendar/calendar", day="2026-10-23", calendar=work)).text
    assert titles(off) == ["Dentist"]
    assert ("Erin's Work", True) in chips(off)  # still offered, to turn back on
    week = (await get(calendar, "/wall")).text
    assert "Standup" not in week  # the week ahead keeps the same choice
    back = (await post(calendar, "/wall/calendar/calendar", day="2026-10-23", calendar=work)).text
    assert len(titles(back)) == 5


async def test_today_and_the_week_ahead_open_it(calendar: Scenario) -> None:
    page = (await get(calendar, "/wall")).text
    today = page[page.index('class="wall-card wall-today"') :]
    assert 'hx-get="/wall/calendar"' in today[: today.index(">")]
    assert "click[!event.target.closest('.tl-block')]" in today[: today.index(">")]
    assert 'hx-get="/wall/calendar?day=2026-10-22"' in page
