"""The weather at home (WX1-WX3; the Themi Weather Module Plan).

The `weather` module keeps today's forecast for the family's home (K4's `family_home`) in
one stored row, refreshed each hour, so the morning message reads it without a network
call. One forecast for the household: the same line for everyone.

- Open-Meteo's forecast (`themi.connectors.weather`): no key, no account. In the US, the
  National Weather Service's warnings, watches and advisories too (WX3; `WEATHER_ALERTS`:
  `auto` asks NWS once per home address whether it's in the US). NWS failing alone leaves
  the forecast's own rules running.
- WX4: in the US, when Open-Meteo can't be reached, NWS's gridpoint forecast stands in,
  and stays the source for `NWS_FOR` before Open-Meteo is tried again. NWS has no
  yesterday, so yesterday's high and low come from the forecasts kept.
- A forecast older than `FRESH` isn't used. A refresh that fails keeps the last good one,
  and is logged once for the outage. Nothing about it ever reaches the family.
- Off until it's turned on; without a home address it does nothing (the Modules page says
  to set one on the Family page).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import field_validator

from themi import clock
from themi.connectors.weather import (
    ALERT_KINDS,
    Alert,
    Forecast,
    WeatherClient,
    WeatherError,
    WeatherSource,
)
from themi.localtime import to_utc_iso
from themi.modules import Module
from themi.modules.base import AccountNeed, ModuleSetup
from themi.modules.settings import ModuleSettings, env_field

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.modules.context import ModuleContext

log = logging.getLogger(__name__)

NAME = "weather"
REFRESH_EVERY = timedelta(hours=1)
FRESH = timedelta(hours=6)  # an older forecast isn't used
ENSURE_TIMEOUT = 10.0  # seconds the morning message waits for a first forecast
TEST_PLACE = (47.6062, -122.3321, "America/Los_Angeles")  # Test asks about Seattle
NWS_FOR = timedelta(hours=3)  # WX4: after an Open-Meteo failure, NWS is the source this long
TEST_OPEN_METEO_WITHIN = 10.0  # WX4: seconds Test gives Open-Meteo, leaving NWS the rest
OPEN_METEO = "open-meteo"
NWS = "nws"
SOURCE_NAMES = {OPEN_METEO: "Open-Meteo", NWS: "the National Weather Service"}


class WeatherSettings(ModuleSettings):
    units: str = env_field(
        "WEATHER_UNITS", "F", choices=("F", "C"), label="Units (F: °F, inches, mph)"
    )
    alerts: str = env_field(
        "WEATHER_ALERTS",
        "auto",
        choices=("auto", "on", "off"),
        label="Weather warnings from the US National Weather Service",
        advanced=True,
    )
    # The thresholds (the plan's "What counts as noteworthy"), in °F, inches and mph.
    rain_chance: int = env_field("WEATHER_RAIN_CHANCE", 60, label="Rain: chance (%)")
    rain_in: float = env_field("WEATHER_RAIN_IN", 0.05, label="Rain: at least (inches)")
    snow_in: float = env_field("WEATHER_SNOW_IN", 0.5, label="Snow: at least (inches)")
    heat_f: float = env_field("WEATHER_HEAT_F", 95, label="Hot: a high of at least (°F)")
    cold_f: float = env_field("WEATHER_COLD_F", 10, label="Bitter cold: a low of at most (°F)")
    gust_mph: float = env_field("WEATHER_GUST_MPH", 40, label="Wind: gusts of at least (mph)")
    change_f: float = env_field(
        "WEATHER_CHANGE_F", 15, label="A big change: the high moves by at least (°F)"
    )

    @field_validator("units", mode="before")
    @classmethod
    def _units(cls, value: Any) -> str:
        units = str(value).strip().upper().removeprefix("°")
        if units not in ("F", "C"):
            raise ValueError("WEATHER_UNITS is F or C")
        return units

    @field_validator("alerts", mode="before")
    @classmethod
    def _alerts(cls, value: Any) -> str:
        alerts = str(value).strip().lower()
        if alerts not in ("auto", "on", "off"):
            raise ValueError("WEATHER_ALERTS is auto, on or off")
        return alerts

    @field_validator("rain_chance")
    @classmethod
    def _chance(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("WEATHER_RAIN_CHANCE is a percentage, 1 to 100")
        return value

    @field_validator("rain_in", "snow_in", "gust_mph", "change_f")
    @classmethod
    def _above_zero(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("the weather's amounts are more than 0")
        return value


class Weather:
    def __init__(
        self, services: Services, source: WeatherSource, settings: WeatherSettings
    ) -> None:
        self.services = services
        self.source = source
        self.settings = settings
        self.db = services.store.db
        self._down = False  # a failure is logged once, until a refresh works again
        self._alerts_down = False
        self._source = OPEN_METEO  # WX4: which service the last forecast came from

    def install(self) -> None:
        pass

    def home(self) -> tuple[float, float] | None:
        row = self.db.one("SELECT lat, lon FROM family_home WHERE id = 1")
        return (row["lat"], row["lon"]) if row else None

    def tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def today(self) -> date:
        return clock.now().astimezone(self.tz()).date()

    async def refresh(self) -> bool:
        """Fetch today's forecast for home and keep it. False when there's no home, or the
        weather service didn't answer (the last good forecast stays)."""
        home = self.home()
        if home is None:
            return False
        tz = self.tz()
        try:
            forecast, source = await self._forecast(home[0], home[1], tz)
        except WeatherError as exc:
            if not self._down:
                log.warning("weather: the forecast didn't come: %s", exc)
            self._down = True
            return False
        if self._down:
            log.info("weather: the forecast is back")
        self._down = False
        if source != self._source:
            log.info("weather: the forecast now comes from %s", SOURCE_NAMES[source])
        self._source = source
        alerts = await self._alerts(*home)
        today = self.today()
        if source == NWS:
            forecast = self._with_kept_days(forecast, today)
        self.db.execute(
            "INSERT INTO weather_forecasts (day, fetched_at, forecast, alerts, source) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET fetched_at = excluded.fetched_at, "
            "forecast = excluded.forecast, alerts = excluded.alerts, "
            "source = excluded.source",
            (
                today.isoformat(),
                to_utc_iso(clock.now()),
                json.dumps(forecast.to_json()),
                json.dumps([a.to_json() for a in alerts]),
                source,
            ),
        )
        self.db.execute(
            "DELETE FROM weather_forecasts WHERE day < ?",
            ((today - timedelta(days=1)).isoformat(),),
        )
        return True

    async def _forecast(self, lat: float, lon: float, tz: ZoneInfo) -> tuple[Forecast, str]:
        """WX4: Open-Meteo's forecast, or NWS's when Open-Meteo can't be reached and home is
        in the US. After an Open-Meteo failure NWS goes first for `NWS_FOR`; whichever goes
        first, the other is tried when it fails. The last failure is what's raised."""
        sticky = self._nws_until() is not None
        order = (NWS, OPEN_METEO) if sticky else (OPEN_METEO, NWS)
        failure: WeatherError | None = None
        for source in order:
            try:
                if source == OPEN_METEO:
                    return await self.source.forecast(lat, lon, tz.key), OPEN_METEO
                grid = await self._grid(lat, lon)
                if grid is None:
                    continue  # outside the US: no stand-in
                forecast = await self.source.nws_forecast(grid, tz.key)
            except WeatherError as exc:
                failure = exc
                continue
            if not sticky:
                self._hold_nws()
            return forecast, NWS
        assert failure is not None  # Open-Meteo is always tried
        raise failure

    def _nws_until(self) -> datetime | None:
        row = self.db.one("SELECT nws_until FROM weather_home WHERE id = 1")
        if row is None or not row["nws_until"]:
            return None
        until = datetime.fromisoformat(row["nws_until"])
        return until if clock.now() < until else None

    def _hold_nws(self) -> None:
        self.db.execute(
            "UPDATE weather_home SET nws_until = ? WHERE id = 1",
            (to_utc_iso(clock.now() + NWS_FOR),),
        )

    async def _grid(self, lat: float, lon: float) -> str | None:
        """NWS's forecast grid for home, asked once per address; None outside the US."""
        row = await self._home_row(lat, lon)
        if not row["in_us"]:
            return None
        if row["grid_url"]:
            return str(row["grid_url"])
        grid = await self.source.nws_grid(lat, lon)  # a home asked about before WX4
        if grid is None:
            return None
        self.db.execute("UPDATE weather_home SET grid_url = ? WHERE id = 1", (grid or None,))
        return grid

    def _with_kept_days(self, forecast: Forecast, today: date) -> Forecast:
        """NWS's grid has no yesterday (and late in the day it may have dropped today's high):
        those days come from the forecasts kept, the newest first."""
        days = {d.day: d for d in forecast.days}
        missing = [d for d in (today - timedelta(days=1), today) if d not in days]
        if not missing:
            return forecast
        rows = self.db.query("SELECT forecast FROM weather_forecasts ORDER BY fetched_at DESC")
        for row in rows:
            kept = Forecast.from_json(json.loads(row["forecast"]))
            for day in list(missing):
                found = kept.day(day)
                if found is not None:
                    days[day] = found
                    missing.remove(day)
        return Forecast(forecast.hours, tuple(days[d] for d in sorted(days)))

    async def _alerts(self, lat: float, lon: float) -> list[Alert]:
        """NWS's alerts at home, when they're on (WX3); none when NWS doesn't answer."""
        mode = self.settings.alerts
        if mode == "off":
            return []
        try:
            if mode == "auto" and not await self._in_us(lat, lon):
                return []
            alerts = await self.source.alerts(lat, lon)
        except WeatherError as exc:
            if not self._alerts_down:
                log.warning("weather: the weather warnings didn't come: %s", exc)
            self._alerts_down = True
            return []
        self._alerts_down = False
        return alerts

    async def _in_us(self, lat: float, lon: float) -> bool:
        return bool((await self._home_row(lat, lon))["in_us"])

    async def _home_row(self, lat: float, lon: float) -> dict[str, Any]:
        """The `weather_home` row for this place: NWS's `points` is asked once per address
        (a moved home is asked again), keeping whether it's in the US and its grid (WX4)."""
        row = self.db.one("SELECT * FROM weather_home WHERE id = 1")
        if row is not None and (row["lat"], row["lon"]) == (lat, lon):
            return row
        grid = await self.source.nws_grid(lat, lon)
        in_us = grid is not None
        self.db.execute(
            "INSERT INTO weather_home (id, lat, lon, in_us, grid_url, nws_until) "
            "VALUES (1, ?, ?, ?, ?, NULL) "
            "ON CONFLICT(id) DO UPDATE SET lat = excluded.lat, lon = excluded.lon, "
            "in_us = excluded.in_us, grid_url = excluded.grid_url, nws_until = NULL",
            (lat, lon, int(in_us), grid or None),
        )
        if not in_us:
            log.info("weather: home is outside the US, so there are no NWS warnings")
        return {"lat": lat, "lon": lon, "in_us": int(in_us), "grid_url": grid or None}

    async def ensure_today(self, timeout: float = ENSURE_TIMEOUT) -> None:
        """A refresh when there's no usable forecast (Themi just started), waiting at most
        `timeout` seconds for it."""
        if self.latest() is not None:
            return
        try:
            await asyncio.wait_for(self.refresh(), timeout)
        except TimeoutError:
            log.warning("weather: no forecast within %s seconds", timeout)

    def _latest_row(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM weather_forecasts ORDER BY fetched_at DESC LIMIT 1")

    def _fresh_row(self) -> dict[str, Any] | None:
        row = self._latest_row()
        if row is None or clock.now() - datetime.fromisoformat(row["fetched_at"]) > FRESH:
            return None
        return row

    def latest(self) -> Forecast | None:
        """The newest forecast fetched within `FRESH`, or None."""
        row = self._fresh_row()
        return Forecast.from_json(json.loads(row["forecast"])) if row else None

    def latest_alerts(self) -> list[Alert]:
        """NWS's alerts as of the newest fresh forecast (WX3)."""
        row = self._fresh_row()
        return [Alert.from_json(a) for a in json.loads(row["alerts"])] if row else []

    def line(self, start: datetime) -> str | None:
        """The weather line for the waking day from `start` (the morning message's time)
        to 9 pm, or None: a fair day, or no forecast to go on."""
        forecast = self.latest()
        if forecast is None:
            return None
        local = start.astimezone(self.tz())
        end = datetime(local.year, local.month, local.day, DAY_ENDS.hour, tzinfo=self.tz())
        if local >= end:
            return None
        return noteworthy(forecast, local, end, self.settings, self.latest_alerts())

    def alert_in_force(self, start: datetime) -> bool:
        """DC3: whether the line for the day from `start` is an NWS alert (the day card
        shows it as a warning, not a note)."""
        if self.latest() is None:
            return False
        local = start.astimezone(self.tz())
        end = datetime(local.year, local.month, local.day, DAY_ENDS.hour, tzinfo=self.tz())
        return local < end and _alert_line(self.latest_alerts(), local, end) is not None


# ----- what's noteworthy (WX2) -------------------------------------------------------------

DAY_ENDS = time(21)  # the waking day the rules look at ends at 9 pm
FREEZING_F = 32.0
ICE_CODES = frozenset({56, 57, 66, 67})  # freezing drizzle, freezing rain
STORM_CODES = frozenset(range(95, 100))  # thunderstorms, with or without hail
MOST_OF_THE_DAY = 0.75  # this share of the waking hours wet: "most of the day"


def _clock(at: datetime) -> str:
    if at.hour == 12:
        return "noon"
    hour = at.hour % 12 or 12
    return f"{hour} {'am' if at.hour < 12 else 'pm'}"


def _part(at: datetime) -> str:
    if at.hour < 12:
        return "this morning"
    if at.hour < 17:
        return "this afternoon"
    return "this evening"


def _degrees(f: float, units: str) -> str:
    return f"{round((f - 32) * 5 / 9)}°C" if units == "C" else f"{round(f)}°F"


def _snow(inches: float, units: str) -> str:
    if units == "C":
        return f"{max(1, round(inches * 2.54))} cm"
    halves = max(1, round(inches * 2))
    return f"{halves // 2} in" if halves % 2 == 0 else f"{halves / 2:g} in"


def _speed(mph: float, units: str) -> str:
    return f"{round(mph * 1.609)} km/h" if units == "C" else f"{round(mph)} mph"


def _alert_line(alerts: Sequence[Alert], start: datetime, end: datetime) -> str | None:
    """Rank 1 (WX3): the gravest NWS alert in force during the waking day."""
    during = [a for a in alerts if a.starts < end and (a.ends is None or a.ends > start)]
    if not during:
        return None

    def gravity(a: Alert) -> tuple[int, datetime]:
        kind = next(i for i, k in enumerate(ALERT_KINDS) if a.event.endswith(k))
        return (kind, a.starts)

    alert = min(during, key=gravity)
    if alert.starts <= start:
        return f"{alert.event} in effect today."
    return f"{alert.event} from {_clock(alert.starts.astimezone(start.tzinfo))}."


def noteworthy(
    forecast: Forecast,
    start: datetime,
    end: datetime,
    settings: WeatherSettings,
    alerts: Sequence[Alert] = (),
) -> str | None:
    """The one line for the waking day from `start` to `end`, or None on a fair day. The
    first rule that holds gives it (the plan's table: NWS's alerts, then ranks 2 to 9).
    Thresholds are in °F, inches and mph; `settings.units` changes only the words. A
    statement of the weather, never advice."""
    hours = [h for h in forecast.hours if h.at + timedelta(hours=1) > start and h.at < end]
    if not hours:
        return None
    official = _alert_line(alerts, start, end)
    if official:
        return official
    day = start.date()
    today, yesterday = forecast.day(day), forecast.day(day - timedelta(days=1))
    units = settings.units

    def when(first: datetime) -> str:
        return _part(first) if first <= hours[0].at else f"from about {_clock(first)}"

    ice = [h for h in hours if h.code in ICE_CODES]
    if ice:
        return f"Freezing rain likely {when(ice[0].at)}."
    storms = [h for h in hours if h.code in STORM_CODES]
    if storms:
        return f"Thunderstorms likely {when(storms[0].at)}."
    snowy = [h for h in hours if h.snow > 0]
    snow = sum(h.snow for h in hours)
    if snow >= settings.snow_in:
        amount = _snow(snow, units)
        if len(snowy) >= MOST_OF_THE_DAY * len(hours):
            return f"Snow most of the day, around {amount}."
        return f"Snow {when(snowy[0].at)}, around {amount}."
    wet = [h for h in hours if h.chance >= settings.rain_chance]
    if wet and sum(h.rain for h in hours) >= settings.rain_in:
        high = f", high {_degrees(today.high, units)}" if today else ""
        if len(wet) >= MOST_OF_THE_DAY * len(hours):
            return f"Rain most of the day{high}."
        return f"Rain likely {when(wet[0].at)}{high}."
    if today and yesterday and today.low <= FREEZING_F < yesterday.low:
        coldest = min(forecast.hours_on(day), key=lambda h: h.temp, default=None)
        part = "this morning" if coldest and coldest.at.hour < 12 else "tonight"
        return f"Below freezing {part}, low {_degrees(today.low, units)}."
    if today and today.high >= settings.heat_f:
        return f"Hot today, high {_degrees(today.high, units)}."
    if today and today.low <= settings.cold_f:
        return f"Bitter cold today, low {_degrees(today.low, units)}."
    gusty = max(hours, key=lambda h: h.gust)
    if gusty.gust >= settings.gust_mph:
        return f"Gusty, up to {_speed(gusty.gust, units)} {_part(gusty.at)}."
    if today and yesterday and abs(today.high - yesterday.high) >= settings.change_f:
        word = "colder" if today.high < yesterday.high else "warmer"
        return f"Much {word} than yesterday, high {_degrees(today.high, units)}."
    return None


class WeatherModule(Module):
    """WX1: the forecast at home, for the morning message's weather line (MM5)."""

    name = NAME
    title = "Weather"
    summary = "A line in the morning message when the day's weather is worth knowing."
    cost = "Free, no account"
    kind = "connector"
    needs_accounts = AccountNeed(
        "the home address", "/family", "an admin", "SELECT 1 FROM family_home WHERE id = 1"
    )
    settings = WeatherSettings
    migrations = Path(__file__).parent / "weather_schema"

    def __init__(self, source: WeatherSource, settings: WeatherSettings | None = None) -> None:
        self.source = source
        self.weather_settings = settings or WeatherSettings()

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        return cls(WeatherClient(), setup.read(WeatherSettings))

    async def check(self) -> str | None:
        """Test: Open-Meteo, and when it fails, NWS's stand-in (WX4); both inside the
        portal's wait, so Open-Meteo gets `TEST_OPEN_METEO_WITHIN` of it."""
        lat, lon, tz = TEST_PLACE
        try:
            await asyncio.wait_for(self.source.forecast(lat, lon, tz), TEST_OPEN_METEO_WITHIN)
            return None
        except TimeoutError:
            failed = f"no answer within {int(TEST_OPEN_METEO_WITHIN)} seconds"
        except WeatherError as exc:
            failed = str(exc)
        try:
            grid = await self.source.nws_grid(lat, lon)
            if grid is None:
                raise WeatherError("NWS says the test place isn't in the US")
            await self.source.nws_forecast(grid, tz)
        except WeatherError as exc:
            return (
                f"The weather service didn't answer: {failed}. "
                f"The National Weather Service didn't either: {exc}"
            )
        return (
            f"Open-Meteo didn't answer ({failed}); the National Weather Service did, "
            "so forecasts carry on in the US."
        )

    def install(self, ctx: ModuleContext) -> None:
        weather = ctx.provide(Weather(ctx.services, self.source, self.weather_settings))
        weather.install()
        ctx.periodic("weather.refresh", REFRESH_EVERY, weather.refresh)
