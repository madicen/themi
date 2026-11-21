"""PT1: tracking numbers in shipping emails (the Themi Package Tracking Plan, Part 1).

Code finds the numbers, not the model: triage is only told which numbers an email holds
and may match them to parcels (PT2). `find` searches an email's whole text and its link
addresses, a redirect link's target once (decoded, never followed), and keeps a number only
when its pattern and check digit both hold.

    find("Tracking number: 1Z5R89390357567127", (), "orders@chewy.example")
    # [Found(carrier="ups", number="1Z5R89390357567127")]

The patterns and check digits come from Jeff Keen's `tracking_number_data` (MIT), vendored
in `tracking_data/` with its licence and the release it came from (`SOURCE.md`). Only UPS,
USPS, FedEx and Amazon Logistics are used; UPS freight waybills and Amazon's international
numbers are left out (a letter and ten digits match too much ordinary text).

Numbers with a fixed prefix (UPS `1Z`, Amazon `TBA`, USPS `92`-`95`, FedEx `96`) count on
their own. A bare run of digits (FedEx 12 and 15, USPS 20, ...) passes its check digit one
time in ten by chance, so it counts only with a word like "tracking" or a carrier's name on
its line or the lines next to it (or in the link it came from). When two carriers' patterns
fit the same digits, one with a fixed prefix wins (USPS `420` + ZIP + `92...` also passes
FedEx's 34-digit check); otherwise the sender or a carrier named nearby decides; failing
that, both are kept and the first lookup that answers settles it (PT5).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

CARRIERS = ("ups", "usps", "fedex", "amazon")
LEFT_OUT = frozenset({"UPS Waybill", "Amazon International"})  # by the data's `name`
# Kinds with a fixed prefix, trusted without a nearby word (by the data's `id`).
STRONG = frozenset(
    {"ups", "amazon_logistics", "usps_impb_n", "usps_impb_c", "fedex_ground_96", "fedex_ground_gsn"}
)
CONTEXT = re.compile(r"track|\bups\b|ups\.com|usps|postal|fedex|shipment|waybill", re.IGNORECASE)
HINTS = {
    "ups": re.compile(r"\bups\b|ups\.com", re.IGNORECASE),
    "usps": re.compile(r"usps|postal service|informed delivery", re.IGNORECASE),
    "fedex": re.compile(r"fedex", re.IGNORECASE),
    "amazon": re.compile(r"amazon", re.IGNORECASE),
}
REDIRECT_KEYS = frozenset({"url", "u", "redirect", "target"})
URL = re.compile(r"https?://[^\s<>\"']+")
MAX_TEXT = 60_000  # characters of an email searched
MAX_LINE = 4_000  # characters of one line or link searched
MAX_LINKS = 300
MAX_FOUND = 12


@dataclass(frozen=True)
class Found:
    carrier: str  # one of CARRIERS
    number: str  # as the carrier writes it, no spaces: "1Z5R89390357567127"

    def as_json(self) -> dict[str, str]:
        return {"carrier": self.carrier, "number": self.number}


@dataclass(frozen=True)
class Kind:
    carrier: str
    id: str
    pattern: re.Pattern[str]
    check: Callable[[str, str], bool] | None
    prepend: tuple[re.Pattern[str], str] | None
    strong: bool


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    number: str
    start: int
    end: int


def _python_regex(parts: str | list[str]) -> str:
    text = "".join(parts) if isinstance(parts, list) else parts
    return re.sub(r"\(\?<(?=[A-Za-z])", "(?P<", text)  # Ruby's named groups


def mod10(seq: str, check: str, extras: dict[str, Any]) -> bool:
    """The data set's mod 10, as its Ruby reference has it: letters count (ord - 3) % 10."""
    chars = list(reversed(seq)) if extras.get("reverse") else list(seq)
    total = 0
    for i, c in enumerate(chars):
        x = int(c) if c.isdigit() else (ord(c) - 3) % 10
        if extras.get("odds_multiplier") and i % 2 == 1:
            x *= int(extras["odds_multiplier"])
        elif extras.get("evens_multiplier") and i % 2 == 0:
            x *= int(extras["evens_multiplier"])
        total += x
    digit = total % 10
    digit = 10 - digit if digit else 0
    return check.isdigit() and digit == int(check)


def sum_product(seq: str, check: str, extras: dict[str, Any]) -> bool:
    weights = extras.get("weightings") or []
    total = sum(int(a) * b for a, b in zip(seq, weights, strict=False) if a.isdigit())
    return check.isdigit() and total % extras["modulo1"] % extras["modulo2"] == int(check)


CHECKS: dict[str, Callable[[str, str, dict[str, Any]], bool]] = {
    "mod10": mod10,
    "sum_product_with_weightings_and_modulo": sum_product,
}


