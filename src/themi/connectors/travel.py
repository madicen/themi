"""Where a place is and how long it takes to drive there (K4).

- With a TomTom key (`TOMTOM_API_KEY`, the free plan is plenty): TomTom's geocoder, and its
  router with live traffic, arriving at a given time.
- Without one: OpenStreetMap's Nominatim geocoder (free, one request a second, a named
  User-Agent), and an estimate from the straight-line distance at typical driving speeds.
  `Route.traffic` says which it was, so a message can call it a rough guess.

Both are plain HTTP over `httpx`; tests hand in a transport (`tests/fakes/travel.py`).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import httpx

from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

TOMTOM_URL = "https://api.tomtom.com"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "Themi household assistant (self-hosted; one family)"
TIMEOUT = 20.0
ROAD_FACTOR = 1.35  # roads wind: a straight line is shorter than the drive
TYPICAL_KMH = 45.0  # a mix of town and highway
PARKING_MINUTES = 5


class TravelError(Exception):
    pass


@dataclass(frozen=True)
class Place:
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    minutes: int
    traffic: bool  # live traffic (TomTom), or a rough estimate from the distance


def distance_km(a: Place, b: Place) -> float:
    """As the crow flies (haversine)."""
    r = 6371.0
    dlat, dlon = math.radians(b.lat - a.lat), math.radians(b.lon - a.lon)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(a.lat)) * math.cos(math.radians(b.lat)) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


def estimate(a: Place, b: Place) -> Route:
    """A rough drive time from the distance, rounded up to five minutes."""
    minutes = distance_km(a, b) * ROAD_FACTOR / TYPICAL_KMH * 60 + PARKING_MINUTES
    return Route(math.ceil(minutes / 5) * 5, traffic=False)


class TravelClient:
    def __init__(
        self,
        tomtom_key: Secret | None = None,
        *,
        tomtom_url: str = TOMTOM_URL,
        nominatim_url: str = NOMINATIM_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tomtom_key = tomtom_key
        self.tomtom_url = tomtom_url.rstrip("/")
        self.nominatim_url = nominatim_url.rstrip("/")
        self._transport = transport

    @property
    def live_traffic(self) -> bool:
        return self.tomtom_key is not None

    async def geocode(self, address: str) -> Place | None:
        """The place an address names, or None if it can't be found."""
        if self.tomtom_key is not None:
            body = await self._get(
                f"{self.tomtom_url}/search/2/geocode/{quote(address)}.json",
                {"key": self.tomtom_key.reveal(), "limit": "1"},
            )
            results = body.get("results") or [] if isinstance(body, dict) else []
            if not results:
                return None
            position = results[0].get("position") or {}
            return Place(float(position["lat"]), float(position["lon"]))
        body = await self._get(
            f"{self.nominatim_url}/search", {"q": address, "format": "json", "limit": "1"}
        )
        if not isinstance(body, list) or not body:
            return None
        return Place(float(body[0]["lat"]), float(body[0]["lon"]))

    async def route(self, start: Place, end: Place, arrive_at: datetime) -> Route:
        """How long the drive takes to arrive at `arrive_at`: with traffic when there's a
        key, else an estimate."""
        if self.tomtom_key is None:
            return estimate(start, end)
        body = await self._get(
            f"{self.tomtom_url}/routing/1/calculateRoute/"
            f"{start.lat},{start.lon}:{end.lat},{end.lon}/json",
            {
                "key": self.tomtom_key.reveal(),
                "traffic": "true",
                "arriveAt": arrive_at.isoformat(timespec="seconds"),
            },
        )
        if not isinstance(body, dict):
            raise TravelError("TomTom's answer had no route")
        try:
            seconds = int(body["routes"][0]["summary"]["travelTimeInSeconds"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TravelError("TomTom's answer had no route") from exc
        return Route(math.ceil(seconds / 60), traffic=True)

    async def _get(self, url: str, params: dict[str, str]) -> object:
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, transport=self._transport, headers={"User-Agent": USER_AGENT}
            ) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise TravelError(f"couldn't reach the map service ({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise TravelError(f"the map service said {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise TravelError("the map service's answer wasn't JSON") from exc
