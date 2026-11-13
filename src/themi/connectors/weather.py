"""Today's weather at home (WX1, WX3; the Themi Weather Module Plan).

Open-Meteo's forecast: no key, no account, free for personal home automation. One call
gives yesterday, today and tomorrow, hour by hour, in °F, inches and mph (the rules are in
those units; °C only changes the words). Plain HTTP over `httpx`; tests hand in a transport
(`tests/fakes/weather.py`).

In the US, the National Weather Service's active warnings, watches and advisories for the
point (WX3): no key, public domain. `in_us` asks NWS's `points` once per address: it
answers 404 outside the US.

WX4: when Open-Meteo can't be reached, NWS's gridpoint forecast stands in for it in the
US (`nws_grid`, then `nws_forecast`): the raw grid's interval series, unpacked into the
same hours and days, in the same units, so the rules don't know which service answered.

The User-Agent is generic, as the travel connector's is: no family details leave the house.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from themi.http import tls

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com"
NWS_URL = "https://api.weather.gov"
ALERT_KINDS = ("Warning", "Watch", "Advisory")  # not statements or outlooks
USER_AGENT = "Themi household assistant (self-hosted; one family)"
TIMEOUT = 8.0  # per phase (connect, read): both inside the portal Test's 20 s wait
HOURLY = (
    "precipitation_probability",
    "precipitation",
    "snowfall",
    "weather_code",
    "temperature_2m",
    "wind_gusts_10m",
)
DAILY = (
    "temperature_2m_max",
    "temperature_2m_min",
    "weather_code",  # DC6: the week ahead's icon for each day
    "precipitation_probability_max",
)
FORECAST_DAYS = 7  # DC6: today and the six after, for the week ahead (WX1 asked for 2)


class WeatherError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the HTTP status, when the service answered with one


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
    code: int = 0  # WMO, the day's (DC6); 0 in a forecast stored before it
    chance: int = 0  # %, the day's highest chance of rain or snow (DC6)


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


@dataclass(frozen=True)
class Alert:
    """An NWS warning, watch or advisory in force at the point."""

    event: str  # "Winter Storm Warning"
    starts: datetime
    ends: datetime | None  # None: until further notice

    def to_json(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "starts": self.starts.isoformat(),
            "ends": self.ends.isoformat() if self.ends else None,
        }

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Alert:
        ends = body.get("ends")
        return cls(
            body["event"],
            datetime.fromisoformat(body["starts"]),
            datetime.fromisoformat(ends) if ends else None,
        )


class WeatherSource(Protocol):
    async def forecast(self, lat: float, lon: float, timezone: str) -> Forecast: ...

    async def in_us(self, lat: float, lon: float) -> bool: ...

    async def alerts(self, lat: float, lon: float) -> list[Alert]: ...

    async def nws_grid(self, lat: float, lon: float) -> str | None: ...

    async def nws_forecast(self, grid_url: str, timezone: str) -> Forecast: ...


class WeatherClient:
    def __init__(
        self,
        *,
        open_meteo_url: str = OPEN_METEO_URL,
        nws_url: str = NWS_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.open_meteo_url = open_meteo_url.rstrip("/")
        self.nws_url = nws_url.rstrip("/")
        self._transport = transport

    async def forecast(self, lat: float, lon: float, timezone: str) -> Forecast:
        """Yesterday, today and the six days after at this place, hours in `timezone`."""
        body = await self._get(
            f"{self.open_meteo_url}/v1/forecast",
            {
                "latitude": f"{lat:.4f}",
                "longitude": f"{lon:.4f}",
                "timezone": timezone,
                "past_days": "1",
                "forecast_days": str(FORECAST_DAYS),
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

    async def in_us(self, lat: float, lon: float) -> bool:
        """Whether NWS forecasts for this point: a 404 means it's outside the US."""
        return await self.nws_grid(lat, lon) is not None

    async def nws_grid(self, lat: float, lon: float) -> str | None:
        """WX4: the address of NWS's raw forecast grid for this point; None outside the US
        (`points` answers 404). An empty string when NWS answered without one."""
        try:
            body = await self._get(f"{self.nws_url}/points/{lat:.4f},{lon:.4f}", {}, nws=True)
        except WeatherError as exc:
            if exc.status == 404:
                return None
            raise
        props = body.get("properties") if isinstance(body, dict) else None
        return str((props or {}).get("forecastGridData") or "")

    async def nws_forecast(self, grid_url: str, timezone: str) -> Forecast:
        """WX4: NWS's forecast from its raw grid, hours in `timezone`. It has no yesterday:
        the caller fills that in from what it kept."""
        if not grid_url.startswith(self.nws_url + "/"):
            raise WeatherError("NWS gave no forecast grid for this place")
        body = await self._get(grid_url, {}, nws=True)
        try:
            return _parse_grid(body["properties"], ZoneInfo(timezone))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            raise WeatherError("NWS's forecast wasn't one Themi could read") from exc

    async def alerts(self, lat: float, lon: float) -> list[Alert]:
        """The warnings, watches and advisories in force at this point now."""
        body = await self._get(
            f"{self.nws_url}/alerts/active", {"point": f"{lat:.4f},{lon:.4f}"}, nws=True
        )
        try:
            features = body["features"]
            return [a for a in (_alert(f.get("properties") or {}) for f in features) if a]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise WeatherError("the weather warnings' answer wasn't one Themi could read") from exc

    async def _get(self, url: str, params: dict[str, str], *, nws: bool = False) -> Any:
        try:
            async with httpx.AsyncClient(
                verify=tls(),
                timeout=TIMEOUT,
                transport=self._transport,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/geo+json" if nws else "application/json",
                },
            ) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise WeatherError(
                f"couldn't reach the weather service ({type(exc).__name__})"
            ) from exc
        if response.status_code != 200:
            raise WeatherError(
                f"the weather service said {response.status_code}", response.status_code
            )
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
    codes = daily.get("weather_code") or []
    chances = daily.get("precipitation_probability_max") or []
    days = [
        Day(
            date.fromisoformat(d),
            float(high),
            float(low),
            code=round(_number(codes, i)),
            chance=round(_number(chances, i)),
        )
        for i, (d, high, low) in enumerate(
            zip(
                daily["time"],
                daily["temperature_2m_max"],
                daily["temperature_2m_min"],
                strict=True,
            )
        )
        if high is not None and low is not None
    ]
    if not hours:
        raise ValueError("no hours")
    return Forecast(tuple(hours), tuple(days))


