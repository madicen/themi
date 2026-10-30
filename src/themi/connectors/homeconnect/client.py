"""Home Connect: the cloud API of Bosch, Siemens and the other BSH appliances (H1).

Its official API (https://api-docs.home-connect.com, checked 2026-10-30):

- OAuth 2 authorization code flow at `/security/oauth/authorize`, with the
  client secret at `/security/oauth/token`. Access tokens last 24 hours;
  a refresh may hand back a new refresh token, which then replaces the old.
- `IdentifyAppliance` is needed for every call; `Dishwasher-Monitor` reads the
  dishwasher's state, and nothing here can control it.
- 1000 requests a day per client and user, 10 token refreshes a minute and
  100 a day. Past a limit it answers 429 with a Retry-After; the caller waits.
- An appliance that's off the network answers 409.

`HomeConnectClient` is only the wire. `HomeConnectAccount` keeps the family's
one sign-in: the link's state, the refresh token (encrypted), and the access
token in memory.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

BASE_URL = "https://api.home-connect.com"
# Home Connect hands its sign-in on to SingleKey ID, so links pass through here too.
SIGN_IN_URL = "https://singlekey-id.com"
SCOPES = ("IdentifyAppliance", "Dishwasher-Monitor")
MEDIA_TYPE = "application/vnd.bsh.sdk.v1+json"
OPERATION_STATE = "BSH.Common.Status.OperationState"
STATE_PREFIX = "BSH.Common.EnumType.OperationState."
RUN = "Run"
STATE_TTL = timedelta(minutes=10)
EARLY = timedelta(minutes=5)  # refresh an access token this long before it runs out
TIMEOUT = 20.0


@dataclass(frozen=True)
class HomeConnectConfig:
    client_id: str
    client_secret: Secret = field(repr=False)
    base_url: str = BASE_URL
    sign_in_url: str = SIGN_IN_URL


class HomeConnectError(Exception):
    """Home Connect couldn't be reached or said no; the job tries again later."""


class LinkRevoked(HomeConnectError):
    """The sign-in no longer works: linking again on the Family page fixes it."""


class RateLimited(HomeConnectError):
    def __init__(self, wait: timedelta) -> None:
        super().__init__(f"Home Connect asked Themi to wait {wait}")
        self.wait = wait


class ApplianceOffline(HomeConnectError):
    """The appliance is off, or off the network."""


@dataclass(frozen=True)
class Tokens:
    access: Secret = field(repr=False)
    expires_at: datetime
    refresh: Secret | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Appliance:
    ha_id: str
    name: str
    kind: str  # "Dishwasher", "Washer", "Dryer", ...
    brand: str
    connected: bool


class HomeConnectClient:
    def __init__(
        self, config: HomeConnectConfig, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"), transport=transport, timeout=TIMEOUT
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- signing in -------------------------------------------------------------------

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
        }
        return f"{self.config.base_url.rstrip('/')}/security/oauth/authorize?{urlencode(params)}"

    async def exchange(self, code: str, redirect_uri: str) -> Tokens:
        return await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret.reveal(),
            }
        )

    async def refresh(self, refresh_token: Secret) -> Tokens:
        return await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.reveal(),
                "client_secret": self.config.client_secret.reveal(),
            }
        )

    # ----- reading ----------------------------------------------------------------------

    async def appliances(self, access: Secret) -> list[Appliance]:
        body = await self._get("/api/homeappliances", access)
        return [
            Appliance(
                str(a["haId"]),
                str(a.get("name") or a.get("type") or a["haId"]),
                str(a.get("type") or ""),
                str(a.get("brand") or ""),
                bool(a.get("connected")),
            )
            for a in body.get("data", {}).get("homeappliances", [])
        ]

    async def operation_state(self, access: Secret, ha_id: str) -> str:
        """Its operation state's last word: "Ready", "Run", "Finished", "Inactive"..."""
        body = await self._get(f"/api/homeappliances/{ha_id}/status/{OPERATION_STATE}", access)
        value = str(body.get("data", {}).get("value") or "")
        return value.removeprefix(STATE_PREFIX)

    # ----- the wire ---------------------------------------------------------------------

    async def _token(self, form: dict[str, str]) -> Tokens:
        try:
            response = await self._http.post("/security/oauth/token", data=form)
        except httpx.HTTPError as exc:
            raise HomeConnectError(
                f"Home Connect couldn't be reached ({type(exc).__name__})"
            ) from exc
        self._raise_for_limits(response)
        body = _json(response)
        if response.status_code in (400, 401):
            log.info("Home Connect refused a token request: %s", body.get("error", ""))
            raise LinkRevoked("Home Connect no longer accepts this sign-in; link it again.")
        if response.status_code != 200 or not body.get("access_token"):
            raise HomeConnectError(f"Home Connect's sign-in answered {response.status_code}")
        refresh = body.get("refresh_token")
        return Tokens(
            Secret(str(body["access_token"])),
            clock.now() + timedelta(seconds=int(body.get("expires_in", 86400))),
            Secret(str(refresh)) if refresh else None,
        )

    async def _get(self, path: str, access: Secret) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access.reveal()}", "Accept": MEDIA_TYPE}
        try:
            response = await self._http.get(path, headers=headers)
        except httpx.HTTPError as exc:
            raise HomeConnectError(
                f"Home Connect couldn't be reached ({type(exc).__name__})"
            ) from exc
        self._raise_for_limits(response)
        if response.status_code == 401:
            raise LinkRevoked("Home Connect turned down the access token.")
        if response.status_code == 409:
            raise ApplianceOffline("The appliance isn't connected right now.")
        if response.status_code != 200:
            raise HomeConnectError(f"Home Connect answered {response.status_code} for {path}")
        return _json(response)

    @staticmethod
    def _raise_for_limits(response: httpx.Response) -> None:
        if response.status_code != 429:
            return
        after = response.headers.get("Retry-After", "")
        raise RateLimited(timedelta(seconds=int(after) if after.isdigit() else 3600))


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json() if response.content else {}
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


