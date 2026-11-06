"""CatGenie: the litter box, through the CatGenie app's own cloud (PetNovations) (CG1a).

There's no official API. This follows the community client kclif9/catgenieapi (`catgenie`
0.1.6 on PyPI, MIT), which was read for this, never run or depended on
(github.com/kclif9/catgenieapi, checked 2026-11-04):

- Everything is at `https://iot.petnovations.com`. Sign-in is a phone number and a code
  sent by text: `ums/v1/users/generateLoginCode/v2`, then
  `ums/v1/users/loginByPhoneNumber/v2`. The phone goes in a `str1` field: "+<number>-<seven
  random characters with an X put in>", AES-CBC with a key from the app and a zero IV.
- Signing in gives a refresh token (about 10 years) and an access token (30 minutes),
  renewed at `facade/v1/mobile-user/refreshToken/v2`.
- Every request carries `x-pm-en-dec` (the time, AES-CBC the same way), `x-pm-en-ver` and
  `x-render-t` (the path and the time). The app also signs with HMACs; the server doesn't
  check them, per the package, so Themi doesn't send them.
- The edge drops a request whose TLS doesn't look like a phone's: it answers 200 with an
  empty body. So the real wire is curl_cffi, passing as Chrome on Android. Tests and
  `make dev` use an httpx transport instead (`CatGenieConfig.transport`).
- `GET device/device/v2` lists the devices with all they report (`thingList`);
  `GET notification/v1/push/user` the alerts the app pushed.

`CatGenieClient` is only the wire. `CatGenieAccount` keeps the refresh token, encrypted.
Read-only: nothing here starts, stops or changes the litter box.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher as AesCipher
from cryptography.hazmat.primitives.ciphers import algorithms, modes

from themi import clock
from themi.accounts import Member
from themi.http import tls
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

BASE_URL = "https://iot.petnovations.com"
IMPERSONATE = "chrome131_android"  # curl_cffi's closest match to the app's okhttp
TIMEOUT = 20.0
TOKEN_LASTS = timedelta(minutes=30)  # when the answer doesn't say
TOKEN_EARLY = timedelta(minutes=2)  # renewed this long before it ends
# The app's own headers (the package's packet capture).
HEADERS = {
    "User-Agent": "okhttp/4.9.2",
    "accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip",
    "accept-language": "en-US",
    "Content-Type": "application/json",
    "Connection": "Keep-Alive",
}
# The app's AES key, as the package rebuilt it from the app's code.
AES_KEY = b"P-3Rp6d81Kw9a3Z-CyvWH0WXRieyITk6"
# The app's alphabet for its random parts (with its T twice, and no Y or j).
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXTZabcdefghiklmnopqrstuvwxyz"

SEND_CODE = "ums/v1/users/generateLoginCode/v2"
SIGN_IN = "ums/v1/users/loginByPhoneNumber/v2"
REFRESH = "facade/v1/mobile-user/refreshToken/v2"
DEVICES = "device/device/v2"
NOTIFICATIONS = "notification/v1/push/user"


class CatGenieError(Exception):
    """PetNovations couldn't be reached or said no; the job tries again later."""


class SignInLost(CatGenieError):
    """The sign-in stopped working (the refresh token was refused): linking again fixes it."""


class BadCode(CatGenieError):
    """The texted code was wrong, used, or too old."""


@dataclass(frozen=True)
class CatGenieConfig:
    base_url: str = BASE_URL
    transport: httpx.AsyncBaseTransport | None = field(default=None, compare=False)  # a fake


@dataclass(frozen=True)
class Answer:
    status: int
    body: bytes


class Wire(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        params: dict[str, str] | None,
    ) -> Answer: ...

    async def aclose(self) -> None: ...


