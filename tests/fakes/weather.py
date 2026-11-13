"""A fake weather service for WX1-WX4: Open-Meteo's forecast, NWS's alerts and its grid.

    fake_weather.span(0, 14, 18, chance=80, rain=0.1, code=61)  # rain today, 2 pm to 6 pm
    fake_weather.hour(0, 7, code=66)                             # freezing rain at 7 am
    fake_weather.day(-1, high=70)                                # yesterday's high
    fake_weather.fail("forecast", 500)                           # the next forecast fails
    fake_weather.alert("Winter Storm Warning", 18, None)         # NWS: from 6 pm today
    fake_weather.in_us = False                                   # NWS: `points` says 404
    fake_weather.hang("forecast")                                # the next one times out
    fake_weather.grid = {...}                                    # NWS: this raw grid instead

Days count from today (-1 is yesterday), hours are local and say when the hour starts.
Everything else is a fair day: no rain, 60°F, light wind. NWS's grid (WX4) is built
from the same hours and days, in its own units (°C, mm, km/h), from today on: it has no
yesterday. The scenario harness hands Themi
a WeatherClient over this transport when a test uses the `fake_weather` fixture.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from themi import clock
from themi.connectors.weather import WeatherClient

FAIR = {"chance": 0, "rain": 0.0, "snow": 0.0, "code": 1, "temp": 60.0, "gust": 10.0}
FIELDS = {
    "chance": "precipitation_probability",
    "rain": "precipitation",
    "snow": "snowfall",
    "code": "weather_code",
    "temp": "temperature_2m",
    "gust": "wind_gusts_10m",
}


class FakeWeather:
    def __init__(self) -> None:
        self.hours: dict[tuple[int, int], dict[str, Any]] = {}
        self.days: dict[int, dict[str, float]] = {}
        self.alerts: list[dict[str, Any]] = []  # NWS alerts' properties
        self.in_us = True
        self.forecast_days = 7  # what Themi asks for (the request's forecast_days)
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._failures: Counter[str] = Counter()
        self._hangs: Counter[str] = Counter()
        self.grid: dict[str, Any] | None = None  # WX4: a raw grid's properties, as given
        self.grid_tz = "America/Los_Angeles"  # the grid's days are this zone's
        self.transport = httpx.MockTransport(self._handle)

    def hour(self, day: int, start: int, **values: Any) -> None:
        self.hours.setdefault((day, start), {}).update(values)

    def span(self, day: int, start: int, end: int, **values: Any) -> None:
        """The hours from `start` up to (not including) `end`."""
        for hour in range(start, end):
            self.hour(day, hour, **values)

    def day(
        self, day: int, *, high: float | None = None, low: float | None = None,
        code: int | None = None,
    ) -> None:  # fmt: skip
        if high is not None:
            self.days.setdefault(day, {})["high"] = high
        if low is not None:
            self.days.setdefault(day, {})["low"] = low
        if code is not None:  # DC6: the day's own WMO code
            self.days.setdefault(day, {})["code"] = code

    def alert(
        self,
        event: str,
        start: int,
        end: int | None,
        *,
        day: int = 0,
        status: str = "Actual",
        message_type: str = "Alert",
        tz: str = "America/Los_Angeles",
    ) -> None:
        """An alert from `start` o'clock to `end` o'clock (None: no end given) on today+day."""
        local = clock.now().astimezone(ZoneInfo(tz)).date() + timedelta(days=day)
        midnight = datetime(local.year, local.month, local.day, tzinfo=ZoneInfo(tz))
        self.alerts.append(
            {
                "event": event,
                "status": status,
                "messageType": message_type,
                "onset": (midnight + timedelta(hours=start)).isoformat(),
                "ends": None if end is None else (midnight + timedelta(hours=end)).isoformat(),
                "expires": None,
            }
        )

    def fail(self, kind: str = "forecast", status: int = 500, times: int = 1) -> None:
        self._failures[f"{kind}:{status}"] += times

    def hang(self, kind: str = "forecast", times: int = 1) -> None:
        """The next `times` calls of this kind time out connecting (WX4)."""
        self._hangs[kind] += times

    def client(self) -> WeatherClient:
        return WeatherClient(
            open_meteo_url="https://open-meteo.test",
            nws_url="https://nws.test",
            transport=self.transport,
        )

    def count(self, kind: str = "forecast") -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    def _failure(self, kind: str) -> httpx.Response | None:
        if self._hangs[kind]:
            self._hangs[kind] -= 1
            raise httpx.ConnectTimeout("the handshake operation timed out")
        for failure in list(self._failures):
            name, status = failure.split(":")
            if name == kind and self._failures[failure]:
                self._failures[failure] -= 1
                return httpx.Response(int(status))
        return None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert "Themi" in request.headers.get("User-Agent", "")
        if request.url.host == "nws.test":
            return self._nws(request, params)
        if request.url.host != "open-meteo.test" or request.url.path != "/v1/forecast":
            return httpx.Response(404)
        self.calls.append(("forecast", params))
        failed = self._failure("forecast")
        if failed is not None:
            return failed
        assert params["temperature_unit"] == "fahrenheit" and params["past_days"] == "1"
        self.forecast_days = int(params["forecast_days"])
        return _json(self._forecast(ZoneInfo(params["timezone"])))

    def _nws(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        assert request.headers.get("Accept") == "application/geo+json"
        if request.url.path.startswith("/points/"):
            self.calls.append(("points", params))
            failed = self._failure("points")
            if failed is not None:
                return failed
            if not self.in_us:
                return httpx.Response(404)
            return _json({"properties": {"forecastGridData": GRID_URL}})
        if str(request.url) == GRID_URL:
            self.calls.append(("grid", params))
            failed = self._failure("grid")
            if failed is not None:
                return failed
            return _json({"properties": self.grid or self._grid(ZoneInfo(self.grid_tz))})
        if request.url.path == "/alerts/active":
            self.calls.append(("alerts", params))
            failed = self._failure("alerts")
            if failed is not None:
                return failed
            features = [{"type": "Feature", "properties": p} for p in self.alerts]
            return _json({"type": "FeatureCollection", "features": features})
        return httpx.Response(404)

    def _forecast(self, tz: ZoneInfo) -> dict[str, Any]:
        today = clock.now().astimezone(tz).date()
        hourly: dict[str, list[Any]] = {"time": [], **{f: [] for f in FIELDS.values()}}
        daily: dict[str, list[Any]] = {
            "time": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
            "weather_code": [],
            "precipitation_probability_max": [],
        }
        for offset in range(-1, int(self.forecast_days)):
            day = today + timedelta(days=offset)
            start = datetime(day.year, day.month, day.day, tzinfo=tz)
            temps, codes, chances = [], [], []
            for hour in range(24):
                values = {**FAIR, **self.hours.get((offset, hour), {})}
                label = start + timedelta(hours=hour + 1)  # Open-Meteo labels the hour's end
                hourly["time"].append(label.strftime("%Y-%m-%dT%H:%M"))
                for name, field in FIELDS.items():
                    hourly[field].append(values[name])
                temps.append(values["temp"])
                codes.append(values["code"])
                chances.append(values["chance"])
            set_days = self.days.get(offset, {})
            daily["time"].append(day.isoformat())
            daily["temperature_2m_max"].append(set_days.get("high", max(temps) + 5))
            daily["temperature_2m_min"].append(set_days.get("low", min(temps) - 10))
            daily["weather_code"].append(set_days.get("code", max(codes)))
            daily["precipitation_probability_max"].append(max(chances))
        return {"timezone": tz.key, "hourly": hourly, "daily": daily}

    def _grid(self, tz: ZoneInfo) -> dict[str, Any]:
        """NWS's raw grid for the same weather: hourly series from today's midnight, in its
        own units, and the day's high (7 am to 7 pm) and the night's low (7 pm to 8 am)."""
        today = clock.now().astimezone(tz).date()
        series: dict[str, list[dict[str, Any]]] = {k: [] for k in GRID_UNITS}
        weather: list[dict[str, Any]] = []
        for offset in range(int(self.forecast_days)):
            day = today + timedelta(days=offset)
            start = datetime(day.year, day.month, day.day, tzinfo=tz)
            temps: list[float] = []
            for hour in range(24):
                values = {**FAIR, **self.hours.get((offset, hour), {})}
                valid = f"{(start + timedelta(hours=hour)).astimezone(UTC).isoformat()}/PT1H"
                temps.append(values["temp"])
                for name, value in (
                    ("temperature", (values["temp"] - 32) * 5 / 9),
                    ("probabilityOfPrecipitation", values["chance"]),
                    ("quantitativePrecipitation", values["rain"] * 25.4),
                    ("snowfallAmount", values["snow"] * 25.4),
                    ("windGust", values["gust"] * 1.609344),
                    ("skyCover", {0: 10, 1: 30, 2: 60}.get(values["code"], 95)),
                ):
                    series[name].append({"validTime": valid, "value": value})
                word = NWS_WORDS.get(values["code"])
                weather.append(
                    {
                        "validTime": valid,
                        "value": [{"coverage": "likely", "weather": word, "intensity": None}]
                        if word
                        else [{"coverage": None, "weather": None, "intensity": None}],
                    }
                )
            set_days = self.days.get(offset, {})
            high = set_days.get("high", max(temps) + 5)
            low = set_days.get("low", min(temps) - 10)
            day_starts = (start + timedelta(hours=7)).astimezone(UTC).isoformat()
            night_starts = (start - timedelta(hours=5)).astimezone(UTC).isoformat()
            series["maxTemperature"].append(
                {"validTime": f"{day_starts}/PT12H", "value": (high - 32) * 5 / 9}
            )
            series["minTemperature"].append(  # the night before, ending this morning
                {"validTime": f"{night_starts}/PT13H", "value": (low - 32) * 5 / 9}
            )
        grid: dict[str, Any] = {
            name: {"uom": GRID_UNITS[name], "values": values} for name, values in series.items()
        }
        grid["weather"] = {"values": weather}
        return grid


GRID_URL = "https://nws.test/gridpoints/SEW/124,67"
GRID_UNITS = {
    "temperature": "wmoUnit:degC",
    "maxTemperature": "wmoUnit:degC",
    "minTemperature": "wmoUnit:degC",
    "probabilityOfPrecipitation": "wmoUnit:percent",
    "quantitativePrecipitation": "wmoUnit:mm",
    "snowfallAmount": "wmoUnit:mm",
    "windGust": "wmoUnit:km_h-1",
    "skyCover": "wmoUnit:percent",
}
NWS_WORDS = {  # the fake's WMO codes, as NWS words
    51: "drizzle", 56: "freezing_drizzle", 61: "rain", 66: "freezing_rain", 71: "snow",
    80: "rain_showers", 95: "thunderstorms",
}  # fmt: skip


def _json(body: Any) -> httpx.Response:
    return httpx.Response(
        200, content=json.dumps(body), headers={"Content-Type": "application/json"}
    )


@pytest.fixture
def fake_weather() -> FakeWeather:
    return FakeWeather()
