"""WX1: the weather module, Open-Meteo's forecast, and the stored forecast at home."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.fakes.modules import module_context
from tests.fakes.weather import FakeWeather
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.connectors.weather import Forecast
from themi.core import keys
from themi.modules.base import ModuleSetup
from themi.modules.settings import SettingsProblem, read_settings
from themi.standard.weather import Weather, WeatherModule, WeatherSettings
from themi.storage.migrations import current_version

TZ = ZoneInfo("America/Los_Angeles")
MORNING = datetime(2026, 10, 21, 6, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def frozen() -> object:
    clock.freeze(MORNING)
    yield
    clock.unfreeze()


def set_home(family: SeededFamily, lat: float = 37.70, lon: float = -122.40) -> None:
    family.db.execute(
        "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET lat = excluded.lat, lon = excluded.lon",
        ("12 Main St", lat, lon, "2026-10-01T00:00:00+00:00"),
    )


def load(family: SeededFamily, fake: FakeWeather, settings: WeatherSettings | None = None):
    ctx = module_context(family.store)
    ctx.load(WeatherModule(fake.client(), settings))
    weather = ctx.services.get(keys.weather)
    assert isinstance(weather, Weather)
    return ctx, weather


# ----- the client ------------------------------------------------------------------------


async def test_the_forecast_is_read_hour_by_hour_for_yesterday_today_and_tomorrow() -> None:
    fake = FakeWeather()
    fake.span(0, 14, 16, chance=80, rain=0.1, code=61, temp=55)
    fake.day(0, high=58, low=45)
    forecast = await fake.client().forecast(37.7, -122.4, "America/Los_Angeles")
    today = date(2026, 10, 21)
    assert len(forecast.hours) == 72
    two_pm = next(h for h in forecast.hours if h.at == datetime(2026, 10, 21, 14, tzinfo=TZ))
    assert (two_pm.chance, two_pm.rain, two_pm.code, two_pm.temp) == (80, 0.1, 61, 55)
    assert (
        next(h for h in forecast.hours if h.at == datetime(2026, 10, 21, 16, tzinfo=TZ)).chance == 0
    )
    assert forecast.day(today) is not None and forecast.day(today).high == 58  # type: ignore[union-attr]
    assert forecast.day(today - timedelta(days=1)) is not None
    assert len(forecast.hours_on(today)) == 24
    params = fake.calls[0][1]
    assert params["latitude"] == "37.7000" and params["timezone"] == "America/Los_Angeles"
    assert params["forecast_days"] == "2" and params["wind_speed_unit"] == "mph"


async def test_a_forecast_survives_being_stored() -> None:
    fake = FakeWeather()
    fake.hour(0, 9, snow=0.4, code=73)
    forecast = await fake.client().forecast(37.7, -122.4, "America/Los_Angeles")
    assert Forecast.from_json(forecast.to_json()) == forecast


# ----- the settings ----------------------------------------------------------------------


def test_the_settings_default_to_us_units_and_the_plans_thresholds() -> None:
    s = read_settings(WeatherSettings, {}, {}, "weather")
    assert (s.units, s.alerts) == ("F", "auto")
    assert (s.rain_chance, s.rain_in, s.snow_in) == (60, 0.05, 0.5)
    assert (s.heat_f, s.cold_f, s.gust_mph, s.change_f) == (95, 10, 40, 15)


def test_each_threshold_can_be_set() -> None:
    env = {"WEATHER_UNITS": "c", "WEATHER_RAIN_CHANCE": "40", "WEATHER_HEAT_F": "90"}
    s = read_settings(WeatherSettings, env, {"gust_mph": 30}, "weather")
    assert (s.units, s.rain_chance, s.heat_f, s.gust_mph) == ("C", 40, 90, 30)


@pytest.mark.parametrize(
    ("env", "problem"),
    [
        ({"WEATHER_UNITS": "K"}, "WEATHER_UNITS is F or C"),
        ({"WEATHER_ALERTS": "maybe"}, "WEATHER_ALERTS is auto, on or off"),
        ({"WEATHER_RAIN_CHANCE": "120"}, "WEATHER_RAIN_CHANCE is a percentage, 1 to 100"),
        ({"WEATHER_SNOW_IN": "0"}, "the weather's amounts are more than 0"),
    ],
)
def test_settings_that_make_no_sense_are_refused(env: dict[str, str], problem: str) -> None:
    with pytest.raises(SettingsProblem) as caught:
        read_settings(WeatherSettings, env, {}, "weather")
    assert caught.value.problems == [problem]


# ----- the module ------------------------------------------------------------------------


def test_the_module_brings_its_own_track_and_an_hourly_refresh(family: SeededFamily) -> None:
    ctx, _ = load(family, FakeWeather())
    assert current_version(family.db, "weather") == 2  # WX3: whether home is in the US
    assert [(j.name, j.every) for j in ctx.jobs] == [("weather.refresh", timedelta(hours=1))]


def test_the_module_is_built_from_its_settings() -> None:
    setup = ModuleSetup.__new__(ModuleSetup)
    setup.read = lambda model, module="": WeatherSettings(units="C")  # type: ignore[method-assign]
    module = WeatherModule.build(setup)
    assert isinstance(module, WeatherModule) and module.weather_settings.units == "C"


async def test_test_fetches_one_forecast_and_says_what_went_wrong() -> None:
    fake = FakeWeather()
    module = WeatherModule(fake.client())
    assert await module.check() is None
    fake.fail("forecast", 503)
    assert await module.check() == (
        "The weather service didn't answer: the weather service said 503"
    )


# ----- the stored forecast ---------------------------------------------------------------


async def test_without_a_home_address_nothing_is_fetched(family: SeededFamily) -> None:
    fake = FakeWeather()
    _, weather = load(family, fake)
    assert await weather.refresh() is False
    assert fake.calls == [] and weather.latest() is None


async def test_a_refresh_keeps_todays_forecast(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.span(0, 14, 16, chance=80, rain=0.1)
    set_home(family)
    _, weather = load(family, fake)
    assert await weather.refresh() is True
    forecast = weather.latest()
    assert forecast is not None
    assert max(h.chance for h in forecast.hours_on(date(2026, 10, 21))) == 80
    rows = family.db.query("SELECT day FROM weather_forecasts")
    assert [r["day"] for r in rows] == ["2026-10-21"]


async def test_each_refresh_replaces_the_days_row_and_older_rows_are_pruned(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    set_home(family)
    _, weather = load(family, fake)
    for _ in range(3):
        await weather.refresh()
        clock.advance(timedelta(days=1))
    await weather.refresh()
    clock.advance(timedelta(hours=1))
    await weather.refresh()
    days = [r["day"] for r in family.db.query("SELECT day FROM weather_forecasts ORDER BY day")]
    assert days == ["2026-10-23", "2026-10-24"]  # today, and yesterday kept


async def test_a_forecast_older_than_six_hours_isnt_used(family: SeededFamily) -> None:
    fake = FakeWeather()
    set_home(family)
    _, weather = load(family, fake)
    await weather.refresh()
    clock.advance(timedelta(hours=6))
    assert weather.latest() is not None
    clock.advance(timedelta(minutes=1))
    assert weather.latest() is None


async def test_a_failed_refresh_keeps_the_last_good_forecast_and_is_logged_once(
    family: SeededFamily, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeWeather()
    set_home(family)
    _, weather = load(family, fake)
    await weather.refresh()
    good = weather.latest()
    fake.fail("forecast", 500, times=3)
    caplog.set_level(logging.INFO, logger="themi.standard.weather")
    for _ in range(3):
        clock.advance(timedelta(hours=1))
        assert await weather.refresh() is False
    assert weather.latest() == good  # fetched three hours ago: still fresh
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "the weather service said 500" in warnings[0].getMessage()
    clock.advance(timedelta(hours=1))
    assert await weather.refresh() is True
    assert "the forecast is back" in caplog.records[-1].getMessage()


async def test_a_moved_home_is_asked_about_on_the_next_refresh(family: SeededFamily) -> None:
    fake = FakeWeather()
    set_home(family)
    _, weather = load(family, fake)
    await weather.refresh()
    set_home(family, 45.52, -122.68)
    await weather.refresh()
    forecasts = [params for kind, params in fake.calls if kind == "forecast"]
    assert forecasts[-1]["latitude"] == "45.5200"


async def test_ensure_today_fetches_only_when_theres_no_usable_forecast(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    set_home(family)
    _, weather = load(family, fake)
    await weather.ensure_today()
    await weather.ensure_today()
    assert fake.count() == 1
    clock.advance(timedelta(hours=7))
    await weather.ensure_today()
    assert fake.count() == 2


# ----- WX2: the line, from the stored forecast -------------------------------------------


async def test_the_line_comes_from_the_stored_forecast(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.span(0, 14, 18, chance=80, rain=0.1)
    fake.day(-1, high=58, low=48)
    fake.day(0, high=58, low=48)
    set_home(family)
    _, weather = load(family, fake)
    seven = MORNING.replace(hour=7)
    assert weather.line(seven) is None  # nothing fetched yet
    await weather.refresh()
    assert weather.line(seven) == "Rain likely from about 2 pm, high 58°F."
    assert weather.line(MORNING.replace(hour=21)) is None  # the waking day is over
    clock.advance(timedelta(hours=7))
    assert weather.line(seven) is None  # too old to go on


async def test_the_line_uses_the_settings(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.span(0, 14, 18, chance=45, rain=0.1)
    set_home(family)
    _, weather = load(family, fake, WeatherSettings(rain_chance=40, units="C"))
    await weather.refresh()
    assert weather.line(MORNING.replace(hour=7)) == "Rain likely from about 2 pm, high 18°C."


# ----- WX3: NWS's alerts in the US -------------------------------------------------------


async def test_alerts_are_kept_with_the_forecast_and_us_is_asked_once(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    fake.alert("Winter Storm Warning", 18, None)
    set_home(family)
    _, weather = load(family, fake)
    await weather.refresh()
    await weather.refresh()
    assert (fake.count("points"), fake.count("alerts")) == (1, 2)
    assert fake.calls[-1][1] == {"point": "37.7000,-122.4000"}
    assert [a.event for a in weather.latest_alerts()] == ["Winter Storm Warning"]
    assert weather.line(MORNING.replace(hour=7)) == "Winter Storm Warning from 6 pm."


async def test_outside_the_us_alerts_are_never_asked_for(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.in_us = False
    set_home(family, 51.5, -0.12)
    _, weather = load(family, fake)
    await weather.refresh()
    await weather.refresh()
    assert (fake.count("points"), fake.count("alerts")) == (1, 0)
    set_home(family, 37.7, -122.4)  # moved: asked about again
    fake.in_us = True
    await weather.refresh()
    assert (fake.count("points"), fake.count("alerts")) == (2, 1)


async def test_alerts_on_skips_the_us_check_and_off_asks_nothing(family: SeededFamily) -> None:
    fake = FakeWeather()
    set_home(family)
    _, weather = load(family, fake, WeatherSettings(alerts="on"))
    await weather.refresh()
    assert (fake.count("points"), fake.count("alerts")) == (0, 1)
    off = FakeWeather()
    _, weather = load(family, off, WeatherSettings(alerts="off"))
    await weather.refresh()
    assert (off.count("points"), off.count("alerts"), off.count()) == (0, 0, 1)


async def test_nws_down_leaves_the_forecasts_own_rules(
    family: SeededFamily, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeWeather()
    fake.span(0, 14, 18, chance=80, rain=0.1)
    fake.alert("Flood Watch", 12, 20)
    fake.fail("alerts", 503, times=2)
    set_home(family)
    _, weather = load(family, fake)
    caplog.set_level(logging.WARNING, logger="themi.standard.weather")
    assert await weather.refresh() is True
    assert await weather.refresh() is True
    assert weather.latest_alerts() == []
    assert weather.line(MORNING.replace(hour=7)) == "Rain likely from about 2 pm, high 65°F."
    assert len([r for r in caplog.records if "warnings didn't come" in r.getMessage()]) == 1
    await weather.refresh()
    assert weather.line(MORNING.replace(hour=7)) == "Flood Watch from noon."


async def test_the_us_check_failing_is_tried_again_next_time(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.fail("points", 500)
    set_home(family)
    _, weather = load(family, fake)
    await weather.refresh()
    assert family.db.one("SELECT 1 FROM weather_home") is None
    await weather.refresh()
    assert (fake.count("points"), fake.count("alerts")) == (2, 1)
