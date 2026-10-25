"""Helpers for driving the website over ASGI against the scenario app."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import httpx
import pytest

from tests.scenarios.harness import Scenario
from themi import clock
from themi.web import HealthSources, create_app
from themi.web.auth import WebAuth
from themi.web.kit import SiteContext


def web_client(scenario: Scenario, *, secure: bool = False) -> httpx.AsyncClient:
    web = create_app(
        HealthSources(scenario.app.db, None, clock.now()),
        SiteContext(scenario.app, base_url="http://themi.test", secure_cookies=secure),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web), base_url="http://themi.test", follow_redirects=False
    )


async def sign_in(scenario: Scenario, client: httpx.AsyncClient, name: str) -> str:
    """Sign `name` in through a login link; returns the page's CSRF token."""
    token = WebAuth(scenario.app.store).create_link_token(scenario.member(name))
    response = await client.post(f"/login/{token}")
    assert response.status_code == 303 and response.headers["location"] == "/"
    home = await client.get("/")
    return csrf_of(home.text)


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "page has no CSRF field"
    return match.group(1)


async def flash(client: httpx.AsyncClient, path: str) -> str:
    """The page at `path`, for reading the one-off message a POST left."""
    return (await client.get(path)).text


@pytest.fixture
async def site(scenario: Scenario) -> AsyncIterator[httpx.AsyncClient]:
    """A website client for the scenario app, signed out."""
    async with web_client(scenario) as client:
        yield client
