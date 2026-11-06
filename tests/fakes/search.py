"""A fake web search service for F30d: Tavily's /search and /extract, and Firecrawl's
/v2/search and /v2/scrape.

    fake_search.result("dr scheinbach", "Dr. Scheinbach, DDS", "https://dds.example/s", "...")
    fake_search.page("https://dds.example/s", "Dr. Scheinbach sees patients Mon-Thu.")
    fake_search.backend = "firecrawl"        # the other backend, over the same fake
    fake_search.fail("search", 429)          # the next search is refused
    fake_search.result(..., deep=True)       # found only by a deeper search (F31c)

The scenario harness hands Themi a backend over this transport when a test uses the
`fake_search` fixture. No real network calls.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import httpx
import pytest

from themi.connectors.search import FirecrawlSearch, SearchBackend, TavilySearch
from themi.storage.secrets import Secret

KEY = "tvly-test-key-0000000000000000"


class FakeSearch:
    def __init__(self) -> None:
        self.results: dict[str, list[dict[str, str]]] = {}  # query words -> results
        self.deep: dict[str, list[dict[str, str]]] = {}  # found only by a deep search
        self.pages: dict[str, str] = {}
        self.backend = "tavily"
        self.calls: list[tuple[str, dict[str, Any]]] = []  # (kind, body)
        self._failures: Counter[str] = Counter()
        self.transport = httpx.MockTransport(self._handle)

    def result(self, words: str, title: str, url: str, snippet: str, *, deep: bool = False) -> None:
        (self.deep if deep else self.results).setdefault(words.lower(), []).append(
            {"title": title, "url": url, "snippet": snippet}
        )

    def queries(self) -> list[str]:
        return [str(b["query"]) for k, b in self.calls if k == "search"]

    def page(self, url: str, text: str) -> None:
        self.pages[url] = text

    def fail(self, kind: str, status: int = 500) -> None:
        self._failures[f"{kind}:{status}"] += 1

    def client(self) -> SearchBackend:
        if self.backend == "firecrawl":
            return FirecrawlSearch(
                Secret(KEY), base_url="https://firecrawl.test", transport=self.transport
            )
        return TavilySearch(Secret(KEY), base_url="https://tavily.test", transport=self.transport)

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    def _found(self, query: str, deep: bool = False) -> list[dict[str, str]]:
        query = query.lower()
        found = [r for words, rs in self.results.items() if words in query for r in rs]
        if deep:
            found += [r for words, rs in self.deep.items() if words in query for r in rs]
        return found

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == f"Bearer {KEY}"
        body = json.loads(request.content or b"{}")
        path = request.url.path
        kind = "read" if path in ("/extract", "/v2/scrape") else "search"
        self.calls.append((kind, body))
        for failure in list(self._failures):
            name, status = failure.split(":")
            if name == kind and self._failures[failure]:
                self._failures[failure] -= 1
                return httpx.Response(int(status))
        if request.url.host == "tavily.test" and path == "/search":
            deep = body.get("search_depth") == "advanced"
            found = self._found(body["query"], deep)[: body.get("max_results", 5)]
            return _json(
                {
                    "results": [
                        {"title": r["title"], "url": r["url"], "content": r["snippet"]}
                        for r in found
                    ]
                }
            )
        if request.url.host == "tavily.test" and path == "/extract":
            (url,) = body["urls"]
            done = [{"url": url, "raw_content": self.pages[url]}] if url in self.pages else []
            return _json({"results": done, "failed_results": [] if done else [{"url": url}]})
        if request.url.host == "firecrawl.test" and path == "/v2/search":
            found = self._found(body["query"], body.get("limit", 5) >= 10)[: body.get("limit", 5)]
            web = [{"title": r["title"], "url": r["url"], "description": r["snippet"]}
                   for r in found]  # fmt: skip
            return _json({"success": True, "data": {"web": web}})
        if request.url.host == "firecrawl.test" and path == "/v2/scrape":
            text = self.pages.get(body["url"])
            return _json({"success": True, "data": {"markdown": text}} if text else {})
        return httpx.Response(404)


def _json(body: Any) -> httpx.Response:
    return httpx.Response(
        200, content=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )


@pytest.fixture
def fake_search() -> FakeSearch:
    return FakeSearch()
