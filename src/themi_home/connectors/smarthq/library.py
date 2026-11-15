"""The real SmartHQ connection, over `gehomesdk` (optional: `themi[smarthq]`).

`LibraryLogin` signs in with `GeSmartHqLogin` (which handles SmartHQ's emailed code) and
opens a `LibrarySession`: a `GeWebsocketClient` seeded with the refresh token, running in
the background. GE's cloud pushes every ERD the range sends; the session answers reads from
the library's raw cache and writes raw hex, so Themi decodes and encodes the bytes itself
(`events`).

This is the one piece the default test run can't reach: tests use `tests/fakes/smarthq.py`.
OV1 ran the same calls against the family's range.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from themi import clock
from themi_home.connectors.smarthq.client import (
    BadCode,
    Range,
    RangeOffline,
    SignIn,
    SignInLost,
    SmartHQError,
    SmartHQSession,
)
from themi_home.connectors.smarthq.events import MODEL_NUMBER

log = logging.getLogger(__name__)

CONNECT_WITHIN = 60.0  # seconds for the range to show up after connecting


def _library() -> Any:
    try:
        import gehomesdk  # type: ignore[import-not-found]
    except ImportError:
        return None
    return gehomesdk


def available() -> LibraryLogin | None:
    """The real sign-in, or None without the library (no oven, then)."""
    return LibraryLogin() if _library() is not None else None


class LibraryLogin:
    def __init__(self) -> None:
        # A code is traded by the same login that asked for it (its cookies and CSRF token).
        self._pending: dict[str, tuple[Any, Any]] = {}  # email -> (aiohttp session, login)

    async def sign_in(self, email: str, password: str, region: str) -> SignIn:
        import aiohttp
        from gehomesdk.clients.smart_hq_login import (  # type: ignore[import-not-found]
            GeSmartHqLogin,
        )

        await self._drop(email)
        http = aiohttp.ClientSession()
        login = GeSmartHqLogin(http)
        try:
            with _translated("sign_in"):
                result = await login.async_login(email, password, region)
                if result.mfa_required:
                    await login.async_send_code((result.mfa_methods or ["email"])[0])
                    self._pending[email] = (http, login)
                    return SignIn(code_sent=True)
                return SignIn(token=str(result.token["refresh_token"]))
        finally:
            if email not in self._pending:
                await http.close()

    async def submit_code(self, email: str, code: str) -> str:
        if email not in self._pending:
            raise BadCode("That sign-in has ended; start again.")
        _, login = self._pending[email]
        try:
            with _translated("code"):
                token = await login.async_submit_code(code)
        except BadCode:
            raise  # the same login takes another try
        except BaseException:
            await self._drop(email)
            raise
        await self._drop(email)
        return str(token["refresh_token"])

    async def open(self, email: str, region: str, refresh_token: str) -> SmartHQSession:
        session = LibrarySession(email, region, refresh_token)
        await session.start()
        return session

    async def settle(self, seconds: float) -> None:
        await clock.sleep(seconds)

    async def _drop(self, email: str) -> None:
        pending = self._pending.pop(email, None)
        if pending is not None:
            await pending[0].close()


class LibrarySession:
    def __init__(self, email: str, region: str, refresh_token: str) -> None:
        self.email, self.region, self._token = email, region, refresh_token
        self._client: Any = None
        self._http: Any = None
        self._task: asyncio.Task[None] | None = None
        self._appliances: dict[str, Any] = {}
        self._ready = asyncio.Event()

    async def start(self) -> None:
        import aiohttp
        from gehomesdk import (  # type: ignore[import-not-found]
            EVENT_APPLIANCE_INITIAL_UPDATE,
            GeWebsocketClient,
        )

        # The password isn't needed while the refresh token works; an empty one makes a
        # refused token fail rather than start an emailed-code sign-in nobody can answer.
        self._client = GeWebsocketClient(self.email, "", self.region, refresh_token=self._token)
        self._client.add_event_handler(EVENT_APPLIANCE_INITIAL_UPDATE, self._found)
        self._http = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(self._ready.wait(), CONNECT_WITHIN)
        except TimeoutError:
            failed = self._task.done() and self._task.exception()
            await self.close()
            if failed:
                _raise(failed)
            raise RangeOffline("SmartHQ didn't show the range in time.") from None

    async def _run(self) -> None:
        assert self._client is not None
        await self._client.async_get_credentials_and_run(self._http)

    async def _found(self, appliance: Any) -> None:
        self._appliances[appliance.mac_addr] = appliance
        self._ready.set()

    async def ranges(self) -> list[Range]:
        found = []
        for mac, appliance in self._appliances.items():
            raw = appliance.get_raw_erd_value(MODEL_NUMBER) or ""
            found.append(Range(mac, _model(raw)))
        return found

    async def erds(self, mac: str) -> dict[str, str]:
        self._check()
        appliance = self._appliances.get(mac)
        if appliance is None or not appliance.available:
            raise RangeOffline("The range isn't connected right now.")
        out = {}
        for erd in appliance.known_properties:
            value = appliance.get_raw_erd_value(erd)
            if value is not None:
                out[str(getattr(erd, "value", erd)).lower()] = str(value)
        return out

    async def write(self, mac: str, erd: str, value: str) -> None:
        self._check()
        appliance = self._appliances.get(mac)
        if appliance is None or not appliance.available:
            raise RangeOffline("The range isn't connected right now.")
        with _translated():
            await self._client.async_set_erd_value(appliance, erd, value)

    def refresh_token(self) -> str | None:
        token = getattr(self._client, "refresh_token", None) if self._client else None
        return str(token) if token else self._token

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                log.info("SmartHQ didn't disconnect cleanly")
        if self._task is not None:
            await asyncio.wait([self._task], timeout=10)
            if not self._task.done():
                self._task.cancel()
        if self._http is not None:
            await self._http.close()

    def _check(self) -> None:
        if self._task is not None and self._task.done():
            failed = self._task.exception()
            if failed:
                _raise(failed)
            raise RangeOffline("The SmartHQ connection closed.")


def _model(raw: str) -> str:
    """MODEL_NUMBER: a length byte, then ASCII ("0C" + "CHS950P2M9S1")."""
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return ""
    return data[1 : 1 + data[0]].decode("ascii", "replace") if data else ""


def _raise(exc: BaseException) -> None:
    with _translated():
        raise exc


class _translated:
    """The library's errors as Themi's. `step`: what was being done, since GE answers a
    wrong password and a wrong code with the same error."""

    def __init__(self, step: str = "session") -> None:
        self.step = step

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, exc: BaseException | None, tb: Any) -> None:
        if exc is None or not isinstance(exc, Exception) or isinstance(exc, SmartHQError):
            return
        from gehomesdk import exception as ge  # type: ignore[import-not-found]

        if isinstance(exc, ge.GeAuthFailedError) and self.step == "code":
            raise BadCode("That code didn't work; check it, or start again.") from exc
        if isinstance(exc, ge.GeAuthFailedError) and self.step == "sign_in":
            raise SmartHQError("SmartHQ didn't accept that email and password.") from exc
        if isinstance(
            exc,
            ge.GeAuthFailedError | ge.GeNotAuthenticatedError | ge.GeNeedsReauthenticationError,
        ):
            raise SignInLost("SmartHQ no longer accepts the sign-in; link it again.") from exc
        if isinstance(exc, ge.GeSetErdNotAllowedError):
            raise SmartHQError("The range doesn't take that from here.") from exc
        if isinstance(exc, OSError | TimeoutError | ge.GeClientDisconnectedError):
            raise RangeOffline(f"SmartHQ didn't answer: {exc}") from exc
        raise SmartHQError(f"SmartHQ said: {exc}") from exc
