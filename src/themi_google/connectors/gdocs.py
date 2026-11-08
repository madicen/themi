"""A small Google Docs and Drive REST client over `httpx` (RC1a, RC5).

Only what the cookbook needs: a document's structure (Docs API `documents.get`), its file
record from Drive (name, type, version: a cheap check for "has it changed?"), and
`documents.batchUpdate` with a required revision, so Themi never writes over an edit made
since it last read the doc. The scope is `drive.file`: Themi can open only the files a
person picked for it in Google's file picker, or that it made itself. Like the other
Google clients, a 401 drops the cached access token and retries once.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from themi.http import tls
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

TIMEOUT = 30.0
DOC_MIME = "application/vnd.google-apps.document"

TokenSource = Callable[[], Awaitable[Secret]]


class DocsError(Exception):
    """Something to tell the person, in plain words."""


class DocsAuthError(DocsError):
    pass


class DocsNotFound(DocsError):
    """Gone, or not one Themi was given (with drive.file, a doc not picked looks the same)."""


class DocsConflict(DocsError):
    """The doc changed since it was read (the required revision didn't match)."""


class DocsClient:
    def __init__(
        self,
        docs_url: str,
        drive_url: str,
        token: TokenSource,
        on_unauthorized: Callable[[], None],
    ) -> None:
        self.docs = f"{docs_url.rstrip('/')}/v1/documents"
        self.drive = f"{drive_url.rstrip('/')}/drive/v3/files"
        self.token = token
        self.on_unauthorized = on_unauthorized

    async def get(self, doc_id: str) -> dict[str, Any]:
        """The document: title, revisionId and body.content (paragraphs, tables...)."""
        return await self._request("GET", f"{self.docs}/{quote(doc_id, safe='')}")

    async def file(self, doc_id: str) -> dict[str, Any]:
        """Drive's record: id, name, mimeType, version, modifiedTime, capabilities.canEdit."""
        return await self._request(
            "GET",
            f"{self.drive}/{quote(doc_id, safe='')}",
            params={"fields": "id,name,mimeType,version,modifiedTime,capabilities(canEdit)"},
        )

    async def batch_update(
        self, doc_id: str, requests: list[dict[str, Any]], revision_id: str
    ) -> dict[str, Any]:
        """Apply `requests` in one go, only if the doc is still at `revision_id`."""
        return await self._request(
            "POST",
            f"{self.docs}/{quote(doc_id, safe='')}:batchUpdate",
            json={"requests": requests, "writeControl": {"requiredRevisionId": revision_id}},
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in (1, 2):
            token = await self.token()
            try:
                async with httpx.AsyncClient(verify=tls(), timeout=TIMEOUT) as client:
                    response = await client.request(
                        method, url, headers={"Authorization": f"Bearer {token.reveal()}"}, **kwargs
                    )
            except httpx.HTTPError as exc:
                raise DocsError(f"Google Docs couldn't be reached ({type(exc).__name__})") from exc
            if response.status_code == 401 and attempt == 1:
                self.on_unauthorized()
                continue
            return _result(response)
        raise AssertionError("unreachable")


def _result(response: httpx.Response) -> dict[str, Any]:
    status = response.status_code
    if status == 200:
        return response.json() if response.content else {}
    if status == 401:
        raise DocsAuthError("Google refused the access token for the cookbook")
    if status in (403, 404):
        raise DocsNotFound(
            "Google won't let Themi open that doc. Choosing it in the file picker on the "
            "Accounts page gives Themi access to it (and only it)."
        )
    if status == 400 and "revision" in response.text.lower():
        raise DocsConflict("The cookbook changed while Themi was writing to it")
    log.info("Google Docs returned HTTP %s for %s", status, response.request.url.path)
    raise DocsError(f"Google Docs returned HTTP {status}")


def doc_id_from(text: str) -> str | None:
    """A doc id from a docs.google.com link, or the id itself."""
    text = text.strip()
    found = re.search(r"/document/d/([A-Za-z0-9_-]{20,})", text)
    if found:
        return found.group(1)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{20,}", text) else None
