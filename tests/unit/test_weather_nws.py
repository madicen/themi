"""WX4: NWS's gridpoint forecast stands in when Open-Meteo can't be reached (US homes only).

Bug 2026-11-13: api.open-meteo.com was unreachable from home for hours while status sites
said it was up, and the forecast and the morning line stopped."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.fakes.modules import module_context
from tests.fakes.weather import GRID_URL, FakeWeather
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.connectors.weather import WeatherError, _parse_grid
from themi.core import keys
from themi.standard.weather import Weather, WeatherModule, WeatherSettings

TZ = ZoneInfo("America/Los_Angeles")
MORNING = datetime(2026, 10, 21, 6, 0, tzinfo=TZ)
TODAY = MORNING.date()


@pytest.fixture(autouse=True)
def frozen() -> object:
    clock.freeze(MORNING)
    yield
    clock.unfreeze()


def set_home(family: SeededFamily, lat: float = 37.70, lon: float = -122.40) -> None:
    family.db.execute(
        "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?)",
        ("12 Main St", lat, lon, "2026-10-01T00:00:00+00:00"),
    )


def load(family: SeededFamily, fake: FakeWeather) -> Weather:
    ctx = module_context(family.store)
    ctx.load(WeatherModule(fake.client(), WeatherSettings(alerts="off")))
    weather = ctx.services.get(keys.weather)
    assert isinstance(weather, Weather)
    return weather


def source(family: SeededFamily) -> str:
    return family.db.scalar("SELECT source FROM weather_forecasts WHERE day = ?", (str(TODAY),))


def series(uom: str, *values: tuple[str, float]) -> dict[str, object]:
    return {"uom": uom, "values": [{"validTime": t, "value": v} for t, v in values]}


# ----- reading the grid ----------------------------------------------------------------------


async def test_the_grid_reads_as_the_same_hours_and_days_as_open_meteo() -> None:
    fake = FakeWeather()
    fake.span(0, 14, 18, chance=80, rain=0.1, code=61, gust=30)
    fake.day(0, high=58, low=47)
    client = fake.client()
    grid = await client.nws_grid(37.70, -122.40)
    assert grid == GRID_URL
    nws = await client.nws_forecast(grid, TZ.key)
    meteo = await client.forecast(37.70, -122.40, TZ.key)
    for at in (datetime(2026, 10, 21, h, tzinfo=TZ) for h in (9, 14, 17, 18)):
        mine = next(h for h in nws.hours if h.at == at)
        theirs = next(h for h in meteo.hours if h.at == at)
        assert mine.at.tzinfo is not None and mine.at.utcoffset() == theirs.at.utcoffset()
        assert (mine.chance, mine.code) == (theirs.chance, theirs.code)
        for got, want in ((mine.rain, theirs.rain), (mine.temp, theirs.temp),
                          (mine.gust, theirs.gust), (mine.snow, theirs.snow)):  # fmt: skip
            assert got == pytest.approx(want)
    today = nws.day(TODAY)
    assert today is not None
    assert (today.high, today.low) == (pytest.approx(58), pytest.approx(47))
    assert (today.code, today.chance) == (61, 80)
    assert nws.day(TODAY - timedelta(days=1)) is None  # the grid has no yesterday


def test_a_sum_over_several_hours_is_shared_out_and_a_level_holds_for_each() -> None:
    grid = {
        "temperature": series("wmoUnit:degC", ("2026-10-21T20:00:00+00:00/PT3H", 10.0)),
        "quantitativePrecipitation": series("wmoUnit:mm", ("2026-10-21T20:00:00+00:00/PT3H", 7.62)),
        "probabilityOfPrecipitation": series(
            "wmoUnit:percent", ("2026-10-21T20:00:00+00:00/PT3H", 70)
        ),
        "windGust": series("wmoUnit:km_h-1", ("2026-10-21T20:00:00+00:00/PT3H", 64.37)),
    }
    forecast = _parse_grid(grid, TZ)
    assert [h.at.hour for h in forecast.hours] == [13, 14, 15]
    assert all(h.rain == pytest.approx(0.1) for h in forecast.hours)  # 0.3 in over 3 hours
    assert all(h.temp == pytest.approx(50) and h.chance == 70 for h in forecast.hours)
    assert all(h.gust == pytest.approx(40, abs=0.01) for h in forecast.hours)


def test_intervals_cross_midnight_and_the_clocks_going_back() -> None:
    grid = {
        "temperature": series(
            "wmoUnit:degF",
            ("2026-10-21T06:00:00+00:00/PT2H", 50),  # 11 pm on the 20th to 1 am on the 21st
            ("2026-11-01T07:00:00+00:00/PT4H", 40),  # midnight, 1 am twice, 2 am
        ),
    }
    hours = _parse_grid(grid, TZ).hours
    assert [(h.at.date(), h.at.hour) for h in hours[:2]] == [
        (date(2026, 10, 20), 23),
        (date(2026, 10, 21), 0),
    ]
    back = hours[2:]
    assert [h.at.hour for h in back] == [0, 1, 1, 2]
    assert len({h.at.astimezone(UTC) for h in back}) == 4


@pytest.mark.parametrize(
    ("entries", "sky", "code"),
    [
        ([{"coverage": "likely", "weather": "thunderstorms"}], 95, 95),
        (
            [{"coverage": "likely", "weather": "thunderstorms", "attributes": ["large_hail"]}],
            95,
            96,
        ),
        ([{"coverage": "chance", "weather": "thunderstorms"}], 95, 3),  # not likely: cloud
        ([{"coverage": "definite", "weather": "freezing_rain", "intensity": "heavy"}], 95, 67),
        (
            [
                {"coverage": "likely", "weather": "rain", "intensity": "light"},
                {"coverage": "likely", "weather": "snow", "intensity": "moderate"},
            ],
            95,
            73,
        ),
        ([{"coverage": None, "weather": None}], 10, 0),
        ([{"coverage": None, "weather": None}], 60, 2),
    ],
)
def test_nws_weather_words_become_the_wmo_codes_the_rules_read(
    entries: list[dict[str, object]], sky: int, code: int
) -> None:
    valid = "2026-10-21T20:00:00+00:00/PT1H"
    grid = {
        "temperature": series("wmoUnit:degF", (valid, 50)),
        "skyCover": series("wmoUnit:percent", (valid, sky)),
        "weather": {"values": [{"validTime": valid, "value": entries}]},
    }
    assert _parse_grid(grid, TZ).hours[0].code == code


async def test_a_grid_that_cant_be_read_says_so() -> None:
    fake = FakeWeather()
    fake.grid = {"temperature": series("wmoUnit:furlongs", ("2026-10-21T20:00:00+00:00/PT1H", 5))}
    with pytest.raises(WeatherError, match="NWS's forecast wasn't one Themi could read"):
        await fake.client().nws_forecast(GRID_URL, TZ.key)


async def test_only_nws_own_grid_addresses_are_fetched() -> None:
    with pytest.raises(WeatherError, match="no forecast grid"):
        await FakeWeather().client().nws_forecast("https://elsewhere.test/grid", TZ.key)


# ----- the fallback ------------------------------------------------------------------------


async def test_open_meteo_failing_brings_nws_forecast_and_the_same_line(
    family: SeededFamily, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeWeather()
    fake.span(0, 14, 18, chance=80, rain=0.1, code=61)
    fake.day(0, high=58, low=47)
    set_home(family)
    weather = load(family, fake)
    fake.fail("forecast", 503)
    caplog.set_level(logging.INFO, logger="themi.standard.weather")
    assert await weather.refresh() is True
    assert source(family) == "nws"
    assert weather.line(MORNING) == "Rain likely from about 2 pm, high 58°F."
    assert any("now comes from the National Weather Service" in r.getMessage()
               for r in caplog.records)  # fmt: skip
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_a_hung_open_meteo_brings_nws_too(family: SeededFamily) -> None:
    fake = FakeWeather()
    set_home(family)
    weather = load(family, fake)
    fake.hang("forecast")
    assert await weather.refresh() is True
    assert source(family) == "nws" and weather.latest() is not None


async def test_nws_stays_the_source_for_three_hours_then_open_meteo_is_tried(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    set_home(family)
    weather = load(family, fake)
    fake.fail("forecast", 503)
    await weather.refresh()
    for _ in range(2):
        clock.advance(timedelta(hours=1))
        assert await weather.refresh() is True
    assert fake.count("forecast") == 1  # not asked again while NWS stands in
    assert fake.count("grid") == 3
    clock.advance(timedelta(hours=1))
    assert await weather.refresh() is True
    assert fake.count("forecast") == 2 and source(family) == "open-meteo"


async def test_nws_failing_while_it_stands_in_goes_back_to_open_meteo(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    set_home(family)
    weather = load(family, fake)
    fake.fail("forecast", 503)
    await weather.refresh()
    clock.advance(timedelta(hours=1))
    fake.fail("grid", 500)
    assert await weather.refresh() is True
    assert source(family) == "open-meteo"


async def test_outside_the_us_there_is_no_stand_in(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.in_us = False
    set_home(family, 51.5, -0.12)
    weather = load(family, fake)
    fake.fail("forecast", 503, times=2)
    assert await weather.refresh() is False
    clock.advance(timedelta(hours=1))
    assert await weather.refresh() is False
    assert fake.count("grid") == 0 and fake.count("points") == 1  # asked once per address


async def test_yesterday_comes_from_the_forecast_kept(family: SeededFamily) -> None:
    fake = FakeWeather()
    fake.day(-1, high=50)
    fake.day(0, high=70, low=50)
    set_home(family)
    weather = load(family, fake)
    await weather.refresh()  # Open-Meteo, with yesterday in it
    clock.advance(timedelta(hours=1))
    fake.fail("forecast", 503)
    assert await weather.refresh() is True
    assert source(family) == "nws"
    forecast = weather.latest()
    assert forecast is not None
    yesterday = forecast.day(TODAY - timedelta(days=1))
    assert yesterday is not None and yesterday.high == 50
    assert weather.line(MORNING) == "Much warmer than yesterday, high 70°F."


async def test_with_nothing_kept_the_rules_that_need_yesterday_dont_fire(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    fake.day(-1, high=50)
    fake.day(0, high=70, low=50)
    set_home(family)
    weather = load(family, fake)
    fake.fail("forecast", 503)
    assert await weather.refresh() is True
    forecast = weather.latest()
    assert forecast is not None and forecast.day(TODAY - timedelta(days=1)) is None
    assert weather.line(MORNING) is None


async def test_a_home_asked_about_before_wx4_gets_its_grid_when_needed(
    family: SeededFamily,
) -> None:
    fake = FakeWeather()
    set_home(family)
    weather = load(family, fake)
    family.db.execute(
        "INSERT INTO weather_home (id, lat, lon, in_us) VALUES (1, 37.70, -122.40, 1)"
    )
    fake.fail("forecast", 503)
    assert await weather.refresh() is True
    assert family.db.scalar("SELECT grid_url FROM weather_home") == GRID_URL


# ----- Test ---------------------------------------------------------------------------------


async def test_test_says_when_nws_stood_in() -> None:
    fake = FakeWeather()
    module = WeatherModule(fake.client())
    fake.hang("forecast")
    assert await module.check() == (
        "Open-Meteo didn't answer (couldn't reach the weather service (ConnectTimeout)); "
        "the National Weather Service did, so forecasts carry on in the US."
    )
