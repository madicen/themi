"""F55f (Michael's idea #239, 2026-11-20): the week ahead has a chip per calendar, and a tap
hides that calendar there ("so we can turn off my work calendar so it's not as spammy").

Erin shares her calendar's details; she reads her primary calendar and a Work one. The
clock starts Wednesday 21 October 2026, 9 am.
"""

from __future__ import annotations

import html
import re

import httpx

from tests.fakes.gcal_api import FakeGcal
from tests.fixtures.web import sign_in, web_client
from tests.integration.test_wall_screen import calendar, frame, screen, share, words
from tests.scenarios.harness import Scenario
from tests.scenarios.test_travel import local
from tests.scenarios.test_triage import ERIN
from themi import clock
from themi.core import keys
from themi_home.wall_calendars import WallCalendars

__all__ = ["calendar"]


async def two_calendars(s: Scenario, fake: FakeGcal) -> str:
    """Erin's primary calendar with a dentist on Friday, and her Work one with four
    meetings on Friday and one today at 3 pm. Returns Work's id."""
    share(s)
    work = fake.add_calendar(ERIN, "Work")
    account = int(s.app.db.scalar("SELECT id FROM linked_accounts WHERE member_id = ?",
                                  (s.member("Erin").id,)))  # fmt: skip
    calendars = s.app.services.maybe(keys.calendars)
    assert calendars is not None
    calendars.choose(account, [("primary", "primary"), (work, "Work")])
    fake.add_event(ERIN, local(8, day=23), local(9, day=23), summary="Dentist")
    for hour, title in ((9, "Standup"), (11, "Planning"), (13, "Review"), (15, "Retro")):
        fake.add_event(ERIN, local(hour, day=23), local(hour + 1, day=23), summary=title,
                       calendar=work)  # fmt: skip
    fake.add_event(ERIN, local(15), local(16), summary="Work today", calendar=work)
    await s.run_periodic("calendar.busy")
    return work


def week_of(page: str) -> str:
    start = page.index('class="wall-card wall-week"')
    return page[start : page.index("</section>", start)]


def chips(page: str) -> list[tuple[str, bool]]:
    """The week's calendar chips: (name, off)."""
    return [
        (html.unescape(name), "off" in classes)
        for classes, name in re.findall(
            r'<button type="button" class="wk-cal ([^"]*)"[^>]*>([^<]+)</button>', page
        )
    ]


async def tap_calendar(s: Scenario, client: httpx.AsyncClient, calendar_id: str) -> str:
    page = await client.get("/wall")
    csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', page.text)
    assert csrf
    response = await client.post(
        "/wall/week/calendar",
        data={"calendar": calendar_id},
        headers={"X-CSRF-Token": csrf[1], "HX-Request": "true"},
    )
    assert response.status_code == 200
    return response.text


async def test_the_week_has_a_chip_per_calendar(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    await two_calendars(calendar, fake_gcal)
    week = week_of(await screen(calendar))
    assert chips(week) == [("Erin", False), ("Erin's Work", False)]
    assert "Fri 23 Dentist Standup Planning +2 more" in words(week)


async def test_a_tap_hides_that_calendar_in_the_week_only(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    work = await two_calendars(calendar, fake_gcal)
    async with web_client(calendar) as client:
        await frame(calendar, client)
        week = await tap_calendar(calendar, client, work)
        assert chips(week) == [("Erin", False), ("Erin's Work", True)]
        assert "Fri 23 Dentist" in words(week)
        assert "Standup" not in week and "more" not in week
        page = (await client.get("/wall")).text  # still off after a reload
    assert chips(week_of(page)) == [("Erin", False), ("Erin's Work", True)]
    assert "Standup" not in week_of(page)
    timeline = page[page.index('id="wall-today"') : page.index('class="wall-card wall-week"')]
    assert "Work today" in timeline  # today's timeline is unchanged

    async with web_client(calendar) as client:
        await frame(calendar, client)
        week = await tap_calendar(calendar, client, work)  # and back on
    assert chips(week) == [("Erin", False), ("Erin's Work", False)]
    assert "Standup" in week


async def test_it_stays_off_the_next_day(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    work = await two_calendars(calendar, fake_gcal)
    WallCalendars(calendar.app.db).toggle(work)
    clock.advance(clock.now().replace(day=22) - clock.now())
    await calendar.run_periodic("calendar.busy")
    week = week_of(await screen(calendar))
    assert ("Erin's Work", True) in chips(week)
    assert "Standup" not in week


async def test_one_calendar_has_no_chips(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(8, day=23), local(9, day=23), summary="Dentist")
    await calendar.run_periodic("calendar.busy")
    week = week_of(await screen(calendar))
    assert "Dentist" in week and chips(week) == []


async def test_a_calendar_not_in_the_week_isnt_a_chip(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    await two_calendars(calendar, fake_gcal)
    fake_gcal.add_event(ERIN, local(8, day=23), local(9, day=23), summary="Dentist")
    for event in fake_gcal.events(ERIN, "Work"):  # Work's events all gone
        fake_gcal.calendar(ERIN, "Work").events.pop(event["id"])  # type: ignore[union-attr]
    await calendar.run_periodic("calendar.busy")
    assert chips(week_of(await screen(calendar))) == []


async def test_the_frames_page_has_the_same_checklist(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    work = await two_calendars(calendar, fake_gcal)
    async with web_client(calendar) as phone:
        csrf = await sign_in(calendar, phone, "Erin")
        frames = (await phone.get("/wall/frames")).text
        assert "Calendars in the week ahead" in frames
        boxes = re.findall(
            r'<input type="checkbox" name="shown" value="([^"]+)"( checked)?', frames
        )
        assert sorted(boxes) == sorted([("primary", " checked"), (work, " checked")])
        response = await phone.post(
            "/wall/frames/calendars", data={"csrf": csrf, "shown": "primary"}
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/wall/frames#calendars"
        frames = (await phone.get("/wall/frames")).text
    boxes = re.findall(r'<input type="checkbox" name="shown" value="([^"]+)"( checked)?', frames)
    assert sorted(boxes) == sorted([("primary", " checked"), (work, "")])
    assert WallCalendars(calendar.app.db).hidden() == {work}
    assert "Standup" not in week_of(await screen(calendar))
