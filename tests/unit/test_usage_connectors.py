"""UC3: each connector's client counts the requests it sends; a 429 counts as refused."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from tests.fakes.modules import module_context
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.connectors.search import TavilySearch
from themi.connectors.travel import TravelClient
from themi.connectors.weather import WeatherClient
from themi.storage.secrets import Secret
from themi.usage import Tally, UsageBook

Answer = Callable[[httpx.Request], httpx.Response]


def answering(status: int, body: Any = None) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.MockTransport(answer)


@pytest.fixture
def usage(family: SeededFamily, frozen_clock: datetime) -> UsageBook:
    return UsageBook(family.db)


def counted(usage: UsageBook, key: str) -> tuple[int, int]:
    return usage.today(key).count, usage.today(f"{key}.refused").count


async def test_home_connect_counts_each_call_and_a_429_as_refused(usage: UsageBook) -> None:
    from themi_home.connectors.homeconnect.client import (
        HomeConnectClient,
        HomeConnectConfig,
        RateLimited,
    )

    config = HomeConnectConfig("id", Secret("secret"), base_url="https://hc.example")
    client = HomeConnectClient(config, transport=answering(200, {"data": {}}))
    client.tally = Tally(usage, "homeconnect.calls")
    await client._get("/api/homeappliances", Secret("token"))
    limited = HomeConnectClient(config, transport=answering(429))
    limited.tally = client.tally
    with pytest.raises(RateLimited):
        await limited._get("/api/homeappliances", Secret("token"))
    assert counted(usage, "homeconnect.calls") == (1, 1)


async def test_thinq_counts_each_call(usage: UsageBook) -> None:
    from themi_home.connectors.thinq.client import ThinqClient, ThinqConfig

    config = ThinqConfig(
        base_url="https://thinq.example", transport=answering(200, {"response": []})
    )
    client = ThinqClient(Secret("t"), "US", "client", config, tally=Tally(usage, "thinq.calls"))
    await client._call("GET", "/devices")
    await client._call("GET", "/devices")
    assert counted(usage, "thinq.calls") == (2, 0)


async def test_tuya_counts_each_call(usage: UsageBook) -> None:
    from themi_home.connectors.tuya.client import TuyaClient, TuyaConfig

    body = {"success": True, "result": []}
    config = TuyaConfig(base_url="https://tuya.example", transport=answering(200, body))
    client = TuyaClient("id", Secret("s"), "us", config, tally=Tally(usage, "tuya.calls"))
    client._token = "token"
    client._token_until = clock.now() + timedelta(hours=1)
    await client._call("GET", "/v1.0/devices/x/status")
    assert counted(usage, "tuya.calls") == (1, 0)


async def test_catgenie_counts_each_call(usage: UsageBook) -> None:
    from themi_home.connectors.catgenie.client import CatGenieClient, CatGenieConfig

    config = CatGenieConfig(base_url="https://pn.example", transport=answering(200))
    client = CatGenieClient(config, tally=Tally(usage, "catgenie.calls"))
    await client.send_code("+12065550100")
    assert counted(usage, "catgenie.calls") == (1, 0)


async def test_tomtom_counts_but_the_free_geocoder_doesnt(usage: UsageBook) -> None:
    tomtom = TravelClient(
        Secret("key"), tomtom_url="https://api.tomtom.example", transport=answering(200, {})
    )
    tomtom.tally = Tally(usage, "tomtom.requests")
    await tomtom.geocode("Pike Place Market")
    free = TravelClient(None, nominatim_url="https://geo.example", transport=answering(200, []))
    free.tally = tomtom.tally
    await free.geocode("Pike Place Market")
    assert counted(usage, "tomtom.requests") == (1, 0)


async def test_tavily_counts_a_credit_and_two_for_a_deep_search(usage: UsageBook) -> None:
    search = TavilySearch(Secret("k"), base_url="https://tavily.example",
                          transport=answering(200, {"results": []}))  # fmt: skip
    search.tally = Tally(usage, "tavily.credits")
    await search.search("soup")
    await search.search("soup", deep=True)
    assert counted(usage, "tavily.credits") == (3, 0)


async def test_open_meteo_and_nws_count_apart(usage: UsageBook) -> None:
    from themi.connectors.weather import WeatherError

    weather = WeatherClient(
        open_meteo_url="https://om.example", nws_url="https://nws.example",
        transport=answering(429),
    )  # fmt: skip
    weather.tally = Tally(usage, "openmeteo.calls")
    weather.nws_tally = Tally(usage, "nws.calls")
    with pytest.raises(WeatherError):
        await weather.forecast(47.6, -122.3, "America/Los_Angeles")
    assert counted(usage, "openmeteo.calls") == (0, 1)
    assert counted(usage, "nws.calls") == (0, 0)


async def test_a_google_client_counts_each_request(
    usage: UsageBook, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themi_google.connectors.gmail import client as gmail

    real = httpx.AsyncClient

    def mocked(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=answering(200, {"emailAddress": "erin@example.com"}), **kwargs)

    monkeypatch.setattr(gmail.httpx, "AsyncClient", mocked)

    async def token() -> Secret:
        return Secret("access")

    client = gmail.GmailClient("https://gmail.example", token, lambda: None)
    client.tally = Tally(usage, "google.requests")
    await client._request("GET", "/profile")
    assert counted(usage, "google.requests") == (1, 0)


def test_modules_register_their_meters(family: SeededFamily) -> None:
    from themi.standard.weather import WeatherModule
    from themi.standard.web_search import WebSearchModule

    ctx = module_context(family.store)
    tavily = TavilySearch(Secret("k"))
    weather = WeatherClient()
    ctx.load(WeatherModule(weather), WebSearchModule(tavily))
    meters = ctx.services.usage.meters
    assert {"openmeteo.calls", "nws.calls", "tavily.credits"} <= set(meters)
    assert "firecrawl.credits" not in meters  # only the backend in use
    assert tavily.tally.key == "tavily.credits" and weather.tally.key == "openmeteo.calls"
    tavily_limit = ctx.services.usage.limit_for("tavily.credits")
    assert tavily_limit is not None and tavily_limit.per_month == 1000


def test_a_module_not_installed_registers_nothing(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    assert not any(
        k.startswith(("homeconnect", "thinq", "google")) for k in ctx.services.usage.meters
    )
