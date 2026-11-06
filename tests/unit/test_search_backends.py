"""F30d: which search backend is used, and Firecrawl's two answer shapes."""

from __future__ import annotations

import json

import httpx

from themi.connectors.search import FirecrawlSearch, TavilySearch, choose
from themi.storage.secrets import Secret

T, F = Secret("tvly-x"), Secret("fc-x")


def test_the_backend_chosen() -> None:
    assert isinstance(choose("", T, F), TavilySearch)  # Tavily first
    assert isinstance(choose("", None, F), FirecrawlSearch)
    assert isinstance(choose("firecrawl", T, F), FirecrawlSearch)
    assert choose("firecrawl", T, None) is None  # asked for, but no key
    assert choose("", None, None) is None


async def test_firecrawls_older_list_answer_reads_too() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        body = {"success": True, "data": [{"url": "https://a.example", "title": "A",
                                           "description": "about a"}]}  # fmt: skip
        return httpx.Response(200, content=json.dumps(body).encode())

    backend = FirecrawlSearch(F, transport=httpx.MockTransport(answer))
    (result,) = await backend.search("a")
    assert (result.title, result.url, result.snippet) == ("A", "https://a.example", "about a")
