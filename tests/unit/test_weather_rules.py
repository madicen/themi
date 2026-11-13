"""WX2: what's noteworthy about the day's weather, and the one line that says so."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.fakes.weather import FakeWeather
from themi import clock
from themi.standard.weather import WeatherSettings, noteworthy

TZ = ZoneInfo("America/Los_Angeles")
SEVEN = datetime(2026, 10, 21, 7, 0, tzinfo=TZ)
NINE_PM = datetime(2026, 10, 21, 21, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def frozen() -> object:
    clock.freeze(SEVEN - timedelta(hours=1))
    yield
    clock.unfreeze()


@pytest.fixture
def fake() -> FakeWeather:
    weather = FakeWeather()
    weather.day(-1, high=65, low=50)
    weather.day(0, high=65, low=50)
    return weather


async def line(
    fake: FakeWeather,
    start: datetime = SEVEN,
    settings: WeatherSettings | None = None,
) -> str | None:
    client = fake.client()
    forecast = await client.forecast(37.7, -122.4, "America/Los_Angeles")
    alerts = await client.alerts(37.7, -122.4)
    return noteworthy(forecast, start, NINE_PM, settings or WeatherSettings(), alerts)


async def test_a_fair_day_has_no_line(fake: FakeWeather) -> None:
    assert await line(fake) is None


async def test_rain_says_when_it_starts_and_the_high(fake: FakeWeather) -> None:
    fake.span(0, 14, 18, chance=80, rain=0.1, code=61)
    fake.day(0, high=58, low=48)
    assert await line(fake) == "Rain likely from about 2 pm, high 58°F."


async def test_a_small_chance_or_a_trace_of_rain_isnt_worth_a_line(fake: FakeWeather) -> None:
    fake.span(0, 14, 18, chance=50, rain=0.1)
    assert await line(fake) is None
    fake.span(0, 14, 18, chance=90, rain=0.01)  # 0.04 in all told
    assert await line(fake) is None


async def test_rain_already_falling_says_this_morning(fake: FakeWeather) -> None:
    fake.span(0, 5, 10, chance=90, rain=0.05)
    assert await line(fake) == "Rain likely this morning, high 65°F."


async def test_rain_all_day_says_most_of_the_day(fake: FakeWeather) -> None:
    fake.span(0, 6, 21, chance=90, rain=0.05)
    assert await line(fake) == "Rain most of the day, high 65°F."


async def test_rain_that_ended_before_the_morning_message_doesnt_count(
    fake: FakeWeather,
) -> None:
    fake.span(0, 3, 6, chance=90, rain=0.2)
    assert await line(fake) is None
    assert await line(fake, start=SEVEN - timedelta(hours=4)) is not None


async def test_rain_after_nine_pm_doesnt_count(fake: FakeWeather) -> None:
    fake.span(0, 21, 24, chance=90, rain=0.2)
    assert await line(fake) is None


async def test_freezing_rain(fake: FakeWeather) -> None:
    fake.span(0, 8, 10, code=66, chance=90, rain=0.1)
    assert await line(fake) == "Freezing rain likely from about 8 am."


async def test_thunderstorms(fake: FakeWeather) -> None:
    fake.span(0, 15, 17, code=95, chance=70, rain=0.3)
    assert await line(fake) == "Thunderstorms likely from about 3 pm."


async def test_snow_says_about_how_much(fake: FakeWeather) -> None:
    fake.span(0, 10, 14, snow=0.5, code=73, chance=90, rain=0.05)
    assert await line(fake) == "Snow from about 10 am, around 2 in."


async def test_a_dusting_of_snow_isnt_worth_a_line(fake: FakeWeather) -> None:
    fake.hour(0, 10, snow=0.2, code=71)
    assert await line(fake) is None


async def test_the_first_freeze_is_noted(fake: FakeWeather) -> None:
    fake.day(-1, high=50, low=36)
    fake.day(0, high=50, low=28)
    fake.hour(0, 23, temp=28)
    assert await line(fake) == "Below freezing tonight, low 28°F."


async def test_a_freeze_already_this_morning(fake: FakeWeather) -> None:
    fake.day(-1, high=50, low=36)
    fake.day(0, high=50, low=29)
    fake.hour(0, 5, temp=29)
    assert await line(fake) == "Below freezing this morning, low 29°F."


async def test_a_second_freezing_day_in_a_row_isnt(fake: FakeWeather) -> None:
    fake.day(-1, high=40, low=27)
    fake.day(0, high=40, low=25)
    assert await line(fake) is None


async def test_heat_and_bitter_cold(fake: FakeWeather) -> None:
    fake.day(-1, high=92, low=70)
    fake.day(0, high=97, low=72)
    assert await line(fake) == "Hot today, high 97°F."
    fake.day(-1, high=15, low=0)
    fake.day(0, high=14, low=4)
    assert await line(fake) == "Bitter cold today, low 4°F."


async def test_wind(fake: FakeWeather) -> None:
    fake.span(0, 13, 16, gust=45)
    assert await line(fake) == "Gusty, up to 45 mph this afternoon."


async def test_a_big_change_from_yesterday(fake: FakeWeather) -> None:
    fake.day(-1, high=60, low=45)
    fake.day(0, high=41, low=35)
    assert await line(fake) == "Much colder than yesterday, high 41°F."
    fake.day(0, high=78, low=50)
    assert await line(fake) == "Much warmer than yesterday, high 78°F."


async def test_the_first_rule_that_holds_gives_the_one_line(fake: FakeWeather) -> None:
    fake.span(0, 14, 18, chance=80, rain=0.1, gust=50)
    fake.day(0, high=40, low=35)  # rain, wind, and much colder than yesterday
    assert await line(fake) == "Rain likely from about 2 pm, high 40°F."
    fake.hour(0, 16, code=95)
    assert await line(fake) == "Thunderstorms likely from about 4 pm."
    fake.hour(0, 9, code=67)
    assert await line(fake) == "Freezing rain likely from about 9 am."


async def test_a_threshold_setting_changes_what_counts(fake: FakeWeather) -> None:
    fake.span(0, 14, 18, chance=45, rain=0.1)
    assert await line(fake) is None
    assert await line(fake, settings=WeatherSettings(rain_chance=40)) == (
        "Rain likely from about 2 pm, high 65°F."
    )
    fake.day(-1, high=88, low=68)
    fake.day(0, high=91, low=70)
    fake.span(0, 14, 18, chance=0, rain=0)
    assert await line(fake) is None
    assert await line(fake, settings=WeatherSettings(heat_f=90)) == "Hot today, high 91°F."


async def test_celsius_changes_only_the_words(fake: FakeWeather) -> None:
    c = WeatherSettings(units="C")
    fake.span(0, 12, 13, chance=80, rain=0.1)
    fake.day(0, high=58, low=48)
    assert await line(fake, settings=c) == "Rain likely from about noon, high 14°C."
    fake.span(0, 12, 13, chance=0, rain=0, gust=45)
    assert await line(fake, settings=c) == "Gusty, up to 72 km/h this afternoon."
    fake.span(0, 10, 14, snow=0.5, chance=90, rain=0.05)
    assert await line(fake, settings=c) == "Snow from about 10 am, around 5 cm."


# ----- WX3: NWS's alerts ------------------------------------------------------------------


async def test_a_warning_comes_first(fake: FakeWeather) -> None:
    fake.span(0, 14, 18, chance=80, rain=0.1, code=95)
    fake.alert("Winter Storm Warning", 18, None)
    assert await line(fake) == "Winter Storm Warning from 6 pm."


async def test_an_alert_already_in_force(fake: FakeWeather) -> None:
    fake.alert("Heat Advisory", 0, 20, day=0)
    assert await line(fake) == "Heat Advisory in effect today."


async def test_warnings_before_watches_before_advisories(fake: FakeWeather) -> None:
    fake.alert("Wind Advisory", 9, 18)
    fake.alert("Flood Watch", 10, 20)
    assert await line(fake) == "Flood Watch from 10 am."
    fake.alert("Flood Warning", 15, 23)
    assert await line(fake) == "Flood Warning from 3 pm."


async def test_alerts_outside_the_waking_day_dont_count(fake: FakeWeather) -> None:
    fake.alert("Frost Advisory", 1, 6)  # over before the morning message
    fake.alert("Winter Storm Watch", 22, None)  # after 9 pm
    fake.alert("Gale Warning", 2, 9, day=1)  # tomorrow
    assert await line(fake) is None


async def test_statements_tests_and_cancellations_are_skipped(fake: FakeWeather) -> None:
    fake.alert("Special Weather Statement", 9, 18)
    fake.alert("Hazardous Weather Outlook", 9, 18)
    fake.alert("Tornado Warning", 9, 18, status="Test")
    fake.alert("Flood Warning", 9, 18, message_type="Cancel")
    assert await line(fake) is None
