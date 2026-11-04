"""Tuya: the pet feeders, through Tuya's cloud API, where the SmartLife app's devices live (32).

Its API (developer.tuya.com, checked 2026-11-04):

- A cloud project on Tuya's IoT platform has an Access ID and Access Secret, and lives in
  one data centre (`openapi.tuyaus.com` for the western Americas, ...). The SmartLife app
  account is linked to the project by scanning its QR code in the app.
- Every call is signed: HMAC-SHA256 with the secret over the Access ID, the access token
  (none when asking for one), a 13-digit millisecond time, a nonce, and a string of the
  method, the body's SHA-256, the signed headers and the path with its sorted query.
  `sign` keeps Tuya's two published examples (tests pin them).
- `GET /v1.0/token?grant_type=1` gives a project token (about two hours);
  `GET /v1.0/token/{refresh_token}` renews it.
- `GET /v1.0/iot-01/associated-users/devices` lists the linked app accounts' devices;
  `/v1.0/devices/{id}/status` and `/specifications` read one; `/logs` (type 7, a data
  point's reports) gives its feeding log.
- Answers come as `{"success": true, "result": ...}` or `{"success": false, "code", "msg"}`.
  The trial plan lapses unless it's extended on Tuya's site (28841002 and kin).

`TuyaClient` is only the wire. `TuyaAccount` keeps the project's secret, encrypted.
Read-only: nothing here sends a feeder a command.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
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

TIMEOUT = 15.0
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
TOKEN_EARLY = timedelta(minutes=5)  # renewed this long before Tuya says it ends
LIMITED_FOR = timedelta(minutes=10)  # Tuya doesn't say how long; a gentle guess
PAGE = 100

# The data centres, by the name the cloud project shows (Tuya's "endpoints" page).
REGIONS = {
    "us": ("Western America", "https://openapi.tuyaus.com"),
    "us-e": ("Eastern America", "https://openapi-ueaz.tuyaus.com"),
    "eu": ("Central Europe", "https://openapi.tuyaeu.com"),
    "eu-w": ("Western Europe", "https://openapi-weaz.tuyaeu.com"),
    "cn": ("China", "https://openapi.tuyacn.com"),
    "in": ("India", "https://openapi.tuyain.com"),
}

# Tuya's error codes (its global error code page, checked 2026-11-04).
TOKEN_CODES = frozenset({1010, 1011, 1012, 1400})  # get a new token and try once more
KEY_CODES = frozenset({1001, 1004, 1005})  # the Access ID or secret is wrong
PLAN_CODES = frozenset(range(28841001, 28841007)) | frozenset(range(28841101, 28841107))
LIMIT_CODES = frozenset({1110, 1113, 1199})
OFFLINE_CODES = frozenset({2001, 40000801})


def string_to_sign(
    method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None
) -> str:
    """Tuya's stringToSign. `path` carries its query, sorted and not encoded (`url_for`)."""
    digest = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
    signed = "".join(f"{k}:{v}\n" for k, v in (headers or {}).items())
    return f"{method.upper()}\n{digest}\n{signed}\n{path}"


def sign(
    access_id: str,
    secret: str,
    t: str,
    nonce: str,
    to_sign: str,
    access_token: str = "",
) -> str:
    message = f"{access_id}{access_token}{t}{nonce}{to_sign}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest().upper()


def url_for(path: str, params: dict[str, Any] | None = None) -> str:
    """The path with its query sorted by key and not encoded, as Tuya signs it (it's sent
    encoded, and Tuya decodes it before checking)."""
    if not params:
        return path
    return f"{path}?{'&'.join(f'{k}={v}' for k, v in sorted(params.items()))}"


@dataclass(frozen=True)
class TuyaConfig:
    base_url: str = ""  # empty: the project's data centre; set only for a fake
    transport: httpx.AsyncBaseTransport | None = field(default=None, compare=False)  # a fake


