"""MM5: a weather line in the morning message when the day's weather is worth knowing.

As in the morning message scenarios: Erin's morning message is set for 7:15 on Thursday 22
October, inside her quiet hours, so it goes at 8. The weather module is on (the
`fake_weather` fixture) and the home is set; nothing has been fetched before 7:15, so the
morning job asks for a forecast first."""

from __future__ import annotations

import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.weather import FakeWeather
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import linked
from tests.scenarios.test_morning_message import ALL_FOUR, MORNING, at, overnight, to
from themi.standard.day_summary import DaySummaryPreferences

__all__ = ["linked"]

RAIN = "Rain likely from about 2 pm, high 58°F."
NOTHING_ON = "Morning, Erin. Nothing on the calendar today."


@pytest.fixture
def weather(scenario: Scenario, fake_weather: FakeWeather) -> FakeWeather:
    scenario.app.db.execute(
        "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?)",
        ("12 Main St", 37.70, -122.40, "2026-10-01T00:00:00+00:00"),
    )
    fake_weather.day(-1, high=60, low=48)
    fake_weather.day(0, high=58, low=47)
    return fake_weather


def rain(fake: FakeWeather) -> None:
    fake.span(0, 14, 18, chance=80, rain=0.1, code=61)


async def test_a_rainy_day_gets_one_line_under_the_calendar(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    rain(weather)
    await overnight(scenario, linked)
    assert weather.count() == 1  # nothing fetched before: the morning job asked first
    assert await scenario.advance(minutes=45) == [f"{MORNING}\n{RAIN}"]
    assert scenario.last_buttons("Erin") == ALL_FOUR
    assert scenario.app.outbox.sent_today(scenario.member("Erin").id) == 1


async def test_a_fair_day_leaves_the_message_as_it_was(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    await overnight(scenario, linked)
    assert await scenario.advance(minutes=45) == [MORNING]


async def test_the_line_is_brought_up_to_date_while_the_message_waits(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    await overnight(scenario, linked)  # fair at 7:15
    to(at(7, 30))
    rain(weather)
    await scenario.run_periodic("weather.refresh")
    assert await scenario.advance(minutes=30) == [f"{MORNING}\n{RAIN}"]


async def test_a_weather_line_alone_sends_the_message(
    scenario: Scenario, weather: FakeWeather
) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="07:15"
    )
    to(at(7, 15))
    weather.alert("Winter Storm Warning", 18, None)  # from 6 pm Thursday
    await scenario.run_periodic("calendar.morning")
    sent = await scenario.advance(minutes=45)
    assert sent == [f"{NOTHING_ON}\nWinter Storm Warning from 6 pm."]


async def test_a_fair_empty_morning_still_sends_nothing(
    scenario: Scenario, weather: FakeWeather
) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, DaySummaryPreferences, morning_summary="07:15"
    )
    to(at(7, 15))
    await scenario.run_periodic("calendar.morning")
    assert await scenario.advance(minutes=45) == []
    assert weather.count() == 1


async def test_when_the_forecast_cant_be_had_the_message_goes_without_it(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    rain(weather)
    weather.fail("forecast", 503, times=10)
    weather.fail("grid", 503, times=10)  # WX4: NWS's stand-in can't be had either
    await overnight(scenario, linked)
    sent = await scenario.advance(minutes=45)
    assert sent == [MORNING]  # no line, and no word about the weather
    assert "weather" not in " ".join(scenario.inbox("Erin")).lower()


async def test_with_open_meteo_down_the_line_comes_from_nws(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    """WX4: Open-Meteo unreachable (as on 2026-11-13); in the US, NWS's forecast stands in
    and the line reads the same."""
    rain(weather)
    weather.hang("forecast", times=10)
    await overnight(scenario, linked)
    assert weather.count("grid") == 1
    assert await scenario.advance(minutes=45) == [f"{MORNING}\n{RAIN}"]