def _alert(p: dict[str, Any]) -> Alert | None:
    """A warning, watch or advisory that's real and not cancelled; None for the rest."""
    event = str(p.get("event") or "")
    if p.get("status") != "Actual" or p.get("messageType") == "Cancel":
        return None
    if not event.endswith(ALERT_KINDS):
        return None
    starts = p.get("onset") or p.get("effective")
    if not starts:
        return None
    ends = p.get("ends") or p.get("expires")
    return Alert(
        event,
        datetime.fromisoformat(starts),
        datetime.fromisoformat(ends) if ends else None,
    )


# ----- NWS's raw grid (WX4) -----------------------------------------------------------------

DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
TO_F = {"wmoUnit:degC": lambda c: c * 9 / 5 + 32, "wmoUnit:degF": lambda f: f}
TO_INCHES = {
    "wmoUnit:mm": lambda mm: mm / 25.4,
    "wmoUnit:cm": lambda cm: cm / 2.54,
    "wmoUnit:m": lambda m: m / 0.0254,
    "wmoUnit:in": lambda i: i,
}
TO_MPH = {
    "wmoUnit:km_h-1": lambda k: k / 1.609344,
    "wmoUnit:m_s-1": lambda m: m * 2.236936,
    "wmoUnit:kn": lambda k: k * 1.150779,
    "wmoUnit:mi_h-1": lambda m: m,
}
SAME = {"wmoUnit:percent": lambda p: p}
# NWS's weather words → the WMO code the rules and the pictures read: (light, moderate, heavy).
WMO_FOR = {
    "drizzle": (51, 53, 55),
    "freezing_drizzle": (56, 56, 57),
    "rain": (61, 63, 65),
    "freezing_rain": (66, 66, 67),
    "snow": (71, 73, 75),
    "sleet": (79, 79, 79),
    "ice_crystals": (77, 77, 77),
    "rain_showers": (80, 81, 82),
    "snow_showers": (85, 85, 86),
    "thunderstorms": (95, 95, 95),
    "fog": (45, 45, 45),
    "freezing_fog": (48, 48, 48),
    "ice_fog": (48, 48, 48),
}
UNLIKELY = frozenset({"slight_chance", "chance", "isolated", "scattered"})


