"""Recipe pages on the web, faked (RC4a): an httpx transport and a resolver, no sockets.

site = FakeRecipeSite()
site.page("https://cooks.example/brownies", BROWNIES)        # 200, text/html
site.page("https://cooks.example/old", status=301, location="https://cooks.example/new")
site.address("cooks.example", "93.184.216.34")              # what DNS says (default public)
reader = site.reader()                                       # a PageReader on the fake
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from themi.connectors.recipe_page import PageReader

PUBLIC = "93.184.216.34"


class FakeRecipeSite:
    def __init__(self) -> None:
        self.pages: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.addresses: dict[str, list[str]] = {}
        self.fetched: list[str] = []

    def page(
        self,
        url: str,
        html: str = "",
        *,
        status: int = 200,
        location: str = "",
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        headers = {"content-type": content_type}
        if location:
            headers["location"] = location
        self.pages[url] = (status, headers, html.encode())

    def address(self, host: str, *ips: str) -> None:
        self.addresses[host] = list(ips)

    async def resolve(self, host: str) -> list[str]:
        return self.addresses.get(host, [PUBLIC])

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.fetched.append(url)
        assert "cookie" not in {k.lower() for k in request.headers}
        status, headers, body = self.pages.get(url, (404, {"content-type": "text/html"}, b""))
        return httpx.Response(status, headers=headers, content=body)

    def reader(self) -> PageReader:
        return PageReader(transport=httpx.MockTransport(self._handle), resolve=self.resolve)


def recipe_page(recipe: dict[str, Any], *, graph: bool = False, words: str = "") -> str:
    """A page with a schema.org Recipe in its JSON-LD (alone, or in an @graph)."""
    data: Any = {"@context": "https://schema.org", **recipe, "@type": "Recipe"}
    if graph:
        data = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, data]}
    return (
        '<html><head><title>A recipe</title><script type="application/ld+json">'
        f"{json.dumps(data)}</script></head><body><h1>{recipe.get('name', '')}</h1>"
        f"<p>{words}</p></body></html>"
    )


def plain_page(name: str, ingredients: list[str], steps: list[str], story: str = "") -> str:
    """A page with no JSON-LD: a blog post with the recipe in its text."""
    items = "".join(f"<li>{i}</li>" for i in ingredients)
    method = "".join(f"<li>{s}</li>" for s in steps)
    return (
        f"<html><head><title>{name}</title><script>var x = 1;</script></head><body>"
        f"<p>{story}</p><h2>{name}</h2><h3>Ingredients</h3><ul>{items}</ul>"
        f"<h3>Method</h3><ol>{method}</ol></body></html>"
    )
