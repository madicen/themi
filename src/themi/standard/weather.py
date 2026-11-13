"""The weather at home (WX1-WX3; the Themi Weather Module Plan).

The `weather` module keeps today's forecast for the family's home (K4's `family_home`) in
one stored row, refreshed each hour, so the morning message reads it without a network
call. One forecast for the household: the same line for everyone.

- Open-Meteo's forecast (`themi.connectors.weather`): no key, no account.
- A forecast older than `FRESH` isn't used. A refresh that fails keeps the last good one,
  and is logged once for the outage. Nothing about it ever reaches the family.
- Off until it's turned on; without a home address it does nothing (the Modules page says
  to set one on the Family page).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import field_validator

from themi import clock
from themi.connectors.weather import Forecast, WeatherClient, WeatherError, WeatherSource
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
            forecast = await self.source.forecast(home[0], home[1], tz.key)
        except WeatherError as exc:
            if not self._down:
                log.warning("weather: the forecast didn't come: %s", exc)
            self._down = True
            return False
        if self._down:
            log.info("weather: the forecast is back")
        self._down = False
        today = self.today()
        self.db.execute(
            "INSERT INTO weather_forecasts (day, fetched_at, forecast) VALUES (?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET fetched_at = excluded.fetched_at, "
            "forecast = excluded.forecast",
            (today.isoformat(), to_utc_iso(clock.now()), json.dumps(forecast.to_json())),
        )
        self.db.execute(
            "DELETE FROM weather_forecasts WHERE day < ?",
            ((today - timedelta(days=1)).isoformat(),),
        )
        return True

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

    def latest(self) -> Forecast | None:
        """The newest forecast fetched within `FRESH`, or None."""
        row = self._latest_row()
        if row is None:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if clock.now() - fetched > FRESH:
            return None
        return Forecast.from_json(json.loads(row["forecast"]))


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
        lat, lon, tz = TEST_PLACE
        try:
            await self.source.forecast(lat, lon, tz)
        except WeatherError as exc:
            return f"The weather service didn't answer: {exc}"
        return None

    def install(self, ctx: ModuleContext) -> None:
        weather = ctx.provide(Weather(ctx.services, self.source, self.weather_settings))
        weather.install()
        ctx.periodic("weather.refresh", REFRESH_EVERY, weather.refresh)
