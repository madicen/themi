"""CR17b: each pack's pages render from the pack's own templates, and its static files are
served under /static/<pack>/."""

from __future__ import annotations

import re

import httpx
import pytest

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario

ALL_FAKES = (
    "fake_google",
    "fake_gmail",
    "fake_gcal",
    "fake_spotify",
    "fake_home_connect",
    "fake_thinq",
    "fake_roborock",
    "fake_tuya",
    "fake_catgenie",
)


def get_pages(scenario: Scenario) -> list[str]:
    """Every GET page that takes nothing in its path (the golden file's walk)."""
    from tests.scenarios.test_golden import routes_of

    return [
        r.removeprefix("GET ") for r in routes_of(scenario) if r.startswith("GET ") and "{" not in r
    ]


@pytest.mark.usefixtures(*ALL_FAKES)
async def test_every_page_renders(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Erin")
    pages = get_pages(scenario)
    assert {"/recipes", "/safeway", "/spending", "/maintenance", "/email/noise"} <= set(pages)
    broken = []
    for path in pages:
        if path.startswith(("/auth/", "/login", "/logout", "/api/")):
            continue  # not pages: they redirect to or answer someone else
        response = await site.get(path)
        if response.status_code >= 400:
            broken.append(f"{path}: {response.status_code}")
    assert broken == []


@pytest.mark.usefixtures("fake_google")
async def test_a_packs_static_files_are_served_under_its_name(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    kitchen = (await site.get("/recipes/kitchen")).text
    (url,) = re.findall(r'src="(/static/home/kitchen\.js\?v=\w+)"', kitchen)
    response = await site.get(url)
    assert response.status_code == 200 and "visibilitychange" in response.text
    assert response.headers["cache-control"] == "no-cache"
    assert (await site.get("/static/home/../../web/kit.py")).status_code == 404
    assert (await site.get("/static/themi.css")).status_code == 200  # the core's, as before
