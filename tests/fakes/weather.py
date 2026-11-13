"""A fake weather service for WX1-WX3: Open-Meteo's forecast.

    fake_weather.span(0, 14, 18, chance=80, rain=0.1, code=61)  # rain today, 2 pm to 6 pm
    fake_weather.hour(0, 7, code=66)                             # freezing rain at 7 am
    fake_weather.day(-1, high=70)                                # yesterday's high
    fake_weather.fail("forecast", 500)                           # the next forecast fails

Days count from today (-1 is yesterday), hours are local and say when the hour starts.
Everything else is a fair day: no rain, 60°F, light wind. The scenario harness hands Themi
a WeatherClient over this transport when a test uses the `fake_weather` fixture.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
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
        self.calls: list[tuple[str, dict[str, str]]] = []
        self._failures: Counter[str] = Counter()
        self.transport = httpx.MockTransport(self._handle)

    def hour(self, day: int, start: int, **values: Any) -> None:
        self.hours.setdefault((day, start), {}).update(values)

    def span(self, day: int, start: int, end: int, **values: Any) -> None:
        """The hours from `start` up to (not including) `end`."""
        for hour in range(start, end):
            self.hour(day, hour, **values)

    def day(self, day: int, *, high: float | None = None, low: float | None = None) -> None:
        if high is not None:
            self.days.setdefault(day, {})["high"] = high
        if low is not None:
            self.days.setdefault(day, {})["low"] = low

    def fail(self, kind: str = "forecast", status: int = 500, times: int = 1) -> None:
        self._failures[f"{kind}:{status}"] += times

    def client(self) -> WeatherClient:
        return WeatherClient(open_meteo_url="https://open-meteo.test", transport=self.transport)

    def count(self, kind: str = "forecast") -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    def _failure(self, kind: str) -> httpx.Response | None:
        for failure in list(self._failures):
            name, status = failure.split(":")
            if name == kind and self._failures[failure]:
                self._failures[failure] -= 1
                return httpx.Response(int(status))
        return None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if request.url.host != "open-meteo.test" or request.url.path != "/v1/forecast":
            return httpx.Response(404)
        assert "Themi" in request.headers.get("User-Agent", "")
        self.calls.append(("forecast", params))
        failed = self._failure("forecast")
        if failed is not None:
            return failed
        assert params["temperature_unit"] == "fahrenheit" and params["past_days"] == "1"
        return _json(self._forecast(ZoneInfo(params["timezone"])))

    def _forecast(self, tz: ZoneInfo) -> dict[str, Any]:
        today = clock.now().astimezone(tz).date()
        hourly: dict[str, list[Any]] = {"time": [], **{f: [] for f in FIELDS.values()}}
        daily: dict[str, list[Any]] = {
            "time": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
        }
        for offset in (-1, 0, 1):
            day = today + timedelta(days=offset)
            start = datetime(day.year, day.month, day.day, tzinfo=tz)
            temps = []
            for hour in range(24):
                values = {**FAIR, **self.hours.get((offset, hour), {})}
                label = start + timedelta(hours=hour + 1)  # Open-Meteo labels the hour's end
                hourly["time"].append(label.strftime("%Y-%m-%dT%H:%M"))
                for name, field in FIELDS.items():
                    hourly[field].append(values[name])
                temps.append(values["temp"])
            set_days = self.days.get(offset, {})
            daily["time"].append(day.isoformat())
            daily["temperature_2m_max"].append(set_days.get("high", max(temps) + 5))
            daily["temperature_2m_min"].append(set_days.get("low", min(temps) - 10))
        return {"timezone": tz.key, "hourly": hourly, "daily": daily}


def _json(body: Any) -> httpx.Response:
    return httpx.Response(
        200, content=json.dumps(body), headers={"Content-Type": "application/json"}
    )


@pytest.fixture
def fake_weather() -> FakeWeather:
    return FakeWeather()