def _kind(carrier: str, raw: dict[str, Any]) -> Kind | None:
    validation = raw.get("validation") or {}
    checksum = validation.get("checksum")
    check: Callable[[str, str], bool] | None = None
    if checksum:
        how = CHECKS.get(checksum["name"])
        if how is None:
            return None  # a check digit this module doesn't know: never guess
        check = lambda seq, digit, how=how, extras=checksum: how(seq, digit, extras)  # noqa: E731
    prepend = None
    if fmt := (validation.get("serial_number_format") or {}).get("prepend_if"):
        prepend = (re.compile(_python_regex(fmt["matches_regex"])), str(fmt["content"]))
    body = _python_regex(raw["regex"])
    pattern = re.compile(rf"(?<![A-Z0-9])(?:{body})(?![A-Z0-9])")
    ident = str(raw.get("id") or raw["name"])
    return Kind(carrier, ident, pattern, check, prepend, ident in STRONG)


@cache
def kinds() -> tuple[Kind, ...]:
    """Every kind of number Themi looks for, from the vendored data."""
    root = resources.files("themi_google") / "tracking_data"
    found: list[Kind] = []
    for carrier in CARRIERS:
        data = json.loads((root / f"{carrier}.json").read_text(encoding="utf-8"))
        for raw in data["tracking_numbers"]:
            if raw["name"] in LEFT_OUT:
                continue
            kind = _kind(carrier, raw)
            if kind is not None:
                found.append(kind)
    return tuple(found)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _valid(kind: Kind, m: re.Match[str]) -> bool:
    if kind.check is None:
        return True
    groups = m.groupdict()
    serial, digit = (
        _squash(groups.get("SerialNumber") or ""),
        _squash(groups.get("CheckDigit") or ""),
    )
    if not serial or not digit:
        return False
    if kind.prepend is not None and kind.prepend[0].match(serial):
        serial = kind.prepend[1] + serial
    return kind.check(serial, digit)


def _number(m: re.Match[str]) -> str:
    """The number to track: a USPS routing prefix (420 and a ZIP code) left off."""
    groups = m.groupdict()
    if groups.get("RoutingApplicationId") and groups.get("SerialNumber") is not None:
        return _squash(m.string[m.start("SerialNumber") : m.end("CheckDigit")])
    return _squash(m.group(0))


def candidates(text: str) -> list[Candidate]:
    """Every pattern match in one line whose check digit holds, longest first."""
    upper = text[:MAX_LINE].upper()
    out = [
        Candidate(kind, _number(m), m.start(), m.end())
        for kind in kinds()
        for m in kind.pattern.finditer(upper)
        if _valid(kind, m)
    ]
    return sorted(out, key=lambda c: (-(c.end - c.start), c.start))


def _pick(found: list[Candidate], context: str, sender: str) -> list[Found]:
    """Drop a match inside a longer one, weak kinds without a nearby word, and settle a
    clash (two carriers on the same digits) by the sender or a carrier named nearby."""
    has_context = bool(CONTEXT.search(context))
    taken: list[tuple[int, int]] = []
    groups: dict[tuple[int, int], list[Candidate]] = {}
    for c in found:
        span = (c.start, c.end)
        if span not in groups and any(s <= c.start and c.end <= e for s, e in taken):
            continue
        if not c.kind.strong and not has_context:
            continue
        if span not in groups:
            taken.append(span)
            groups[span] = []
        groups[span].append(c)
    out: list[Found] = []
    for group in groups.values():
        if any(c.kind.strong for c in group):  # a fixed prefix is the surer reading
            group = [c for c in group if c.kind.strong]
        carriers = {c.kind.carrier for c in group}
        if len(carriers) > 1:
            hinted = {
                name
                for name in carriers
                if HINTS[name].search(sender) or HINTS[name].search(context)
            }
            if len(hinted) == 1:
                group = [c for c in group if c.kind.carrier in hinted]
        for c in group:
            out.append(Found(c.kind.carrier, c.number))
    return out


def _link_texts(links: Iterable[str]) -> list[str]:
    """Each link as text to search, and a redirect's target once, decoded. Nothing is
    fetched."""
    out: list[str] = []
    for link in list(links)[:MAX_LINKS]:
        link = link[:MAX_LINE]
        out.append(unquote(link))
        try:
            query = urlsplit(link).query
        except ValueError:
            continue
        for key, value in parse_qsl(query, keep_blank_values=False):
            if key.lower() in REDIRECT_KEYS and value:
                out.append(unquote(value))
    return out


def find(text: str, links: Sequence[str] = (), sender: str = "") -> list[Found]:
    """The tracking numbers in an email: its text (all of it, up to MAX_TEXT), its links
    and the links written out in the text. In the order found, each once."""
    lines = text[:MAX_TEXT].splitlines()
    seen: dict[tuple[str, str], Found] = {}

    def keep(found: Iterable[Found]) -> None:
        for f in found:
            seen.setdefault((f.carrier, f.number), f)

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        context = " ".join(lines[max(0, i - 1) : i + 2])
        keep(_pick(candidates(line), context, sender))
    written = [u for line in lines for u in URL.findall(line)]
    for link in _link_texts([*links, *written]):
        keep(_pick(candidates(link), link, sender))
    return list(seen.values())[:MAX_FOUND]


def as_json(found: Iterable[Found]) -> str:
    return json.dumps([f.as_json() for f in found])


def from_json(raw: str | None) -> list[Found]:
    """An email row's `tracking`, back as Founds; anything malformed is left out."""
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    out: list[Found] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("carrier") in CARRIERS and item.get("number"):
            out.append(Found(str(item["carrier"]), str(item["number"])))
    return out
