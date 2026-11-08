"""A recipe from a web page someone sent (RC4a).

`fetch` reads a page directly, carefully: http(s) only; refused for loopback, private,
link-local, CGNAT (100.64.0.0/10, which Tailscale uses) and `*.ts.net` addresses, checked
after DNS on every redirect (at most 3); 10 seconds; 2 MB; HTML only; no cookies; a plain
"Themi recipe reader" User-Agent. So a link can't make Themi look inside the house's own
network.

`schema_recipe` reads schema.org `Recipe` JSON-LD, which most recipe sites embed: alone, in
a list, or in `@graph`; instructions as text, `HowToStep` or `HowToSection`. Only the
standard library's HTML parser is used. `page_text` is the page's visible words, for the
model's fallback reading and for checking that what it read is really on the page.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from themi.http import tls

log = logging.getLogger(__name__)

TIMEOUT = 10.0
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
USER_AGENT = "Themi recipe reader (a household assistant; reads one page when asked)"
CGNAT = ipaddress.ip_network("100.64.0.0/10")

Resolver = Callable[[str], Awaitable[list[str]]]


class PageError(Exception):
    """Something to tell the person, in plain words."""


class Blocked(PageError):
    """The site refused the fetch (403, a bot wall): another way may still read it."""


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _refused_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT)
    )


async def check_url(url: str, resolve: Resolver) -> None:
    """Refuse a link that isn't a public web page."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PageError("Only http and https links can be read.")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".ts.net", ".local", ".internal", ".lan")):
        raise PageError("That link is to a private address, so Themi won't open it.")
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            addresses = await resolve(host)
        except OSError as exc:
            raise PageError("That site's address couldn't be found.") from exc
    if not addresses or any(_refused_address(a) for a in addresses):
        raise PageError("That link is to a private address, so Themi won't open it.")


@dataclass
class Fetched:
    url: str  # after redirects
    html: str


class PageReader:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolve: Resolver = system_resolver,
    ) -> None:
        self.transport = transport
        self.resolve = resolve

    async def fetch(self, url: str) -> Fetched:
        current = url
        async with httpx.AsyncClient(
            verify=tls(),
            timeout=TIMEOUT,
            follow_redirects=False,
            transport=self.transport,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await check_url(current, self.resolve)
                try:
                    async with client.stream("GET", current) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("location")
                            if not location:
                                raise PageError("The site sent Themi somewhere it didn't say.")
                            current = urljoin(current, location)
                            continue
                        if response.status_code in (401, 403, 429, 451):
                            raise Blocked(
                                f"The site wouldn't let Themi read it ({response.status_code})."
                            )
                        if response.status_code != 200:
                            raise PageError(f"The page didn't load (HTTP {response.status_code}).")
                        kind = response.headers.get("content-type", "")
                        if "html" not in kind.lower():
                            raise PageError("That link isn't a web page Themi can read.")
                        body = b""
                        async for chunk in response.aiter_bytes():
                            body += chunk
                            if len(body) > MAX_BYTES:
                                raise PageError("That page is too big to read.")
                        return Fetched(
                            current, body.decode(response.encoding or "utf-8", "replace")
                        )
                except httpx.HTTPError as exc:
                    raise PageError(
                        f"The page couldn't be reached ({type(exc).__name__})."
                    ) from exc
        raise PageError("The site kept sending Themi somewhere else.")


# ----- reading the page ---------------------------------------------------------------------


class _Scan(HTMLParser):
    """The page's JSON-LD blocks and its visible text."""

    SKIP = frozenset({"script", "style", "noscript", "template", "svg", "head"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_blocks: list[str] = []
        self.words: list[str] = []
        self.title = ""
        self._ld = False
        self._skip = 0
        self._in_title = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and (values.get("type") or "").lower() == "application/ld+json":
            self._ld = True
            self._buffer = []
            return
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr"):
            self.words.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld:
            self.json_blocks.append("".join(self._buffer))
            self._ld = False
            return
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._ld:
            self._buffer.append(data)
        elif self._in_title:
            self.title += data
        elif not self._skip:
            self.words.append(data)


def scan(html: str) -> _Scan:
    found = _Scan()
    try:
        found.feed(html)
    except Exception:  # a broken page: whatever was read so far
        log.info("A page's HTML didn't parse to the end")
    return found


def page_text(html: str) -> str:
    text = "".join(scan(html).words)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


@dataclass
class PageRecipe:
    name: str
    ingredients: list[str]
    steps: list[tuple[str, str]]  # (group, text)
    makes: int | None = None
    minutes: int | None = None
    site: str = ""
    notes: list[str] = field(default_factory=list)


def _types(node: dict[str, Any]) -> set[str]:
    kind = node.get("@type", "")
    kinds = kind if isinstance(kind, list) else [kind]
    return {str(k).rsplit("/", 1)[-1].lower() for k in kinds}


def _find_recipe(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        for item in data:
            if found := _find_recipe(item):
                return found
        return None
    if not isinstance(data, dict):
        return None
    if "recipe" in _types(data):
        return data
    for key in ("@graph", "mainEntity", "itemListElement"):
        if key in data and (found := _find_recipe(data[key])):
            return found
    return None


def _text(value: Any) -> str:
    if isinstance(value, str):
        spaced = re.sub(r"<(?:br|/p|/li|/div)\s*/?>", " ", value, flags=re.IGNORECASE)
        return " ".join(re.sub(r"<[^>]+>", "", spaced).split())
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or "")
    return ""


def _steps(value: Any, group: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(group, line) for line in (_text(p) for p in re.split(r"\n+", value)) if line]
    if isinstance(value, list):
        out: list[tuple[str, str]] = []
        for item in value:
            out.extend(_steps(item, group))
        return out
    if isinstance(value, dict):
        if "howtosection" in _types(value):
            name = _text(value.get("name", ""))
            return _steps(value.get("itemListElement", []), name)
        if "itemListElement" in value and "text" not in value:
            return _steps(value["itemListElement"], group)
        text = _text(value)
        return [(group, text)] if text else []
    return []


def _makes(value: Any) -> int | None:
    values = value if isinstance(value, list) else [value]
    for item in values:
        found = re.search(r"\d+", str(item))
        if found and 0 < int(found.group(0)) <= 200:
            return int(found.group(0))
    return None


def _minutes(value: Any) -> int | None:
    found = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", str(value or "").strip())
    if not found or not any(found.groups()):
        return None
    return int(found.group(1) or 0) * 60 + int(found.group(2) or 0)


def schema_recipe(html: str, url: str) -> PageRecipe | None:
    """The page's schema.org Recipe, if it has one with ingredients and steps."""
    for block in scan(html).json_blocks:
        cleaned = block.strip().removeprefix("<!--").removesuffix("-->").strip()
        cleaned = cleaned.removeprefix("//<![CDATA[").removesuffix("//]]>").strip()
        try:
            data = json.loads(cleaned)
        except ValueError:
            continue
        recipe = _find_recipe(data)
        if recipe is None:
            continue
        ingredients = [t for t in (_text(i) for i in recipe.get("recipeIngredient") or []) if t]
        steps = _steps(recipe.get("recipeInstructions") or [])
        if ingredients and steps:
            return PageRecipe(
                name=_text(recipe.get("name") or "") or "A recipe",
                ingredients=ingredients,
                steps=steps,
                makes=_makes(recipe.get("recipeYield")),
                minutes=_minutes(recipe.get("totalTime")),
                site=(urlsplit(url).hostname or "").removeprefix("www."),
            )
    return None
