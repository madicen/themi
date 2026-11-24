"""WL5a: the views that slide up when something on the wall is tapped: Event, Day, Weather
and Person. The scenario's day is Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.weather import FakeWeather
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import (
    calendar,
    frame,
    share,
    step,
    task,
    wall,
    with_wall,
    words,
)
from tests.integration.test_wall_taps import tap
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import local
from tests.scenarios.test_triage import ERIN
from themi import clock
from themi.core import keys

__all__ = ["calendar", "wall"]  # fixtures


async def get(s: Scenario, path: str) -> httpx.Response:
    async with web_client(s) as client:
        await frame(s, client)
        return await client.get(path, headers={"HX-Request": "true"})


async def dentist(s: Scenario, fake: FakeGcal) -> str:
    """Erin's dentist at 10, with a place; returns its Event view's address."""
    fake.add_event(ERIN, local(10), local(11), summary="Dentist", location="Smile Dental")
    await s.run_periodic("calendar.busy")
    page = (await get(s, "/wall")).text
    found = re.search(r'hx-get="(/wall/view/event\?[^"]+)"', page)
    assert found
    return found[1].replace("&amp;", "&")


# ----- Event ---------------------------------------------------------------------------


async def test_the_event_view_says_how_long_until_it_starts(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    view = await get(calendar, await dentist(calendar, fake_gcal))
    shown = words(view.text)
    assert "Erin&#39;s calendar Dentist Today, 10\u201311 am Starts in 1 hour" in shown
    assert "Where Smile Dental" in shown and "Send to Erin's phone" in shown
    assert 'data-close-after="120"' in view.text and "<html" not in view.text


async def test_while_it_happens_the_view_says_how_long_is_left(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    address = await dentist(calendar, fake_gcal)
    clock.advance(timedelta(hours=1, minutes=12))
    assert "Happening now · 48 minutes left" in words((await get(calendar, address)).text)
    clock.advance(timedelta(hours=1))
    assert "Finished" in words((await get(calendar, address)).text)


async def test_a_busy_event_shows_nothing_more(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    view = await get(calendar, await dentist(calendar, fake_gcal))
    assert "Busy" in view.text
    assert "Dentist" not in view.text and "Smile Dental" not in view.text


async def notes(s: Scenario, fake: FakeGcal, description: str) -> str:
    """Erin's dentist at 10 with notes; returns its Event view, as words."""
    fake.add_event(ERIN, local(10), local(11), summary="Dentist", description=description)
    await s.run_periodic("calendar.busy")
    found = re.search(r'hx-get="(/wall/view/event\?[^"]+)"', (await get(s, "/wall")).text)
    assert found
    return words((await get(s, found[1].replace("&amp;", "&"))).text)


