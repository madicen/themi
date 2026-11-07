"""BD5b: Spotify linking with PKCE, tokens kept encrypted and refreshed, the Premium check,
and playback through the trust tiers. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fakes.spotify import FakeSpotify
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.connectors.spotify import pkce_pair
from themi.core.music import NO_DEVICE_TEXT, Music


def music(scenario: Scenario) -> Music:
    assert scenario.app.services.music is not None
    return scenario.app.services.music


async def link(
    scenario: Scenario, site: httpx.AsyncClient, fake: FakeSpotify, name: str = "Erin"
) -> httpx.Response:
    csrf = await sign_in(scenario, site, name)
    started = await site.post("/accounts/spotify/link", data={"csrf": csrf})
    assert started.status_code == 303
    state, code = fake.approve(started.headers["location"])
    return await site.get(f"/auth/spotify/callback?state={state}&code={code}")


def test_the_pkce_challenge_is_the_verifiers_hash() -> None:
    import base64
    import hashlib

    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def test_linking_keeps_the_refresh_token_encrypted(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify
) -> None:
    done = await link(scenario, site, fake_spotify)
    assert done.status_code == 303 and done.headers["location"].startswith("/accounts")
    row = scenario.app.db.one("SELECT * FROM spotify_links")
    assert row is not None and row["premium"] == 1 and row["display_name"] == "Erin S"
    stored = bytes(row["refresh_token"])
    assert not any(t.encode() in stored for t in fake_spotify.refresh_tokens)
    page = await site.get("/accounts")
    assert (
        "Unlink Spotify" in page.text
        and "accounts.spotify.test" in page.headers["content-security-policy"]
    )


async def test_a_state_works_once_and_only_for_who_started_it(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    started = await site.post("/accounts/spotify/link", data={"csrf": csrf})
    state, code = fake_spotify.approve(started.headers["location"])
    async with httpx.AsyncClient(transport=site._transport, base_url="http://themi.test") as his:
        await sign_in(scenario, his, "Husband")
        await his.get(f"/auth/spotify/callback?state={state}&code={code}")
    assert scenario.app.db.one("SELECT * FROM spotify_links") is None
    again = await site.get(f"/auth/spotify/callback?state={state}&code={code}")
    assert again.status_code == 303 and scenario.app.db.one("SELECT * FROM spotify_links") is None


async def test_the_access_token_is_refreshed_when_it_runs_out(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify
) -> None:
    await link(scenario, site, fake_spotify)
    fake_spotify.add("playlist", "Lofi Beats")
    erin = scenario.member("Erin")
    first = await music(scenario).find(erin, "lofi")
    assert first is not None and first.name == "Lofi Beats"
    old = bytes(scenario.app.db.scalar("SELECT refresh_token FROM spotify_links"))
    clock.advance(timedelta(hours=2))
    assert await music(scenario).find(erin, "lofi") is not None
    assert bytes(scenario.app.db.scalar("SELECT refresh_token FROM spotify_links")) != old


async def test_no_device_is_one_line(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify
) -> None:
    await link(scenario, site, fake_spotify)
    fake_spotify.add("playlist", "Lofi Beats")
    scenario.primary.queue_tool_call("play_music", {"query": "lofi"})
    replies = await scenario.say("Erin", "play some lofi")
    assert replies == [NO_DEVICE_TEXT]
    assert fake_spotify.calls.count("PUT /v1/me/player/play") == 0


async def test_pause_is_through_the_music_tier(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify
) -> None:
    await link(scenario, site, fake_spotify)
    fake_spotify.add_device("Phone", active=True)
    fake_spotify.add("playlist", "Lofi Beats")
    scenario.primary.queue_tool_call("play_music", {"query": "lofi"})
    await scenario.say("Erin", "play some lofi")
    scenario.primary.queue_tool_call("pause_music", {})
    assert await scenario.say("Erin", "pause the music") == ["Paused."]
    rows = scenario.app.db.query("SELECT category, executor, status FROM pending_actions")
    assert [(r["category"], r["executor"], r["status"]) for r in rows] == [
        ("music", "music.play", "done"), ("music", "music.pause", "done"),
    ]  # fmt: skip


async def test_not_linked_says_where_to_link(scenario: Scenario, fake_spotify: FakeSpotify) -> None:
    scenario.primary.queue_tool_call("play_music", {"query": "lofi"})
    scenario.primary.queue_text("Spotify isn't linked yet; it's on the Accounts page.")
    replies = await scenario.say("Erin", "play some lofi")
    assert replies == ["Spotify isn't linked yet; it's on the Accounts page."]
