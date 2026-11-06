"""Web search for Themi's lookups (F30d, idea #162): one interface, two backends.

- Tavily (`TAVILY_API_KEY`, the default): 1,000 free credits a month, a basic search is 1
  credit, reading pages 1 credit per 5. No card needed.
- Firecrawl (`FIRECRAWL_API_KEY`): 1,000 free credits a month, a search is 2 credits per
  10 results; it reads a page into clean text. No card needed.

`THEMI_SEARCH_BACKEND` picks one; empty uses whichever has a key, Tavily first. Both are
plain HTTP over `httpx`; tests hand in a transport (`tests/fakes/search.py`). What comes
back is outside text: the caller treats it as data, never instructions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from themi.http import tls
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com"
FIRECRAWL_URL = "https://api.firecrawl.dev"
TIMEOUT = 30.0
MAX_PAGE = 20_000  # characters of a page kept


class SearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchBackend(Protocol):
    name: str

    async def search(self, query: str, count: int = 5) -> list[SearchResult]: ...

    async def read(self, url: str) -> str: ...


class _Http:
    def __init__(
        self, key: Secret, base_url: str, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self._key = key
        self._base = base_url.rstrip("/")
        self._transport = transport

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {"Authorization": f"Bearer {self._key.reveal()}"}
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, transport=self._transport, verify=tls()
            ) as client:
                response = await client.post(f"{self._base}{path}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise SearchError(f"couldn't reach the search service ({type(exc).__name__})") from exc
        if response.status_code in (401, 403):
            raise SearchError("the search service turned the key down")
        if response.status_code == 429 or response.status_code == 432:
            raise SearchError("the search service's limit is used up for now")
        if response.status_code >= 400:
            raise SearchError(f"the search service answered {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise SearchError("the search service's answer wasn't readable") from exc


class TavilySearch(_Http):
    name = "Tavily"

    def __init__(
        self, key: Secret, *, base_url: str = TAVILY_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        super().__init__(key, base_url, transport)

    async def search(self, query: str, count: int = 5) -> list[SearchResult]:
        body = await self._post(
            "/search", {"query": query, "max_results": count, "search_depth": "basic"}
        )
        return [
            SearchResult(str(r.get("title", "")), str(r.get("url", "")), str(r.get("content", "")))
            for r in (body.get("results") or [])
            if isinstance(r, dict) and r.get("url")
        ][:count]

    async def read(self, url: str) -> str:
        body = await self._post("/extract", {"urls": [url]})
        for r in body.get("results") or []:
            if isinstance(r, dict) and r.get("raw_content"):
                return str(r["raw_content"])[:MAX_PAGE]
        # Some sites refuse the fetch ("Failed to fetch url"); another result may read fine.
        raise SearchError("that site wouldn't let the page be read; another result may work")


class FirecrawlSearch(_Http):
    name = "Firecrawl"

    def __init__(
        self, key: Secret, *, base_url: str = FIRECRAWL_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        super().__init__(key, base_url, transport)

    async def search(self, query: str, count: int = 5) -> list[SearchResult]:
        body = await self._post("/v2/search", {"query": query, "limit": count})
        data = body.get("data")
        items = data.get("web", []) if isinstance(data, dict) else data or []  # v2, or v1
        return [
            SearchResult(
                str(r.get("title", "")), str(r.get("url", "")), str(r.get("description", ""))
            )
            for r in items
            if isinstance(r, dict) and r.get("url")
        ][:count]

    async def read(self, url: str) -> str:
        body = await self._post("/v2/scrape", {"url": url, "formats": ["markdown"]})
        data = body.get("data") or {}
        text = data.get("markdown") if isinstance(data, dict) else None
        if not text:
            raise SearchError("that site wouldn't let the page be read; another result may work")
        return str(text)[:MAX_PAGE]


def choose(
    backend: str, tavily_key: Secret | None, firecrawl_key: Secret | None
) -> SearchBackend | None:
    """The configured backend, or None when there's no key for it."""
    wanted = backend.strip().lower()
    if wanted == "firecrawl" or (not wanted and tavily_key is None):
        return FirecrawlSearch(firecrawl_key) if firecrawl_key else None
    return TavilySearch(tavily_key) if tavily_key else None