class CurlWire:
    """The real wire: curl_cffi, so the TLS looks like a phone's."""

    def __init__(self) -> None:
        from curl_cffi.requests import AsyncSession

        self._session = AsyncSession(impersonate=IMPERSONATE, timeout=TIMEOUT)

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        params: dict[str, str] | None,
    ) -> Answer:
        from curl_cffi import CurlError
        from curl_cffi.requests import RequestsError

        try:
            response = await self._session.request(
                method,  # pyright: ignore[reportArgumentType]
                url,
                headers=headers,
                data=body,
                params=params,
                impersonate=IMPERSONATE,
                default_headers=False,
            )
        except (CurlError, RequestsError) as exc:
            raise CatGenieError(f"PetNovations couldn't be reached ({type(exc).__name__})") from exc
        return Answer(response.status_code, response.content)

    async def aclose(self) -> None:
        await self._session.close()


class HttpxWire:
    """A wire over an httpx transport: the fake's, for tests and `make dev`."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._http = httpx.AsyncClient(verify=tls(), transport=transport, timeout=TIMEOUT)

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        params: dict[str, str] | None,
    ) -> Answer:
        try:
            response = await self._http.request(
                method, url, headers=headers, content=body, params=params
            )
        except httpx.HTTPError as exc:
            raise CatGenieError(f"PetNovations couldn't be reached ({type(exc).__name__})") from exc
        return Answer(response.status_code, response.content)

    async def aclose(self) -> None:
        await self._http.aclose()


def wire_for(config: CatGenieConfig) -> Wire:
    return HttpxWire(config.transport) if config.transport is not None else CurlWire()


# ----- the app's encodings ----------------------------------------------------------------


def _aes(text: str) -> str:
    padder = padding.PKCS7(128).padder()
    data = padder.update(text.encode()) + padder.finalize()
    encryptor = AesCipher(algorithms.AES(AES_KEY), modes.CBC(b"\x00" * 16)).encryptor()
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()


def unaes(text: str) -> str:
    """The other way, for the fake (and its tests)."""
    decryptor = AesCipher(algorithms.AES(AES_KEY), modes.CBC(b"\x00" * 16)).decryptor()
    data = decryptor.update(base64.b64decode(text)) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(data) + unpadder.finalize()).decode()


def _random_part(marker: str) -> str:
    """Seven of the app's random characters, with `marker` put in somewhere."""
    chars = "".join(secrets.choice(ALPHABET) for _ in range(7))
    at = secrets.randbelow(len(chars) + 1)
    return chars[:at] + marker + chars[at:]


def phone_field(phone: str) -> str:
    """`str1`: the phone number, as the app hides it."""
    return _aes(f"{phone}-{_random_part('X')}")


