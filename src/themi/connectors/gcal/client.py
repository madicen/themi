"""A small Google Calendar REST client (API v3) over `httpx`.

Only what Themi needs: the calendar list (to find the "Themi" calendar), making
a calendar, and writing, updating and deleting events by id. Like the Gmail
client, a 401 drops the cached access token and retries once.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

TIMEOUT = 30.0

TokenSource = Callable[[], Awaitable[Secret]]


class CalendarError(Exception):
    pass


class CalendarAuthError(CalendarError):
    pass


class CalendarNotFound(CalendarError):
    pass


class CalendarConflict(CalendarError):
    """An event with that id already exists (possibly deleted)."""


class CalendarClient:
    def __init__(
        self, base_url: str, token: TokenSource, on_unauthorized: Callable[[], None]
    ) -> None:
        self.base = f"{base_url.rstrip('/')}/calendar/v3"
        self.token = token
        self.on_unauthorized = on_unauthorized

    async def calendars(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            params = {"pageToken": page} if page else {}
            body = await self._request("GET", "/users/me/calendarList", params=params)
            items.extend(body.get("items", []))
            page = body.get("nextPageToken")
            if not page:
                return items

    async def create_calendar(self, name: str, timezone: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/calendars", json={"summary": name, "timeZone": timezone}
        )

    async def update_event(self, calendar_id: str, event_id: str, event: dict[str, Any]) -> None:
        await self._request("PUT", f"{_events(calendar_id)}/{event_id}", json=event)

    async def insert_event(self, calendar_id: str, event: dict[str, Any]) -> None:
        await self._request("POST", _events(calendar_id), json=event)

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Gone already (404, or 410 for deleted) counts as done."""
        with contextlib.suppress(CalendarNotFound):
            await self._request("DELETE", f"{_events(calendar_id)}/{event_id}")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in (1, 2):
            token = await self.token()
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                    response = await client.request(
                        method,
                        f"{self.base}{path}",
                        headers={"Authorization": f"Bearer {token.reveal()}"},
                        **kwargs,
                    )
            except httpx.HTTPError as exc:
                raise CalendarError(
                    f"Google Calendar couldn't be reached ({type(exc).__name__})"
                ) from exc
            if response.status_code == 401 and attempt == 1:
                self.on_unauthorized()
                continue
            return _result(response)
        raise AssertionError("unreachable")


def _events(calendar_id: str) -> str:
    return f"/calendars/{quote(calendar_id, safe='')}/events"


def _result(response: httpx.Response) -> dict[str, Any]:
    status = response.status_code
    if status in (200, 204):
        return response.json() if response.content else {}
    if status == 401:
        raise CalendarAuthError("Google Calendar refused the access token")
    if status in (404, 410):
        raise CalendarNotFound(response.request.url.path)
    if status == 409:
        raise CalendarConflict(response.request.url.path)
    log.info("Google Calendar returned HTTP %s for %s", status, response.request.url.path)
    raise CalendarError(f"Google Calendar returned HTTP {status}")
