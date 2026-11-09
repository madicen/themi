"""CK11: the kitchen tablet. /session can be added to a home screen as its own app: the
manifest, its icons and the page's links to them."""

from __future__ import annotations

import httpx

from tests.scenarios.harness import Scenario


async def test_the_manifest_opens_the_session_page_as_an_app(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    answer = await site.get("/session/manifest.webmanifest")  # signed out: nothing private
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/manifest+json")
    made = answer.json()
    assert (made["name"], made["start_url"], made["scope"]) == ("Themi", "/session", "/session")
    assert made["display"] == "standalone" and made["display_override"][0] == "fullscreen"
    assert {icon["sizes"] for icon in made["icons"]} == {"192x192", "512x512"}
    for icon in made["icons"]:
        image = await site.get(icon["src"])
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert "maskable" in icon["purpose"]


async def test_the_session_page_links_it(scenario: Scenario, site: httpx.AsyncClient) -> None:
    page = await site.get("/session")
    assert '<link rel="manifest" href="/session/manifest.webmanifest">' in page.text
    touch = page.text.split('rel="apple-touch-icon" href="')[1].split('"')[0]
    assert (await site.get(touch)).headers["content-type"] == "image/png"
    assert 'name="apple-mobile-web-app-capable"' in page.text