def _interval(valid_time: str) -> tuple[datetime, int]:
    """ "2026-11-13T14:00:00+00:00/PT6H" → its start and how many whole hours it runs."""
    start, _, duration = valid_time.partition("/")
    match = DURATION.match(duration)
    if not match:
        raise ValueError(f"not a duration: {duration!r}")
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    total = days * 24 + hours + (1 if minutes or seconds else 0)
    begins = datetime.fromisoformat(start)
    if begins.tzinfo is None:
        raise ValueError("a time without a zone")
    return begins, max(1, total)


def _hourly(
    series: dict[str, Any] | None, units: dict[str, Any], *, spread: bool = False
) -> dict[datetime, float]:
    """A grid series by the hour (UTC hour starts). A sum over several hours (`spread`) is
    shared out evenly; anything else holds for each hour of its interval."""
    if not series:
        return {}
    convert = units[series.get("uom", next(iter(units)))]
    out: dict[datetime, float] = {}
    for item in series.get("values") or []:
        if item.get("value") is None:
            continue
        begins, hours = _interval(item["validTime"])
        value = convert(float(item["value"]))
        for i in range(hours):
            out[begins + timedelta(hours=i)] = value / hours if spread else value
    return out


def _wmo(entries: list[dict[str, Any]] | None) -> int:
    """The gravest likely weather in one interval of NWS's `weather` series, as a WMO code."""
    code = 0
    for entry in entries or []:
        codes = WMO_FOR.get(str(entry.get("weather") or ""))
        if codes is None or entry.get("coverage") in UNLIKELY:
            continue
        intensity = entry.get("intensity") or ""
        step = 2 if intensity == "heavy" else 1 if intensity == "moderate" else 0
        code = max(code, codes[step])
        if entry.get("weather") == "thunderstorms" and "large_hail" in (
            entry.get("attributes") or []
        ):
            code = max(code, 96)
    return code


def _sky(cover: float | None) -> int:
    if cover is None:
        return 0
    return 0 if cover < 25 else 1 if cover < 50 else 2 if cover < 88 else 3


def _parse_grid(p: dict[str, Any], tz: ZoneInfo) -> Forecast:
    temps = _hourly(p["temperature"], TO_F)
    chances = _hourly(p.get("probabilityOfPrecipitation"), SAME)
    rain = _hourly(p.get("quantitativePrecipitation"), TO_INCHES, spread=True)
    snow = _hourly(p.get("snowfallAmount"), TO_INCHES, spread=True)
    gusts = _hourly(p.get("windGust"), TO_MPH)
    sky = _hourly(p.get("skyCover"), SAME)
    weather: dict[datetime, int] = {}
    for item in (p.get("weather") or {}).get("values") or []:
        begins, span = _interval(item["validTime"])
        for i in range(span):
            weather[begins + timedelta(hours=i)] = _wmo(item.get("value"))
    hours = tuple(
        Hour(
            at=at.astimezone(tz),
            chance=round(chances.get(at, 0)),
            rain=rain.get(at, 0.0),
            snow=snow.get(at, 0.0),
            code=max(weather.get(at, 0), _sky(sky.get(at))),
            temp=temp,
            gust=gusts.get(at, 0.0),
        )
        for at, temp in sorted(temps.items())
    )
    if not hours:
        raise ValueError("no hours")
    highs = _daily(p.get("maxTemperature"), tz, by_end=False)
    lows = _daily(p.get("minTemperature"), tz, by_end=True)  # the night's low, by its morning
    days = []
    for day in sorted({h.at.date() for h in hours} | set(highs) | set(lows)):
        on_day = [h for h in hours if h.at.date() == day]
        high = highs.get(day, max((h.temp for h in on_day), default=None))
        low = lows.get(day, min((h.temp for h in on_day), default=None))
        if high is None or low is None:
            continue
        days.append(
            Day(
                day,
                high,
                low,
                code=max((h.code for h in on_day), default=0),
                chance=max((h.chance for h in on_day), default=0),
            )
        )
    return Forecast(hours, tuple(days))


def _daily(series: dict[str, Any] | None, tz: ZoneInfo, *, by_end: bool) -> dict[date, float]:
    """The day's high (by when its period starts) or low (by when it ends: the morning)."""
    if not series:
        return {}
    convert = TO_F[series.get("uom", "wmoUnit:degC")]
    out: dict[date, float] = {}
    for item in series.get("values") or []:
        if item.get("value") is None:
            continue
        begins, hours = _interval(item["validTime"])
        at = begins + timedelta(hours=hours) if by_end else begins
        out[at.astimezone(tz).date()] = convert(float(item["value"]))
    return out
