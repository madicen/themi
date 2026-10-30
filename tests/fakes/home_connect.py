"""A fake of Home Connect's API (H1), behind an httpx transport.

    fake_home_connect.add_appliance("BOSCH-SMV-1", "Dishwasher")
    fake_home_connect.set_state("BOSCH-SMV-1", "Run")
    fake_home_connect.approve(authorize_url)   # the person says yes: (state, code)
    fake_home_connect.offline("BOSCH-SMV-1")  # the next status read answers 409
    fake_home_connect.limit(times=1)           # the next call answers 429
    fake_home_connect.revoke()                 # every token stops working

Tokens are checked: an expired or unknown access token answers 401, and each
refresh hands back a new refresh token (the old one stops working).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from themi import clock
from themi.connectors.homeconnect import HomeConnectClient, HomeConnectConfig
from themi.connectors.homeconnect.client import OPERATION_STATE, STATE_PREFIX
from themi.storage.secrets import Secret

BASE_URL = "https://home-connect.test"
CLIENT_ID = "themi-home-connect"
CLIENT_SECRET = "home-connect-secret"
ACCESS_LIFETIME = timedelta(hours=24)


class FakeHomeConnect:
    def __init__(self) -> None:
        self.appliances: dict[str, dict] = {}
        self.states: dict[str, str] = {}
        self.codes: dict[str, str] = {}  # code -> redirect_uri
        self.access: dict[str, datetime] = {}  # token -> expires
        self.refresh_tokens: set[str] = set()
        self.calls: list[str] = []
        self._offline: set[str] = set()
        self._limited = 0
        self.transport = httpx.MockTransport(self._handle)

    def client(self) -> HomeConnectClient:
        config = HomeConnectConfig(CLIENT_ID, Secret(CLIENT_SECRET), BASE_URL)
        return HomeConnectClient(config, transport=self.transport)

    # ----- the test's controls ----------------------------------------------------------

    def add_appliance(self, ha_id: str, kind: str, name: str = "", brand: str = "Bosch") -> None:
        self.appliances[ha_id] = {
            "haId": ha_id,
            "name": name or kind,
            "type": kind,
            "brand": brand,
            "vib": "SMV4",
            "connected": True,
        }
        self.states[ha_id] = "Ready"

    def set_state(self, ha_id: str, state: str) -> None:
        self.states[ha_id] = state
        self._offline.discard(ha_id)

    def offline(self, ha_id: str) -> None:
        self._offline.add(ha_id)

    def limit(self, times: int = 1) -> None:
        self._limited += times

    def revoke(self) -> None:
        self.access.clear()
        self.refresh_tokens.clear()

    def approve(self, authorize_url: str) -> tuple[str, str]:
        """The person signs in and says yes: the (state, code) sent back to Themi."""
        query = parse_qs(urlparse(authorize_url).query)
        assert query["client_id"] == [CLIENT_ID]
        assert query["scope"] == ["IdentifyAppliance Dishwasher-Monitor"]
        code = secrets.token_urlsafe(8)
        self.codes[code] = query["redirect_uri"][0]
        return query["state"][0], code

    # ----- the wire ---------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self._limited:
            self._limited -= 1
            return httpx.Response(429, headers={"Retry-After": "600"})
        if path == "/security/oauth/token":
            return self._token(parse_qs(request.content.decode()))
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        expires = self.access.get(token)
        if expires is None or clock.now() >= expires:
            return httpx.Response(401, json={"error": {"key": "invalid_token"}})
        if path == "/api/homeappliances":
            return httpx.Response(
                200, json={"data": {"homeappliances": list(self.appliances.values())}}
            )
        parts = path.split("/")
        if len(parts) == 6 and parts[4] == "status" and parts[5] == OPERATION_STATE:
            ha_id = parts[3]
            if ha_id not in self.appliances:
                return httpx.Response(404)
            if ha_id in self._offline:
                return httpx.Response(
                    409,
                    json={
                        "error": {"key": "SDK.Error.HomeAppliance.Connection.Initialization.Failed"}
                    },
                )
            value = f"{STATE_PREFIX}{self.states[ha_id]}"
            return httpx.Response(200, json={"data": {"key": OPERATION_STATE, "value": value}})
        return httpx.Response(404)

    def _token(self, form: dict[str, list[str]]) -> httpx.Response:
        def one(name: str) -> str:
            return form.get(name, [""])[0]

        if one("client_secret") != CLIENT_SECRET:
            return httpx.Response(401, json={"error": "unauthorized_client"})
        grant = one("grant_type")
        if grant == "authorization_code":
            if self.codes.pop(one("code"), None) != one("redirect_uri"):
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
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "refresh_token": refresh,
                "expires_in": int(ACCESS_LIFETIME.total_seconds()),
                "scope": "IdentifyAppliance Dishwasher-Monitor",
                "token_type": "Bearer",
            },
        )


@pytest.fixture
def fake_home_connect() -> FakeHomeConnect:
    return FakeHomeConnect()
