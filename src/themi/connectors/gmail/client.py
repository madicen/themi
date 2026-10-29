"""A small Gmail REST client (API v1) over `httpx`.

Only what Themi needs: list and get messages, `history.list`, the profile
(for a starting history id), labels, modify labels and send. Every call gets
a fresh access token from `token()`; a 401 drops the cached token and is
retried once with a refreshed one, since an access token can be revoked
before it expires.

Errors are typed so the sync can react: `HistoryExpired` (start over),
`RateLimited` (back off, with Google's Retry-After when given),
`GmailAuthError` (the token keeps being refused) and `GmailError`.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

TIMEOUT = 30.0
PAGE_SIZE = 100

TokenSource = Callable[[], Awaitable[Secret]]


class GmailError(Exception):
    pass


class GmailAuthError(GmailError):
    pass


class HistoryExpired(GmailError):
    """The stored history id is too old; Gmail keeps about a week of history."""


class RateLimited(GmailError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Gmail asked Themi to slow down")
        self.retry_after = retry_after


@dataclass(frozen=True)
class HistoryPage:
    added: list[str]  # message ids added to the inbox, in order
    history_id: str
    next_page: str | None
    # Idea #83: mail dealt with in Gmail itself, (message id, "archived" | "read" |
    # "deleted"), in order. Themi's own archiving and marking read show here too.
    handled: list[tuple[str, str]] = field(default_factory=list)


class GmailClient:
    def __init__(
        self, base_url: str, token: TokenSource, on_unauthorized: Callable[[], None]
    ) -> None:
        self.base = f"{base_url.rstrip('/')}/gmail/v1/users/me"
        self.token = token
        self.on_unauthorized = on_unauthorized

    # ----- reading ------------------------------------------------------------

    async def profile(self) -> dict[str, Any]:
        return await self._request("GET", "/profile")

    async def list_messages(
        self, query: str = "", label: str | None = "INBOX", page_token: str | None = None
    ) -> tuple[list[str], str | None]:
        params: dict[str, Any] = {"maxResults": PAGE_SIZE}
        if query:
            params["q"] = query
        if label:
            params["labelIds"] = label
        if page_token:
            params["pageToken"] = page_token
        body = await self._request("GET", "/messages", params=params)
        return [m["id"] for m in body.get("messages", [])], body.get("nextPageToken")

    async def get_message(self, message_id: str) -> dict[str, Any] | None:
        """The full message, or None if it was deleted in the meantime."""
        try:
            return await self._request("GET", f"/messages/{message_id}", params={"format": "full"})
        except _NotFound:
            return None

    async def history(self, start_history_id: str, page_token: str | None = None) -> HistoryPage:
        """Mail added to the inbox, and mail archived, read or deleted (idea #83). No label
        filter: an archived message no longer carries INBOX, so the added ones are picked
        out by their labels here."""
        params: dict[str, Any] = {
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded", "labelRemoved", "messageDeleted"],
            "maxResults": PAGE_SIZE,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            body = await self._request("GET", "/history", params=params)
        except _NotFound as exc:
            raise HistoryExpired(start_history_id) from exc
        added, handled = [], []
        for record in body.get("history", []):
            for item in record.get("messagesAdded", []):
                if "INBOX" in item["message"].get("labelIds", ["INBOX"]):
                    added.append(item["message"]["id"])
            for item in record.get("labelsRemoved", []):
                removed = set(item.get("labelIds", []))
                how = "archived" if "INBOX" in removed else "read" if "UNREAD" in removed else ""
                if how:
                    handled.append((item["message"]["id"], how))
            for item in record.get("messagesDeleted", []):
                handled.append((item["message"]["id"], "deleted"))
        return HistoryPage(added, str(body["historyId"]), body.get("nextPageToken"), handled)

    async def labels(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/labels")).get("labels", [])

    # ----- changing -----------------------------------------------------------

    async def modify(
        self, message_id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/messages/{message_id}/modify",
            json={"addLabelIds": add or [], "removeLabelIds": remove or []},
        )

    async def create_label(self, name: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/labels",
            json={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )

    async def send(self, rfc822: bytes, thread_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"raw": base64.urlsafe_b64encode(rfc822).decode("ascii")}
        if thread_id:
            body["threadId"] = thread_id
        return await self._request("POST", "/messages/send", json=body)

    # ----- HTTP ---------------------------------------------------------------

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
                raise GmailError(f"Gmail couldn't be reached ({type(exc).__name__})") from exc
            if response.status_code == 401 and attempt == 1:
                self.on_unauthorized()  # the cached token was refused: refresh and retry once
                continue
            return _result(response)
        raise AssertionError("unreachable")


class _NotFound(GmailError):
    pass


def _result(response: httpx.Response) -> dict[str, Any]:
    status = response.status_code
    if status == 200 or status == 204:
        return response.json() if response.content else {}
    if status == 401:
        raise GmailAuthError("Gmail refused the access token")
    if status == 404:
        raise _NotFound(response.request.url.path)
    if status == 429 or (status == 403 and b"rateLimitExceeded" in response.content):
        retry = response.headers.get("Retry-After")
        raise RateLimited(float(retry) if retry and retry.replace(".", "", 1).isdigit() else None)
    log.info("Gmail returned HTTP %s for %s", status, response.request.url.path)
    raise GmailError(f"Gmail returned HTTP {status}")
