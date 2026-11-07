"""A fake of Spotify's Web API and sign-in (BD5b), behind an httpx transport.

    fake_spotify.premium = False                    # a free account
    fake_spotify.add_device("Kitchen speaker")      # an open Spotify app
    fake_spotify.add("playlist", "Lofi Beats")      # something to find
    fake_spotify.add_mine("Focus")                  # one of their own playlists
    state, code = fake_spotify.approve(authorize_url)  # they say yes
    fake_spotify.revoke()                           # every token stops working

PKCE is checked: the token request's verifier must hash to the authorize URL's challenge.
Play without Premium answers 403 PREMIUM_REQUIRED; with no device, 404 NO_ACTIVE_DEVICE.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from themi import clock
from themi.connectors.spotify import SCOPES, SpotifyClient, SpotifyConfig

ACCOUNTS_URL = "https://accounts.spotify.test"
API_URL = "https://api.spotify.test/v1"
CLIENT_ID = "themi-spotify"
ACCESS_LIFETIME = timedelta(hours=1)


class FakeSpotify:
    def __init__(self) -> None:
        self.premium = True
        self.display_name = "Erin S"
        self.devices: list[dict] = []
        self.catalogue: list[dict] = []
        self.mine: list[dict] = []
        self.codes: dict[str, tuple[str, str]] = {}  # code -> (redirect_uri, challenge)
        self.access: dict[str, datetime] = {}
        self.refresh_tokens: set[str] = set()
        self.playing: dict | None = None  # {"context_uri"|"uris", "device_id"}
        self.paused = False
        self.calls: list[str] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self) -> SpotifyClient:
        return SpotifyClient(
            SpotifyConfig(CLIENT_ID, ACCOUNTS_URL, API_URL), transport=self.transport
        )

    # ----- the test's controls ----------------------------------------------------------

    def add_device(self, name: str, *, active: bool = False) -> str:
        device_id = f"dev-{len(self.devices) + 1}"
        self.devices.append({"id": device_id, "name": name, "is_active": active,
                             "is_restricted": False, "type": "Speaker"})  # fmt: skip
        return device_id

    def _entry(self, kind: str, name: str) -> dict:
        key = name.lower().replace(" ", "")
        return {"uri": f"spotify:{kind}:{key}", "name": name, "type": kind,
                "external_urls": {"spotify": f"https://open.spotify.com/{kind}/{key}"}}  # fmt: skip

    def add(self, kind: str, name: str) -> dict:
        entry = self._entry(kind, name)
        self.catalogue.append(entry)
        return entry

    def add_mine(self, name: str) -> dict:
        entry = self._entry("playlist", name)
        self.mine.append(entry)
        return entry

    def revoke(self) -> None:
        self.access.clear()
        self.refresh_tokens.clear()

    def approve(self, authorize_url: str) -> tuple[str, str]:
        query = parse_qs(urlparse(authorize_url).query)
        assert query["client_id"] == [CLIENT_ID]
        assert query["code_challenge_method"] == ["S256"]
        assert query["scope"] == [" ".join(SCOPES)]
        code = secrets.token_urlsafe(8)
        self.codes[code] = (query["redirect_uri"][0], query["code_challenge"][0])
        return query["state"][0], code

    # ----- the wire ---------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.calls.append(f"{request.method} {url.path}")
        if url.host == urlparse(ACCOUNTS_URL).hostname:
            if url.path == "/api/token":
                return self._token(parse_qs(request.content.decode()))
            return httpx.Response(404)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        expires = self.access.get(token)
        if expires is None or clock.now() >= expires:
            return httpx.Response(401, json={"error": {"status": 401, "message": "expired"}})
        path = url.path.removeprefix("/v1")
        if path == "/me":
            product = "premium" if self.premium else "free"
            return httpx.Response(200, json={"product": product, "display_name": self.display_name})
        if path == "/me/playlists":
            return httpx.Response(200, json={"items": self.mine})
        if path == "/search":
            words = url.params.get("q", "").lower().split()
            found: dict[str, dict] = {}
            for kind in ("playlist", "album", "track"):
                items = [e for e in self.catalogue if e["type"] == kind
                         and all(w in e["name"].lower() for w in words)]  # fmt: skip
                found[f"{kind}s"] = {"items": items[:3]}
            return httpx.Response(200, json=found)
        if path == "/me/player/devices":
            return httpx.Response(200, json={"devices": self.devices})
        if path == "/me/player/play":
            if not self.premium:
                return httpx.Response(403, json={"error": {"reason": "PREMIUM_REQUIRED"}})
            device = url.params.get("device_id")
            if not any(d["id"] == device for d in self.devices):
                return httpx.Response(404, json={"error": {"reason": "NO_ACTIVE_DEVICE"}})
            self.playing = {**json.loads(request.content or b"{}"), "device_id": device}
            self.paused = False
            return httpx.Response(204)
        if path == "/me/player/pause":
            if not self.premium:
                return httpx.Response(403, json={"error": {"reason": "PREMIUM_REQUIRED"}})
            if self.playing is None:
                return httpx.Response(404, json={"error": {"reason": "NO_ACTIVE_DEVICE"}})
            self.paused = True
            return httpx.Response(204)
        return httpx.Response(404)

    def _token(self, form: dict[str, list[str]]) -> httpx.Response:
        def one(name: str) -> str:
            return form.get(name, [""])[0]

        if one("client_id") != CLIENT_ID:
            return httpx.Response(400, json={"error": "invalid_client"})
        grant = one("grant_type")
        if grant == "authorization_code":
            redirect, challenge = self.codes.pop(one("code"), ("", ""))
            digest = hashlib.sha256(one("code_verifier").encode()).digest()
            if redirect != one("redirect_uri") or challenge != (
                base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            ):
                return httpx.Response(400, json={"error": "invalid_grant"})
        elif grant == "refresh_token":
            if one("refresh_token") not in self.refresh_tokens:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.refresh_tokens.discard(one("refresh_token"))
        else:
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        access, refresh = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
        self.access[access] = clock.now() + ACCESS_LIFETIME
        self.refresh_tokens.add(refresh)
        return httpx.Response(200, json={"access_token": access, "refresh_token": refresh,
                                         "expires_in": 3600, "token_type": "Bearer"})  # fmt: skip


@pytest.fixture
def fake_spotify() -> FakeSpotify:
    return FakeSpotify()
