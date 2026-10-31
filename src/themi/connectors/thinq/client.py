"""LG ThinQ: the washer and dryer, through LG's official ThinQ Connect API (30).

Its API (thinq.developer.lge.com, and LG's own SDK `thinqconnect`, checked 2026-10-31):

- A personal access token (PAT), made at connect-pat.lgthinq.com by whoever owns the
  appliances in the ThinQ app; it's valid for one country, which picks the regional
  server (`api-aic`, `api-eic` or `api-kic`.lgthinq.com).
- Every call carries the token, the country, a fresh message id, the caller's client id
  (a uuid, kept: making many clients gets calls blocked) and LG's public API key.
- `GET /devices` lists the appliances, `GET /devices/{id}/state` reads one. Answers come
  as `{"response": ...}`, errors as `{"error": {"code", "message"}}`.
- LG publishes no call limit; too many calls answer error 1306 for a while.
- Pushes (status changes, "washing is complete") come over MQTT: see `push.py`.

`ThinqClient` is only the wire. `ThinqAccount` keeps the family's one token, encrypted.
Read-only: nothing here can control an appliance.
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

API_KEY = "v6GFvkweNo7DK7yD3ylIZ9w52aKBU0eJ7wLXkSR3"  # LG's, the same for every caller
SERVICE_PHASE = "OP"
TIMEOUT = 15.0
LIMITED_FOR = timedelta(hours=1)  # LG doesn't say how long; an hour is a gentle guess

# The regional servers, by country (LG's SDK, `country.py`). Anywhere else is KIC.
AMERICAS = frozenset(
    "AG AR AW BB BO BR BS BZ CA CL CO CR CU DM DO EC GD GT GY HN HT JM KN LC MX NI PA PE PR "
    "PY SR SV TT US UY VC VE".split()
)
EUROPE = frozenset(
    "AE AF AL AM AO AT AZ BA BE BF BG BH BJ BY CD CF CG CH CI CM CV CY CZ DE DJ DK DZ EE EG "
    "ES ET FI FR GA GB GE GH GM GN GQ GR HR HU IE IL IQ IR IS IT JO KE KG KW KZ LB LR LT LU "
    "LV LY MA MD ME MK ML MR MT MU MW NE NG NL NO OM PK PL PS PT QA RO RS RU RW SA SD SE SI "
    "SK SL SN SO ST SY TD TG TN TR TZ UA UG UZ XK YE ZA ZM".split()
)
ASIA_PACIFIC = frozenset("AU BD CN HK ID IN JP KH KR LA LK MM MY NP NZ PH SG TH TW VN".split())
COUNTRIES = AMERICAS | EUROPE | ASIA_PACIFIC

# Error codes that mean the token itself is no good: linking again fixes it.
TOKEN_CODES = frozenset({"1103", "1218", "1302", "1303"})
LIMIT_CODES = frozenset({"1306"})
OFFLINE_CODES = frozenset({"1222", "1223", "2205"})
ALREADY_SUBSCRIBED = "1207"


def region_url(country: str) -> str:
    region = "aic" if country in AMERICAS else "eic" if country in EUROPE else "kic"
    return f"https://api-{region}.lgthinq.com"


@dataclass(frozen=True)
class ThinqConfig:
    base_url: str = ""  # empty: the country's regional server; set only for a fake
    transport: httpx.AsyncBaseTransport | None = field(default=None, compare=False)  # a fake
    # How pushes connect (push.py's MqttConnect); None: no pushes, polling alone.
    mqtt: Any = field(default=None, compare=False)


class ThinqError(Exception):
    """LG ThinQ couldn't be reached or said no; the job tries again later."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code  # LG's error code, when it gave one


class TokenRejected(ThinqError):
    """The token no longer works: a new one on the Family page fixes it."""


class RateLimited(ThinqError):
    def __init__(self, wait: timedelta) -> None:
        super().__init__(f"LG ThinQ asked Themi to wait {wait}")
        self.wait = wait


class DeviceOffline(ThinqError):
    """The appliance is off the network."""


@dataclass(frozen=True)
class ThinqDevice:
    device_id: str
    name: str  # the alias given in the ThinQ app
    kind: str  # "DEVICE_WASHER", "DEVICE_DRYER", "DEVICE_WASHTOWER", ...
    model: str