class HomeConnectAccount:
    """The family's Home Connect sign-in. Admins link it; its appliances share it."""

    def __init__(self, db: Database, cipher: Cipher, client: HomeConnectClient) -> None:
        self.db = db
        self.cipher = cipher
        self.client = client
        self._access: Tokens | None = None
        self._wait_until: datetime | None = None

    @staticmethod
    def redirect_uri(base_url: str) -> str:
        return f"{base_url.rstrip('/')}/auth/home-connect/callback"

    def linked(self) -> bool:
        return self.db.one("SELECT 1 FROM home_connect_account WHERE id = 1") is not None

    def authorization_url(self, member: Member, redirect_uri: str) -> str:
        state = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO home_connect_states (state_hash, member_id, expires_at) VALUES (?, ?, ?)",
            (_hash(state), member.id, to_utc_iso(clock.now() + STATE_TTL)),
        )
        return self.client.authorize_url(state, redirect_uri)

    async def complete(self, state: str, code: str, redirect_uri: str) -> int:
        """Finish a link from Home Connect's callback; returns the member who started it.
        The state works once."""
        now = clock.now()
        with self.db.transaction():
            row = self.db.one(
                "SELECT * FROM home_connect_states WHERE state_hash = ?", (_hash(state),)
            )
            self.db.execute(
                "DELETE FROM home_connect_states WHERE state_hash = ? OR expires_at <= ?",
                (_hash(state), to_utc_iso(now)),
            )
        if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
            raise HomeConnectError("That link has expired or was already used; start again.")
        tokens = await self.client.exchange(code, redirect_uri)
        if tokens.refresh is None:
            raise HomeConnectError("Home Connect didn't send a refresh token; try linking again.")
        self.db.execute(
            "INSERT INTO home_connect_account (id, refresh_token, linked_by, linked_at) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "refresh_token = excluded.refresh_token, linked_by = excluded.linked_by, "
            "linked_at = excluded.linked_at",
            (self.cipher.encrypt(tokens.refresh), row["member_id"], to_utc_iso(now)),
        )
        self._access, self._wait_until = tokens, None
        return int(row["member_id"])

    def unlink(self) -> None:
        self.db.execute("DELETE FROM home_connect_account")
        self.db.execute("DELETE FROM devices WHERE provider = 'home_connect'")
        self._access = None

    async def appliances(self) -> list[Appliance]:
        return await self._with_token(self.client.appliances)

    async def operation_state(self, ha_id: str) -> str:
        return await self._with_token(lambda access: self.client.operation_state(access, ha_id))

    async def _with_token(self, call: Any) -> Any:
        now = clock.now()
        if self._wait_until is not None and now < self._wait_until:
            raise RateLimited(self._wait_until - now)
        try:
            for attempt in range(2):
                access = await self._token(fresh=attempt > 0)
                try:
                    return await call(access)
                except LinkRevoked:
                    if attempt:
                        raise
        except RateLimited as exc:
            self._wait_until = now + exc.wait
            raise
        raise AssertionError("unreachable")  # pragma: no cover

    async def _token(self, *, fresh: bool = False) -> Secret:
        if not fresh and self._access and clock.now() < self._access.expires_at - EARLY:
            return self._access.access
        row = self.db.one("SELECT refresh_token FROM home_connect_account WHERE id = 1")
        if row is None:
            raise LinkRevoked("Home Connect isn't linked.")
        tokens = await self.client.refresh(self.cipher.decrypt(row["refresh_token"]))
        if tokens.refresh is not None:  # a new one replaces the old
            self.db.execute(
                "UPDATE home_connect_account SET refresh_token = ? WHERE id = 1",
                (self.cipher.encrypt(tokens.refresh),),
            )
        self._access = tokens
        return tokens.access
