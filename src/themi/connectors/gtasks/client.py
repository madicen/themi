"""A small Google Tasks REST client (API v1) over `httpx` (GT1a).

Only what Themi needs: the open tasks on a list and deleting one (GT1a); the
lists, making one, and writing tasks to it (GT1b). "@default" is the account's
default list ("My Tasks"), where "Hey Google, add a task" puts them. The API
has no push notifications, so callers poll. Like the Calendar client, a 401
drops the cached access token and retries once.
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
DEFAULT_LIST = "@default"
PAGE = 100  # the most the API returns at once

TokenSource = Callable[[], Awaitable[Secret]]


class TasksError(Exception):
    pass


class TasksAuthError(TasksError):
    pass


class _Gone(TasksError):
    pass


class TasksClient:
    def __init__(
        self, base_url: str, token: TokenSource, on_unauthorized: Callable[[], None]
    ) -> None:
        self.base = f"{base_url.rstrip('/')}/tasks/v1"
        self.token = token
        self.on_unauthorized = on_unauthorized

    async def open_tasks(self, list_id: str = DEFAULT_LIST) -> list[dict[str, Any]]:
        """The list's tasks that aren't done, oldest first."""
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            params = {"showCompleted": "false", "maxResults": str(PAGE)}
            if page:
                params["pageToken"] = page
            body = await self._request("GET", _tasks(list_id), params=params)
            items.extend(i for i in body.get("items", []) if i.get("status") != "completed")
            page = body.get("nextPageToken")
            if not page:
                return sorted(items, key=lambda i: str(i.get("updated", "")))

    async def lists(self) -> list[dict[str, Any]]:
        body = await self._request("GET", "/users/@me/lists", params={"maxResults": str(PAGE)})
        return list(body.get("items", []))

    async def create_list(self, title: str) -> str:
        body = await self._request("POST", "/users/@me/lists", json={"title": title})
        return str(body["id"])

    async def all_tasks(self, list_id: str) -> list[dict[str, Any]]:
        """Every task on the list, done ones too (also those done in Google's own apps)."""
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            params = {"showCompleted": "true", "showHidden": "true", "maxResults": str(PAGE)}
            if page:
                params["pageToken"] = page
            body = await self._request("GET", _tasks(list_id), params=params)
            items.extend(body.get("items", []))
            page = body.get("nextPageToken")
            if not page:
                return items

    async def insert_task(self, list_id: str, task: dict[str, Any]) -> str:
        body = await self._request("POST", _tasks(list_id), json=task)
        return str(body["id"])

    async def patch_task(self, list_id: str, task_id: str, changes: dict[str, Any]) -> None:
        await self._request("PATCH", f"{_tasks(list_id)}/{quote(task_id, safe='')}", json=changes)

    async def delete_task(self, list_id: str, task_id: str) -> None:
        """Gone already counts as done."""
        with contextlib.suppress(_Gone):
            await self._request("DELETE", f"{_tasks(list_id)}/{quote(task_id, safe='')}")

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
                raise TasksError(
                    f"Google Tasks couldn't be reached ({type(exc).__name__})"
                ) from exc
            if response.status_code == 401 and attempt == 1:
                self.on_unauthorized()
                continue
            return _result(response)
        raise AssertionError("unreachable")


def _tasks(list_id: str) -> str:
    return f"/lists/{quote(list_id, safe='@')}/tasks"


def _result(response: httpx.Response) -> dict[str, Any]:
    status = response.status_code
    if status in (200, 204):
        return response.json() if response.content else {}
    if status == 401:
        raise TasksAuthError("Google Tasks refused the access token")
    if status in (404, 410):
        raise _Gone(response.request.url.path)
    log.info("Google Tasks returned HTTP %s for %s", status, response.request.url.path)
    raise TasksError(f"Google Tasks returned HTTP {status}")