def time_field(ms: int) -> str:
    """`x-pm-en-dec`: the time, as the app hides it (an odd hundred is moved on by one)."""
    if (ms // 100) % 2:
        ms += 100
    return _aes(f"{ms}-{_random_part('Z')}")


def render_path(path: str) -> str:
    """The path as `x-render-t` names it: without `facade/v1/`."""
    path = path.lstrip("/")
    return path.removeprefix("facade/v1/")


def normal_phone(phone: str) -> str:
    """ "+15551234567" from what someone typed. Ten digits are taken as a US number."""
    digits = re.sub(r"\D", "", phone)
    if phone.strip().startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    raise CatGenieError(
        "Enter the phone number the CatGenie app signs in with, with its country code "
        "(+1 555 123 4567)."
    )


def _expiry(value: Any, now: datetime) -> datetime:
    """An answer's `expiration`: milliseconds since 1970 (as text or a number), or nothing."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        ms = 0
    if ms <= 0:
        return now + TOKEN_LASTS
    seconds = ms / 1000 if ms > 1_000_000_000_000 else ms
    return datetime.fromtimestamp(seconds, UTC)


# ----- the client ---------------------------------------------------------------------------


class CatGenieClient:
    def __init__(self, config: CatGenieConfig, refresh_token: Secret | None = None) -> None:
        self.config = config
        self._wire = wire_for(config)
        self._base = config.base_url.rstrip("/")
        self.refresh_token = refresh_token  # changed when PetNovations hands out a new one
        self._token = ""
        self._token_until: datetime | None = None

    async def aclose(self) -> None:
        await self._wire.aclose()

    # ----- signing in -------------------------------------------------------------------

    async def send_code(self, phone: str) -> None:
        """PetNovations texts a code to the phone. It answers 200 whatever happens."""
        answer = await self._send("POST", SEND_CODE, body={"str1": phone_field(phone)})
        if not 200 <= answer.status < 300:
            raise CatGenieError(f"PetNovations answered {answer.status} when asked for a code")

    async def sign_in(self, phone: str, code: str) -> None:
        answer = await self._send("POST", SIGN_IN, body={"str1": phone_field(phone), "code": code})
        data = _json(answer)
        if answer.status != 200 or not isinstance(data, dict) or not data.get("refreshToken"):
            raise BadCode(
                "PetNovations didn't take that code: it may be mistyped, used already or too "
                "old. Ask for a new one."
            )
        self.refresh_token = Secret(str(data["refreshToken"]))
        self._token = str(data.get("accessToken") or "")
        self._token_until = _expiry(data.get("expiration"), clock.now()) - TOKEN_EARLY

    # ----- reading ----------------------------------------------------------------------

    async def devices(self) -> list[dict[str, Any]]:
        """Every litter box on the account, with all it reports, as PetNovations sends it."""
        data = await self._call(
            "GET", DEVICES, params={"useFleetIndexAndGetRealConnectivity": "true"}
        )
        things = data.get("thingList") if isinstance(data, dict) else None
        if not isinstance(things, list):
            raise CatGenieError("PetNovations sent no device list")
        return [t for t in things if isinstance(t, dict) and t.get("manufacturerId")]

    async def notifications(self) -> list[dict[str, Any]]:
        """The alerts the app was sent: [{id, creationTime, data (JSON text)}]."""
        data = await self._call("GET", NOTIFICATIONS)
        found = data.get("notifications") if isinstance(data, dict) else None
        if not isinstance(found, list):
            raise CatGenieError("PetNovations sent no notification list")
        return [n for n in found if isinstance(n, dict) and n.get("id")]

    # ----- the wire ---------------------------------------------------------------------

    async def _call(self, method: str, path: str, params: dict[str, str] | None = None) -> Any:
        await self._ensure_token()
        answer = await self._send(method, path, params=params, token=self._token)
        if answer.status == 401:  # ended early: once more with a new one
            await self._renew()
            answer = await self._send(method, path, params=params, token=self._token)
        if answer.status == 401:
            raise SignInLost(
                "PetNovations stopped accepting Themi's sign-in. Link the litter box again."
            )
        if not 200 <= answer.status < 300:
            log.info("PetNovations answered %s for %s", answer.status, path)
            raise CatGenieError(f"PetNovations answered {answer.status}")
        data = _json(answer)
        if data is None:
            # What its edge does to a request it doesn't trust: never "no devices".
            raise CatGenieError("PetNovations answered with nothing (its edge may be filtering)")
        return data

    async def _ensure_token(self) -> None:
        if self._token and self._token_until is not None and clock.now() < self._token_until:
            return
        await self._renew()

    async def _renew(self) -> None:
        if self.refresh_token is None:
            raise SignInLost("The litter box isn't linked.")
        answer = await self._send(
            "POST", REFRESH, body={"refreshToken": self.refresh_token.reveal()}
        )
        data = _json(answer)
        if answer.status in (400, 401, 403):
            raise SignInLost(
                "PetNovations stopped accepting Themi's sign-in. Link the litter box again."
            )
        if not 200 <= answer.status < 300 or not isinstance(data, dict) or not data.get("token"):
            raise CatGenieError(f"PetNovations didn't renew the sign-in ({answer.status})")
        self._token = str(data["token"])
        self._token_until = _expiry(data.get("expiration"), clock.now()) - TOKEN_EARLY
        if data.get("refreshToken") and data["refreshToken"] != self.refresh_token.reveal():
            self.refresh_token = Secret(str(data["refreshToken"]))

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        token: str = "",
    ) -> Answer:
        ms = int(clock.now().timestamp() * 1000)
        headers = {
            **HEADERS,
            "x-pm-en-dec": time_field(ms),
            "x-pm-en-ver": "1.0.0",
            "x-render-t": f"{render_path(path)}/{ms}",
        }
        if token:
            headers["authorization"] = f"Bearer {token}"
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        return await self._wire.request(method, f"{self._base}/{path}", headers, data, params)


def _json(answer: Answer) -> Any:
    if not answer.body:
        return None
    try:
        return json.loads(answer.body)
    except ValueError:
        return None


# ----- the account --------------------------------------------------------------------------


class CatGenieAccount:
    """The family's CatGenie sign-in. Admins link it; the litter boxes share it. The phone
    number is only used to sign in, never kept."""

    def __init__(self, db: Database, cipher: Cipher, config: CatGenieConfig) -> None:
        self.db = db
        self.cipher = cipher
        self.config = config
        self._client: CatGenieClient | None = None

    def linked(self) -> bool:
        return self._row() is not None

    def problem(self) -> str | None:
        """Why the litter box can't be read, when the sign-in stopped working."""
        row = self._row()
        return str(row["problem"]) if row and row["problem"] else None

    async def send_code(self, phone: str) -> str:
        """Ask for the code; returns the number as it was used."""
        phone = normal_phone(phone)
        client = CatGenieClient(self.config)
        try:
            await client.send_code(phone)
        finally:
            await client.aclose()
        return phone

    async def link(self, member: Member, phone: str, code: str) -> list[dict[str, Any]]:
        """Trade the code for a sign-in, list the litter boxes with it, then keep it."""
        phone, code = normal_phone(phone), code.strip()
        if not code:
            raise BadCode("Enter the code PetNovations texted.")
        client = CatGenieClient(self.config)
        try:
            await client.sign_in(phone, code)
            found = await client.devices()
        except BaseException:
            await client.aclose()
            raise
        assert client.refresh_token is not None
        self.db.execute(
            "INSERT INTO catgenie_account (id, refresh_token, problem, linked_by, linked_at) "
            "VALUES (1, ?, NULL, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "refresh_token = excluded.refresh_token, problem = NULL, "
            "linked_by = excluded.linked_by, linked_at = excluded.linked_at",
            (self.cipher.encrypt(client.refresh_token), member.id, to_utc_iso(clock.now())),
        )
        await self.close()
        self._client = client
        return found

    async def unlink(self) -> None:
        self.db.execute("DELETE FROM catgenie_account")
        self.db.execute("DELETE FROM devices WHERE provider = 'catgenie'")
        self.db.execute("DELETE FROM catgenie_notifications")
        await self.close()

    async def devices(self) -> list[dict[str, Any]]:
        return await self._with_client(lambda c: c.devices())

    async def notifications(self) -> list[dict[str, Any]]:
        return await self._with_client(lambda c: c.notifications())

    def broken(self, why: str) -> bool:
        """The sign-in stopped working: kept as the problem until linked again. True the
        first time (so an admin hears once)."""
        row = self._row()
        if row is None or row["problem"]:
            return False
        self.db.execute("UPDATE catgenie_account SET problem = ? WHERE id = 1", (why,))
        return True

    async def close(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            await client.aclose()

    def _client_for_row(self) -> CatGenieClient:
        if self._client is None:
            row = self._row()
            if row is None:
                raise SignInLost("The litter box isn't linked.")
            if row["problem"]:
                raise SignInLost(str(row["problem"]))
            self._client = CatGenieClient(self.config, self.cipher.decrypt(row["refresh_token"]))
        return self._client

    async def _with_client(self, call: Any) -> Any:
        client = self._client_for_row()
        before = client.refresh_token
        try:
            return await call(client)
        finally:
            if client.refresh_token is not None and client.refresh_token is not before:
                self.db.execute(  # PetNovations handed out a new one: keep that
                    "UPDATE catgenie_account SET refresh_token = ? WHERE id = 1",
                    (self.cipher.encrypt(client.refresh_token),),
                )

    def _row(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM catgenie_account WHERE id = 1")
