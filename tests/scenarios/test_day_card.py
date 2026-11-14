"""DC3: the day card's data, gathered from a real morning: the calendar (theirs and the
blocks Themi holds for tasks), the weather and what waits in the trays. As in the morning
message scenarios: Thursday 22 October, Erin's morning message at 7:15."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.weather import FakeWeather
from tests.fixtures.web import csrf_of, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import linked
from tests.scenarios.test_morning_message import THU, at, overnight, to
from tests.scenarios.test_morning_weather import rain, weather
from themi.core import keys
from themi.standard.day_card import DayCard, Waiting
from themi.standard.drawings import DrawingsPreferences

__all__ = ["linked", "weather"]


def card(scenario: Scenario) -> DayCard:
    return scenario.app.services.get(keys.drawings).day_card


async def test_the_card_has_the_mornings_events_weather_and_trays(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    rain(weather)
    await overnight(scenario, linked)
    # The 8 am flush puts the night's messages in the trays just before the morning
    # message goes (DC5's scenarios draw it then); here, as it would.
    db = scenario.app.db
    db.execute("UPDATE outbox SET tray = 'email' WHERE kind = 'email' AND status = 'queued'")
    db.execute("UPDATE outbox SET tray = 'other' WHERE kind = 'meal' AND status = 'queued'")
    data = card(scenario).data(scenario.member("Erin"), THU)
    assert data.start.hour == 7 and data.start.minute == 15
    assert [(e.title, e.kind, e.start.hour) for e in data.events] == [
        ("Dentist", "event", 10),
        ("Call the vet", "held", 14),  # the block Themi holds for the task, drawn quieter
    ]
    assert data.waiting == Waiting(tasks=2, email=1, other=1)
    assert data.weather is not None
    assert data.weather.line == "Rain likely from about 2 pm, high 58°F."
    assert not data.weather.alert
    assert data.weather.high == 58
    assert any(h.chance == 80 for h in data.weather.hours)


async def test_the_card_draws_and_says_so_in_words(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    rain(weather)
    await overnight(scenario, linked)
    erin = scenario.member("Erin")
    svg = card(scenario).svg(erin, THU)
    assert (
        ">Thursday<" in svg and ">22 October<" in svg and "Dentist" in svg and "Call the vet" in svg
    )
    png = await card(scenario).png(erin, THU)
    assert png is not None and png[:4] == b"\x89PNG"


async def test_an_alert_is_marked_as_one(scenario: Scenario, weather: FakeWeather) -> None:
    to(at(6))
    weather.alert("Winter Storm Warning", 18, None)
    await scenario.run_periodic("weather.refresh")
    data = card(scenario).data(scenario.member("Erin"), THU)
    assert data.weather is not None and data.weather.alert
    assert data.weather.line == "Winter Storm Warning from 6 pm."


async def test_without_the_weather_module_there_is_no_weather(scenario: Scenario) -> None:
    data = card(scenario).data(scenario.member("Erin"), THU)
    assert data.weather is None
    assert data.events == ()


async def test_an_event_with_a_place_gets_a_lead_in_from_a_known_place(
    scenario: Scenario, linked: FakeGcal, fake_travel: object
) -> None:
    erin = scenario.member("Erin")
    db = scenario.app.db
    db.execute(
        "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?)",
        ("12 Main St", 37.70, -122.40, "2026-10-01T00:00:00+00:00"),
    )
    db.execute(
        "INSERT INTO geocodes (query_key, lat, lon, found, fetched_at) VALUES (?, ?, ?, 1, ?)",
        ("smile dental", 37.80, -122.27, "2026-10-01T00:00:00+00:00"),
    )
    from tests.scenarios.test_triage import ERIN

    linked.add_event(
        ERIN, at(14).isoformat(), at(15).isoformat(), summary="Dentist", location="Smile Dental"
    )
    await scenario.run_periodic("calendar.busy")
    data = card(scenario).data(erin, THU)
    lead = [e for e in data.events if e.kind == "travel"]
    assert len(lead) == 1
    assert lead[0].end == at(14)
    assert lead[0].title.startswith("Leave around 1:")


async def test_the_settings_page_saves_the_picture_settings(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert 'name="picture_morning" checked' in page  # on for everyone
    erin = scenario.member("Erin")
    form = {
        "csrf": csrf_of(page),
        "morning_summary": "07:15",
        "picture_counts": "numbers",
        "picture_theme": "dark",
    }  # picture_morning left unticked
    assert (await site.post("/settings", data=form)).status_code in (200, 303)
    prefs = scenario.app.store.preferences(erin.id, DrawingsPreferences)
    assert (prefs.picture_morning, prefs.picture_counts, prefs.picture_theme) == (
        False,
        "numbers",
        "dark",
    )


@pytest.mark.parametrize(("field", "value"), [("picture_counts", "red"), ("picture_theme", "x")])
def test_a_picture_setting_outside_its_choices_is_refused(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        DrawingsPreferences.model_validate({field: value})