class ThinqClient:
    def __init__(
        self,
        token: Secret,
        country: str,
        client_id: str,
        config: ThinqConfig,
    ) -> None:
        self.country = country
        self.client_id = client_id
        self._token = token
        base = config.base_url.rstrip("/") or region_url(country)
        self._http = httpx.AsyncClient(base_url=base, transport=config.transport, timeout=TIMEOUT)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- reading ----------------------------------------------------------------------

    async def devices(self) -> list[ThinqDevice]:
        body = await self._call("GET", "/devices")
        found = []
        for device in body if isinstance(body, list) else []:
            info = device.get("deviceInfo") or {}
            found.append(
                ThinqDevice(
                    str(device["deviceId"]),
                    str(info.get("alias") or info.get("modelName") or device["deviceId"]),
                    str(info.get("deviceType") or ""),
                    str(info.get("modelName") or ""),
                )
            )
        return found

    async def state(self, device_id: str) -> Any:
        """The appliance's state report: a dict, or a list of one per drum ("location")."""
        return await self._call("GET", f"/devices/{device_id}/state")

    # ----- pushes (push.py) -------------------------------------------------------------

    async def route(self) -> str:
        """The MQTT server's host name."""
        body = await self._call("GET", "/route")
        server = str(body.get("mqttServer") or "") if isinstance(body, dict) else ""
        return server.removeprefix("mqtts://").split(":", 1)[0]

    async def register_client(self, body: dict[str, Any]) -> None:
        await self._call("POST", "/client", json=body)

    async def unregister_client(self, body: dict[str, Any]) -> None:
        await self._call("DELETE", "/client", json=body)

    async def certificate(self, body: dict[str, Any]) -> tuple[str, str]:
        """(the client certificate, PEM; the topic to subscribe to) for a signing request."""
        answer = await self._call("POST", "/client/certificate", json=body)
        result = answer.get("result", {}) if isinstance(answer, dict) else {}
        pem, topics = result.get("certificatePem"), result.get("subscriptions") or []
        if not pem or not topics:
            raise ThinqError("LG ThinQ didn't hand back a certificate for pushes")
        return str(pem), str(topics[0])

    async def subscribe(self, device_id: str) -> None:
        """Pushes for this appliance: its status changes and its notifications."""
        for path, body in (
            (f"/push/{device_id}/subscribe", None),
            (f"/event/{device_id}/subscribe", {"expire": {"unit": "HOUR", "timer": 4464}}),
        ):
            try:
                await self._call("POST", path, json=body)
            except ThinqError as exc:
                if exc.code != ALREADY_SUBSCRIBED:
                    raise

    # ----- the wire ---------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        message_id = base64.urlsafe_b64encode(uuid.uuid4().bytes)[:-2].decode()
        return {
            "Authorization": f"Bearer {self._token.reveal()}",
            "x-country": self.country,
            "x-message-id": message_id,
            "x-client-id": self.client_id,
            "x-api-key": API_KEY,
            "x-service-phase": SERVICE_PHASE,
        }

    async def _call(self, method: str, path: str, json: Any = None) -> Any:
        try:
            response = await self._http.request(method, path, headers=self._headers(), json=json)
        except httpx.HTTPError as exc:
            raise ThinqError(f"LG ThinQ couldn't be reached ({type(exc).__name__})") from exc
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        if response.is_success:
            return body.get("response")
        error = body.get("error")
        code = str(error.get("code") or "") if isinstance(error, dict) else ""
        if code in LIMIT_CODES or response.status_code == 429:
            raise RateLimited(LIMITED_FOR)
        if code in TOKEN_CODES or response.status_code == 401:
            raise TokenRejected("LG ThinQ no longer accepts this token; add a new one.")
        if code in OFFLINE_CODES:
            raise DeviceOffline("The appliance isn't connected right now.")
        log.info("LG ThinQ answered %s (%s) for %s", response.status_code, code, path)
        raise ThinqError(f"LG ThinQ answered {response.status_code} ({code or 'no code'})", code)


class ThinqAccount:
    """The family's LG ThinQ token. Admins add it; the family's appliances share it."""

    def __init__(
        self,
        db: Database,
        cipher: Cipher,
        config: ThinqConfig,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.config = config
        self._client: ThinqClient | None = None
        self._wait_until: datetime | None = None

    def linked(self) -> bool:
        return self._row() is not None

    def country(self) -> str | None:
        row = self._row()
        return str(row["country"]) if row else None

    async def link(self, member: Member, token: str, country: str) -> list[ThinqDevice]:
        """Check the token by listing the appliances, then keep it. Returns them."""
        token, country = token.strip(), country.strip().upper()
        if not token:
            raise ThinqError("Paste the personal access token from LG's site.")
        if country not in COUNTRIES:
            raise ThinqError(f"LG ThinQ doesn't know the country {country or '(blank)'}.")
        row = self._row()
        client_id = str(row["client_id"]) if row else str(uuid.uuid4())  # one, for good
        client = self._make(Secret(token), country, client_id)
        try:
            found = await client.devices()
        except BaseException:
            await client.aclose()
            raise
        self.db.execute(
            "INSERT INTO thinq_account (id, token, country, client_id, linked_by, linked_at) "
            "VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET token = excluded.token, "
            "country = excluded.country, linked_by = excluded.linked_by, "
            "linked_at = excluded.linked_at",
            (
                self.cipher.encrypt(Secret(token)),
                country,
                client_id,
                member.id,
                to_utc_iso(clock.now()),
            ),
        )
        await self._close()
        self._client, self._wait_until = client, None
        return found

    async def unlink(self) -> None:
        self.db.execute("DELETE FROM thinq_account")
        self.db.execute("DELETE FROM devices WHERE provider = 'lg_thinq'")
        await self._close()

    async def devices(self) -> list[ThinqDevice]:
        return await self._with_client(lambda c: c.devices())

    async def state(self, device_id: str) -> Any:
        return await self._with_client(lambda c: c.state(device_id))

    def client(self) -> ThinqClient:
        """The client for the stored token (pushes use it directly)."""
        if self._client is None:
            row = self._row()
            if row is None:
                raise TokenRejected("LG ThinQ isn't linked.")
            self._client = self._make(
                self.cipher.decrypt(row["token"]), str(row["country"]), str(row["client_id"])
            )
        return self._client

    def waiting(self) -> timedelta | None:
        """How much longer LG asked Themi to wait, if it did."""
        now = clock.now()
        if self._wait_until is None or now >= self._wait_until:
            return None
        return self._wait_until - now

    def held_back(self, exc: RateLimited) -> None:
        self._wait_until = clock.now() + exc.wait

    async def _with_client(self, call: Any) -> Any:
        wait = self.waiting()
        if wait is not None:
            raise RateLimited(wait)
        try:
            return await call(self.client())
        except RateLimited as exc:
            self.held_back(exc)
            raise

    def _make(self, token: Secret, country: str, client_id: str) -> ThinqClient:
        return ThinqClient(token, country, client_id, self.config)

    def _row(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM thinq_account WHERE id = 1")

    async def _close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
