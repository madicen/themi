"""A fake map service for K4: TomTom's geocoder and router, and OpenStreetMap's Nominatim.

    fake_travel.place("12 Main St", 37.70, -122.40)   # an address it can find
    fake_travel.minutes = 35                           # TomTom's drive time, with traffic
    fake_travel.leg("12 Main St", "Smile Dental", 9)   # one drive's own time (F41d)
    fake_travel.use_tomtom = False                     # no key: Nominatim and an estimate
    fake_travel.fail("route", 500)                     # the next route lookup fails

The scenario harness hands Themi a TravelClient over this transport when a test uses the
`fake_travel` fixture. No real network calls.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from tests.fakes.snapshot import Snapshots
from themi.connectors.travel import TravelClient
from themi.storage.secrets import Secret

KEY = "tomtom-test-key"


class FakeTravel(Snapshots):
    SNAPSHOT = ("places", "minutes", "use_tomtom")  # D5a: what `make dev` keeps between runs

    def __init__(self) -> None:
        self.places: dict[str, tuple[float, float]] = {}
        self.minutes = 30
        self.legs: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
        self.use_tomtom = True
        self.calls: list[tuple[str, dict[str, str]]] = []  # (kind, query params)
        self._failures: Counter[str] = Counter()
        self.transport = httpx.MockTransport(self._handle)

    def place(self, address: str, lat: float, lon: float) -> None:
        self.places[address.lower()] = (lat, lon)

    def leg(self, start: str, end: str, minutes: int) -> None:
        """The drive from one known place to another takes `minutes` (else `minutes`)."""
        self.legs[(self.places[start.lower()], self.places[end.lower()])] = minutes

    def fail(self, kind: str, status: int = 500, times: int = 1) -> None:
        self._failures[f"{kind}:{status}"] += times

    def client(self) -> TravelClient:
        return TravelClient(
            Secret(KEY) if self.use_tomtom else None,
            tomtom_url="https://tomtom.test",
            nominatim_url="https://osm.test",
            transport=self.transport,
        )

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        path = request.url.path
        if request.url.host == "tomtom.test" and path.startswith("/search/2/geocode/"):
            kind, query = (
                "geocode",
                unquote(path.removeprefix("/search/2/geocode/").removesuffix(".json")),
            )
        elif request.url.host == "tomtom.test" and path.startswith("/routing/1/calculateRoute/"):
            kind, query = "route", ""
        elif request.url.host == "osm.test" and path == "/search":
            kind, query = "nominatim", params.get("q", "")
            assert "Themi" in request.headers.get("User-Agent", "")  # Nominatim's policy
        else:
            return httpx.Response(404)
        self.calls.append((kind, params))
        for failure in list(self._failures):
            name, status = failure.split(":")
            if name == kind and self._failures[failure]:
                self._failures[failure] -= 1
                return httpx.Response(int(status))
        if kind == "route":
            assert params.get("key") == KEY and params.get("traffic") == "true"
            ends = path.removeprefix("/routing/1/calculateRoute/").split("/")[0].split(":")
            a, b = (tuple(float(x) for x in end.split(",")) for end in ends)
            minutes = self.legs.get((a, b), self.minutes)  # type: ignore[arg-type]
            return _json({"routes": [{"summary": {"travelTimeInSeconds": minutes * 60}}]})
        found = self.places.get(query.lower())
        if kind == "geocode":
            assert params.get("key") == KEY
            results = [{"position": {"lat": found[0], "lon": found[1]}}] if found else []
            return _json({"results": results})
        return _json([{"lat": str(found[0]), "lon": str(found[1])}] if found else [])


def _json(body: Any) -> httpx.Response:
    return httpx.Response(
        200, content=json.dumps(body), headers={"Content-Type": "application/json"}
    )


@pytest.fixture
def fake_travel() -> FakeTravel:
    return FakeTravel()