async def test_the_event_view_shows_its_notes(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    """WL7: the event's notes, as plain text, a line each."""
    share(calendar)
    shown = await notes(calendar, fake_gcal, "Bring the <b>insurance card</b>.<br>Park out back.")
    assert "Notes Bring the insurance card. Park out back." in shown


async def test_long_notes_are_shortened_at_a_word(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    share(calendar)
    shown = await notes(calendar, fake_gcal, "Fill in the forms. " * 40)
    said = shown[shown.index("Notes ") + 6 :]
    assert said.startswith("Fill in the forms.") and "\u2026" in said
    assert len(said[: said.index("\u2026")]) <= 280 and "Fill in the forms. " * 20 not in said


async def test_a_busy_events_notes_stay_hidden(calendar: Scenario, fake_gcal: FakeGcal) -> None:
    shown = await notes(calendar, fake_gcal, "Bring the insurance card.")
    assert "insurance" not in shown and "Notes" not in shown


async def test_send_to_my_phone_goes_through_the_outbox(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    address = await dentist(calendar, fake_gcal)
    erin = calendar.member("Erin")
    async with web_client(calendar) as client:
        await frame(calendar, client)
        page = await client.get("/wall")
        csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', page.text)
        assert csrf
        sent = await client.post(
            address.replace("/wall/view/event?", "/wall/view/event/send?"),
            data={"to": str(erin.id)},
            headers={"X-CSRF-Token": csrf[1], "HX-Request": "true"},
        )
        forged = await client.post(
            address.replace("/wall/view/event?", "/wall/view/event/send?"),
            data={"to": str(erin.id)},
            headers={"X-CSRF-Token": "forged"},
        )
    assert "Sent to Erin&#39;s phone." in sent.text and forged.status_code == 403
    await calendar.app.outbox.flush()
    assert calendar.inbox("Erin")[-1] == (
        "From the wall: Dentist\nToday, 10\u201311 am\nAt Smile Dental"
    )
    assert calendar.inbox("Husband") == []


async def test_an_event_that_isnt_there_shows_nothing(calendar: Scenario) -> None:
    view = await get(calendar, "/wall/view/event?day=2026-10-21&m=1&c=x&e=y")
    assert view.status_code == 200 and view.text == ""


# ----- Day -----------------------------------------------------------------------------


async def test_the_day_view_shows_that_days_timeline_and_whats_due(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(15, day=23), local(16, day=23), summary="Tea Time!")
    await calendar.run_periodic("calendar.busy")
    await task(calendar, "Husband", "Take out waste", due=calendar.today() + timedelta(days=2))
    view = await get(calendar, "/wall/view/day/2026-10-23")
    shown = words(view.text)
    assert "In 2 days Friday, October 23" in shown
    assert "Tea Time! 3\u20134 pm" in shown
    assert "Due that day Take out waste Husband" in shown
    assert "Not in the forecast yet" in shown
    assert 'hx-get="/wall/view/day/2026-10-22"' in view.text  # the day before
    assert 'hx-get="/wall/view/day/2026-10-24"' in view.text
    assert "tl-now" not in view.text  # a day ahead has no now line


async def test_the_day_view_goes_from_today_to_two_weeks_out(calendar: Scenario) -> None:
    today = await get(calendar, "/wall/view/day/2026-10-21")
    assert "Today" in today.text and "The day before" not in today.text
    last = await get(calendar, "/wall/view/day/2026-11-03")
    assert "The day after" not in last.text
    assert (await get(calendar, "/wall/view/day/2026-11-04")).text == ""
    assert (await get(calendar, "/wall/view/day/2026-10-20")).text == ""


async def test_a_day_in_the_week_ahead_opens_its_view(calendar: Scenario) -> None:
    # F59f (idea #258) changed this: a day opens the calendar screen on it (was its Day view).
    page = (await get(calendar, "/wall")).text
    assert 'hx-get="/wall/calendar?day=2026-10-22" hx-target="#wall-view"' in page


# ----- Weather -------------------------------------------------------------------------


@pytest.fixture
async def rainy(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_weather: FakeWeather
) -> AsyncIterator[Scenario]:
    s = with_wall(family, fake_telegram, weather=fake_weather)
    await s.start()
    try:
        s.app.db.execute(
            "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?)",
            ("12 Main St", 37.70, -122.40, "2026-10-01T00:00:00+00:00"),
        )
        fake_weather.day(0, high=58, low=47)
        fake_weather.day(2, high=61, low=50, code=61)
        fake_weather.span(0, 14, 18, chance=80, rain=0.1, code=61)
        await s.app.services.get(keys.weather).refresh()
        yield s
    finally:
        await s.stop()


async def test_the_weather_view_is_the_rest_of_today_by_the_hour(rainy: Scenario) -> None:
    view = await get(rainy, "/wall/view/weather")
    hours = re.findall(r'<span class="hour-at">([^<]+)</span>', view.text)
    assert hours[0] == "9 am" and hours[-1] == "11 pm" and len(hours) == 15
    assert "High 58°, low 47°" in view.text
    two = view.text[view.text.index(">2 pm<") :]
    assert '<span class="hour-chance">80%</span>' in two[: two.index("</li>")]
    page = (await get(rainy, "/wall")).text
    assert 'hx-get="/wall/view/weather"' in page


async def test_a_day_ahead_has_its_weather_once_its_in_range(rainy: Scenario) -> None:
    view = await get(rainy, "/wall/view/day/2026-10-23")
    assert "High 61°, low 50°" in view.text


# ----- Person --------------------------------------------------------------------------


async def test_the_person_view_is_their_whole_day(wall: Scenario) -> None:
    step(wall, "Husband", "Morning", "Walk dog")
    step(wall, "Husband", "Afternoon", "Go for a run")
    step(wall, "Husband", "Evening", "Take meds")
    await task(wall, "Husband", "Vacuum upstairs")
    await task(wall, "Husband", "Later errand", due=wall.today() + timedelta(days=3))
    husband = wall.member("Husband")
    page = (await get(wall, "/wall")).text
    assert f'hx-get="/wall/view/person/{husband.id}"' in page
    shown = words((await get(wall, f"/wall/view/person/{husband.id}")).text)
    assert "Husband's day" in shown
    # WL9d: this part of the day's routine is open; the others fold and unfold in place
    assert "Morning routine 1 to do 🐕 Walk dog" in shown
    routines = wall.app.services.get(keys.routines)
    for name, step_words in (("Afternoon", "🏃 Go for a run"), ("Evening", "💊 Take meds")):
        assert f"{name} routine · 1 step" in shown and step_words not in shown
        found = routines.find(husband, name)
        assert found is not None
        opened = await get(wall, f"/wall/view/person/{husband.id}?open={found.id}")
        assert step_words in words(opened.text)
    assert "To-do 1 open Work through these at your own pace. 🧹 Vacuum upstairs" in shown
    assert "Later errand" not in shown
    assert (await get(wall, "/wall/view/person/999")).text == ""


async def test_a_step_ticked_in_the_person_view_refreshes_the_columns(wall: Scenario) -> None:
    item_id = step(wall, "Husband", "Morning", "Walk dog")
    husband = wall.member("Husband")
    routines = wall.app.services.get(keys.routines)
    day = routines.today(husband)
    async with web_client(wall) as client:
        await frame(wall, client)
        answer = await tap(
            wall, client, f"step-{item_id}-{day.isoformat()}", view=f"person/{husband.id}"
        )
    found = routines.item(item_id)
    assert found is not None and routines.ticked(found, day)
    assert answer.headers["HX-Trigger"] == "wall-refresh"
    assert "Husband's day" in answer.text and 'class="wall-item done"' in answer.text
