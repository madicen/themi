"""Today's weather at home (WX1; the Themi Weather Module Plan).

Open-Meteo's forecast: no key, no account, free for personal home automation. One call
gives yesterday, today and tomorrow, hour by hour, in °F, inches and mph (the rules are in
those units; °C only changes the words). Plain HTTP over `httpx`; tests hand in a transport
(`tests/fakes/weather.py`).

The User-Agent is generic, as the travel connector's is: no family details leave the house.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from themi.http import tls

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com"
USER_AGENT = "Themi household assistant (self-hosted; one family)"
TIMEOUT = 20.0
HOURLY = (
    "precipitation_probability",
    "precipitation",
    "snowfall",
    "weather_code",
    "temperature_2m",
    "wind_gusts_10m",
)
DAILY = ("temperature_2m_max", "temperature_2m_min")


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class Hour:
    """One hour of the forecast, starting at `at` (in the family's time zone). Open-Meteo's sums
    (rain, snow, gusts, the chance) are for the hour before the time it labels them with,
    so an hour labelled 14:00 is the one that starts at 13:00."""

    at: datetime
    chance: int  # %, of more than 0.1 mm
    rain: float  # inches, rain and snow's water
    snow: float  # inches of snow
    code: int  # WMO weather code
    temp: float  # °F
    gust: float  # mph


@dataclass(frozen=True)
class Day:
    day: date
    high: float  # °F
    low: float  # °F


@dataclass(frozen=True)
class Forecast:
    hours: tuple[Hour, ...]
    days: tuple[Day, ...]

    def day(self, day: date) -> Day | None:
        return next((d for d in self.days if d.day == day), None)

    def hours_on(self, day: date) -> list[Hour]:
        return [h for h in self.hours if h.at.date() == day]

    def to_json(self) -> dict[str, Any]:
        return {
            "hours": [{**asdict(h), "at": h.at.isoformat()} for h in self.hours],
            "days": [{**asdict(d), "day": d.day.isoformat()} for d in self.days],
        }

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Forecast:
        return cls(
            tuple(Hour(**{**h, "at": datetime.fromisoformat(h["at"])}) for h in body["hours"]),
            tuple(Day(**{**d, "day": date.fromisoformat(d["day"])}) for d in body["days"]),
        )


class WeatherSource(Protocol):
    async def forecast(self, lat: float, lon: float, timezone: str) -> Forecast: ...


class WeatherClient:
    def __init__(
        self,
        *,
        open_meteo_url: str = OPEN_METEO_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.open_meteo_url = open_meteo_url.rstrip("/")
        self._transport = transport

    async def forecast(self, lat: float, lon: float, timezone: str) -> Forecast:
        """Yesterday, today and tomorrow at this place, hours in `timezone`."""
        body = await self._get(
            f"{self.open_meteo_url}/v1/forecast",
            {
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "timezone": timezone,
                "past_days": "1",
                "forecast_days": "2",
                "hourly": ",".join(HOURLY),
                "daily": ",".join(DAILY),
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "wind_speed_unit": "mph",
            },
        )
        try:
            return _parse(body, ZoneInfo(timezone))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise WeatherError("the forecast's answer wasn't one Themi could read") from exc

    async def _get(self, url: str, params: dict[str, str]) -> Any:
        try:
            async with httpx.AsyncClient(
                verify=tls(),
                timeout=TIMEOUT,
                transport=self._transport,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise WeatherError(
                f"couldn't reach the weather service ({type(exc).__name__})"
            ) from exc
        if response.status_code != 200:
            raise WeatherError(f"the weather service said {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise WeatherError("the weather service's answer wasn't JSON") from exc


def _number(values: list[Any], i: int, default: float = 0.0) -> float:
    value = values[i] if i < len(values) else None
    return default if value is None else float(value)


def _parse(body: Any, tz: ZoneInfo) -> Forecast:
    hourly, daily = body["hourly"], body["daily"]
    hours = []
    for i, label in enumerate(hourly["time"]):
        if hourly["temperature_2m"][i] is None:
            continue  # past the model's reach
        hours.append(
            Hour(
                at=datetime.fromisoformat(label).replace(tzinfo=tz) - timedelta(hours=1),
                chance=round(_number(hourly["precipitation_probability"], i)),
                rain=_number(hourly["precipitation"], i),
                snow=_number(hourly["snowfall"], i),
                code=round(_number(hourly["weather_code"], i)),
                temp=_number(hourly["temperature_2m"], i),
                gust=_number(hourly["wind_gusts_10m"], i),
            )
        )
    days = [
        Day(date.fromisoformat(d), float(high), float(low))
        for d, high, low in zip(
            daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"], strict=True
        )
        if high is not None and low is not None
    ]
    if not hours:
        raise ValueError("no hours")
    return Forecast(tuple(hours), tuple(days))
