"""SL1: the little of Slack's Web API that Themi uses, over httpx.

Every call is a form post with the token as a bearer header; Slack answers 200 with
`ok: false` and an `error` word when something's wrong, which becomes a `SlackError`. A 429
waits for `Retry-After` (through the injected sleep, so tests never wait) and tries again.

Not `slack_sdk`: its async client needs aiohttp, and the rest of Themi talks HTTP through
httpx, with fakes to match (the Slack plan's deviation note).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from themi.http import tls
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"
ATTEMPTS = 3
TIMEOUT = 20.0

Sleep = Callable[[float], Awaitable[None]]


class SlackError(Exception):
    """Slack said no (`error` is its word for why, like `invalid_auth`), or couldn't be
    reached (`error` is `unreachable`, `status` the HTTP status if there was one)."""

    def __init__(self, method: str, error: str, status: int = 200) -> None:
        super().__init__(f"Slack {method}: {error}")
        self.method = method
        self.error = error
        self.status = status


class SlackApi:
    def __init__(
        self,
        token: Secret,
        *,
        base_url: str = SLACK_API,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self.base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._http = http
        self._own_http = http is None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=TIMEOUT, verify=tls())
        return self._http

    async def close(self) -> None:
        if self._http is not None and self._own_http:
            await self._http.aclose()
            self._http = None

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token.reveal()}"}

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        """Call `method` with `params` (lists and dicts sent as JSON, None left out)."""
        data = {k: _form_value(v) for k, v in params.items() if v is not None}
        for attempt in range(ATTEMPTS):
            last = attempt == ATTEMPTS - 1
            try:
                response = await self.http.post(
                    f"{self.base_url}/{method}", data=data, headers=self._auth()
                )
            except httpx.HTTPError as exc:
                if last:
                    raise SlackError(method, "unreachable") from exc
                await self._sleep(self._rng.uniform(0, 2.0**attempt))
                continue
            if response.status_code == 429:
                if last:
                    raise SlackError(method, "ratelimited", 429)
                await self._sleep(_retry_after(response))
                continue
            if response.status_code >= 500:
                if last:
                    raise SlackError(method, "unreachable", response.status_code)
                await self._sleep(self._rng.uniform(0, 2.0**attempt))
                continue
            try:
                body = response.json()
            except ValueError as exc:
                raise SlackError(method, "not_json", response.status_code) from exc
            if not body.get("ok"):
                raise SlackError(method, str(body.get("error") or "unknown"), response.status_code)
            return body
        raise AssertionError("unreachable")  # pragma: no cover

    def is_slack(self, url: str) -> bool:
        """A file's address on Slack (or on the API's own host, for the fake): the only
        places the token is ever sent to."""
        host = urlparse(url).hostname or ""
        own = urlparse(self.base_url).hostname or ""
        return host == own or host == "slack.com" or host.endswith(".slack.com")

    async def download(self, url: str, limit: int) -> bytes | None:
        """A file someone shared (`url_private`), held in memory; None when it's larger
        than `limit` or isn't on Slack."""
        if not self.is_slack(url):
            log.warning("Not downloading a Slack file from another host")
            return None
        async with self.http.stream("GET", url, headers=self._auth()) as response:
            if response.status_code != 200:
                raise SlackError("download", "unreachable", response.status_code)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > limit:
                    return None
            return bytes(data)

    async def upload(self, url: str, data: bytes, filename: str) -> None:
        """The middle step of Slack's external upload: the bytes, to the address
        `files.getUploadURLExternal` gave."""
        response = await self.http.post(url, files={"file": (filename, data)})
        if response.status_code != 200:
            raise SlackError("upload", "unreachable", response.status_code)


def _form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", "1")))
    except ValueError:
        return 1.0