class TuyaError(Exception):
    """Tuya couldn't be reached or said no; the job tries again later."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code  # Tuya's error code, when it gave one


class KeyRejected(TuyaError):
    """The Access ID or secret is wrong, or the project's plan has lapsed: linking again
    (after extending the plan, for that) fixes it."""


class RateLimited(TuyaError):
    def __init__(self, wait: timedelta) -> None:
        super().__init__(f"Tuya asked Themi to wait {wait}")
        self.wait = wait


class DeviceOffline(TuyaError):
    """The device is off the network."""


@dataclass(frozen=True)
class TuyaDevice:
    device_id: str
    name: str  # as named in the SmartLife app
    category: str  # Tuya's category code: "cwwsq" is a pet feeder
    product_id: str  # the model, as Tuya knows it
    product_name: str


class TuyaClient:
    def __init__(self, access_id: str, secret: Secret, region: str, config: TuyaConfig) -> None:
        self.access_id = access_id
        self._secret = secret
        base = config.base_url.rstrip("/") or REGIONS[region][1]
        self._http = httpx.AsyncClient(base_url=base, transport=config.transport, timeout=TIMEOUT)
        self._token = ""
        self._refresh = ""
        self._token_until: datetime | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- reading ----------------------------------------------------------------------

    async def devices(self) -> list[TuyaDevice]:
        """Every device on the linked SmartLife accounts."""
        found: list[TuyaDevice] = []
        params: dict[str, Any] = {"size": PAGE}
        while True:
            page = await self._call("GET", "/v1.0/iot-01/associated-users/devices", params)
            page = page if isinstance(page, dict) else {}
            for device in page.get("devices") or []:
                found.append(
                    TuyaDevice(
                        str(device["id"]),
                        str(device.get("name") or device.get("product_name") or device["id"]),
                        str(device.get("category") or ""),
                        str(device.get("product_id") or ""),
                        str(device.get("product_name") or ""),
                    )
                )
            if not page.get("has_more") or not page.get("last_row_key"):
                return found
            params = {"size": PAGE, "last_row_key": page["last_row_key"]}

    async def status(self, device_id: str) -> list[dict[str, Any]]:
        """Its data points now: [{"code": ..., "value": ...}]."""
        result = await self._call("GET", f"/v1.0/devices/{device_id}/status")
        return list(result) if isinstance(result, list) else []

    async def specification(self, device_id: str) -> dict[str, Any]:
        """Its data points' types and ranges (`status`: [{code, type, values}], where
        `values` is JSON text: an enum's `range`, a bitmap's `label`, a number's bounds)."""
        result = await self._call("GET", f"/v1.0/devices/{device_id}/specifications")
        return dict(result) if isinstance(result, dict) else {}

    async def reports(
        self, device_id: str, codes: list[str], since: datetime, until: datetime
    ) -> list[dict[str, Any]]:
        """What it reported for these data points between two times (its log, type 7):
        [{"code", "value", "event_time" (ms)}], oldest first."""
        logs: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "type": 7,
            "codes": ",".join(codes),
            "start_time": _ms(since),
            "end_time": _ms(until),
            "size": PAGE,
        }
        while True:
            page = await self._call("GET", f"/v1.0/devices/{device_id}/logs", params)
            page = page if isinstance(page, dict) else {}
            logs.extend(page.get("logs") or [])
            if not page.get("has_next") or not page.get("current_row_key"):
                return sorted(logs, key=lambda entry: int(entry.get("event_time") or 0))
            params = {**params, "start_row_key": page["current_row_key"]}

    # ----- the wire ---------------------------------------------------------------------

    async def _call(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        await self._ensure_token()
        try:
            return await self._send(method, path, params, self._token)
        except _TokenGone:
            self._token = ""
            await self._ensure_token()
            return await self._send(method, path, params, self._token)

    async def _ensure_token(self) -> None:
        now = clock.now()
        if self._token and self._token_until is not None and now < self._token_until:
            return
        result: Any = None
        if self._refresh:
            try:
                result = await self._send("GET", f"/v1.0/token/{self._refresh}", None, "")
            except TuyaError:
                result = None  # a refresh that's no good: start again
        if not isinstance(result, dict):
            result = await self._send("GET", "/v1.0/token", {"grant_type": 1}, "")
        if not isinstance(result, dict) or not result.get("access_token"):
            raise TuyaError("Tuya didn't hand back a token")
        self._token = str(result["access_token"])
        self._refresh = str(result.get("refresh_token") or "")
        lasts = timedelta(seconds=int(result.get("expire_time") or 0))
        self._token_until = now + max(lasts - TOKEN_EARLY, timedelta(0))

    async def _send(self, method: str, path: str, params: dict[str, Any] | None, token: str) -> Any:
        t = str(_ms(clock.now()))
        nonce = secrets.token_hex(16)
        headers = {
            "client_id": self.access_id,
            "t": t,
            "nonce": nonce,
            "sign_method": "HMAC-SHA256",
            "sign": sign(
                self.access_id,
                self._secret.reveal(),
                t,
                nonce,
                string_to_sign(method, url_for(path, params)),
                token,
            ),
        }
        if token:
            headers["access_token"] = token
        try:
            response = await self._http.request(
                method,
                path,
                params=sorted((k, str(v)) for k, v in (params or {}).items()),
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise TuyaError(f"Tuya couldn't be reached ({type(exc).__name__})") from exc
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        if response.is_success and body.get("success"):
            return body.get("result")
        code = _code(body.get("code"))
        if token and code in TOKEN_CODES:
            raise _TokenGone(code)
        if code in LIMIT_CODES or response.status_code == 429:
            raise RateLimited(LIMITED_FOR)
        if code in KEY_CODES:
            raise KeyRejected(
                "Tuya doesn't accept this Access ID and secret; check them in the cloud "
                "project and link again.",
                code,
            )
        if code in PLAN_CODES:
            raise KeyRejected(
                "Tuya's cloud project can't read devices any more (its plan or an API "
                "service lapsed); extend it on Tuya's site, then link again.",
                code,
            )
        if code in OFFLINE_CODES:
            raise DeviceOffline("The device isn't connected right now.", code)
        log.info("Tuya answered %s (%s) for %s", response.status_code, code, path)
        raise TuyaError(f"Tuya answered {response.status_code} ({code or 'no code'})", code)


class _TokenGone(TuyaError):
    def __init__(self, code: int) -> None:
        super().__init__("Tuya's token ran out", code)


class TuyaAccount:
    """The family's Tuya cloud project. Admins link it; the feeders share it."""

    def __init__(self, db: Database, cipher: Cipher, config: TuyaConfig) -> None:
        self.db = db
        self.cipher = cipher
        self.config = config
        self._client: TuyaClient | None = None
        self._wait_until: datetime | None = None

    def linked(self) -> bool:
        return self._row() is not None

    def access_id(self) -> str | None:
        row = self._row()
        return str(row["access_id"]) if row else None

    def region(self) -> str | None:
        row = self._row()
        return str(row["region"]) if row else None

    def problem(self) -> str | None:
        """Why the feeders can't be read, when the project stopped working."""
        row = self._row()
        return str(row["problem"]) if row and row["problem"] else None

    async def link(
        self, member: Member, access_id: str, secret: str, region: str
    ) -> list[TuyaDevice]:
        """Check the keys by listing the devices, then keep them. Returns the devices."""
        access_id, secret, region = access_id.strip(), secret.strip(), region.strip()
        if not access_id or not secret:
            raise TuyaError("Paste the cloud project's Access ID and Access Secret.")
        if region not in REGIONS:
            raise TuyaError(f"Tuya has no data centre called {region or '(blank)'}.")
        client = TuyaClient(access_id, Secret(secret), region, self.config)
        try:
            found = await client.devices()
        except BaseException:
            await client.aclose()
            raise
        self.db.execute(
            "INSERT INTO tuya_account (id, access_id, secret, region, problem, linked_by, "
            "linked_at) VALUES (1, ?, ?, ?, NULL, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "access_id = excluded.access_id, secret = excluded.secret, region = excluded.region, "
            "problem = NULL, linked_by = excluded.linked_by, linked_at = excluded.linked_at",
            (
                access_id,
                self.cipher.encrypt(Secret(secret)),
                region,
                member.id,
                to_utc_iso(clock.now()),
            ),
        )
        await self.close()
        self._client, self._wait_until = client, None
        return found

    async def unlink(self) -> None:
        self.db.execute("DELETE FROM tuya_account")
        self.db.execute("DELETE FROM devices WHERE provider = 'tuya'")
        await self.close()

    async def devices(self) -> list[TuyaDevice]:
        return await self._with_client(lambda c: c.devices())

    async def status(self, device_id: str) -> list[dict[str, Any]]:
        return await self._with_client(lambda c: c.status(device_id))

    async def specification(self, device_id: str) -> dict[str, Any]:
        return await self._with_client(lambda c: c.specification(device_id))

    async def reports(
        self, device_id: str, codes: list[str], since: datetime, until: datetime
    ) -> list[dict[str, Any]]:
        return await self._with_client(lambda c: c.reports(device_id, codes, since, until))

    def broken(self, why: str) -> bool:
        """The keys stopped working: kept as the problem until linked again. True the first
        time (so an admin hears once)."""
        row = self._row()
        if row is None or row["problem"]:
            return False
        self.db.execute("UPDATE tuya_account SET problem = ? WHERE id = 1", (why,))
        return True

    def waiting(self) -> timedelta | None:
        """How much longer Tuya asked Themi to wait, if it did."""
        now = clock.now()
        if self._wait_until is None or now >= self._wait_until:
            return None
        return self._wait_until - now

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _client_for_row(self) -> TuyaClient:
        if self._client is None:
            row = self._row()
            if row is None:
                raise KeyRejected("Tuya isn't linked.")
            if row["problem"]:
                raise KeyRejected(str(row["problem"]))
            self._client = TuyaClient(
                str(row["access_id"]),
                self.cipher.decrypt(row["secret"]),
                str(row["region"]),
                self.config,
            )
        return self._client

    async def _with_client(self, call: Any) -> Any:
        wait = self.waiting()
        if wait is not None:
            raise RateLimited(wait)
        try:
            return await call(self._client_for_row())
        except RateLimited as exc:
            self._wait_until = clock.now() + exc.wait
            raise

    def _row(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM tuya_account WHERE id = 1")


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _code(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
