"""How sure Themi is, and whether two things are the same spend (EX2a). Pure functions, easy
to tune.

Confidence is set here, by code, never by a model (a model's own "95%" is never used):
- a receipt whose amount, date and vendor match an entry: 0.95;
- a calendar event on the entry's day that names the place or the reason: 0.6;
- what was said in the same conversation: 0.7.

Every value a model reads from text comes with a quote, and the quote must be found word for
word in that text (`quoted`), or the value isn't kept: unknown, never made up.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)

# (source, what matched) -> how sure
CONFIDENCE: dict[tuple[str, str], float] = {
    ("email_receipt", "amount date vendor"): 0.95,  # all three match an entry
    ("email_receipt", "new"): 0.95,  # read from the receipt itself, no entry yet
    ("calendar_event", "vendor"): 0.6,
    ("calendar_event", "purpose"): 0.6,
    ("chat_context", "said nearby"): 0.7,
}
SAME_SPEND = timedelta(days=2)  # a receipt and an entry this close are the same spend

# Delivery services and the like: "DoorDash - Merit" is Merit.
VIA = re.compile(
    r"^(?:doordash|door dash|uber ?eats|grubhub|postmates|caviar|seamless|instacart|"
    r"square|toast|sq \*|tst\*|paypal \*)\s*[-:*|/]+\s*",
    re.IGNORECASE,
)
VIA_AFTER = re.compile(r"\s*(?:via|through|on)\s+(?:doordash|uber ?eats|grubhub)\s*$", re.I)
FILLER = {"the", "restaurant", "inc", "llc", "ltd", "co", "cafe", "and", "&", "order", "from"}
MEAL_WORDS = re.compile(r"\b(lunch|dinner|breakfast|brunch|coffee|drinks|meal)\b", re.I)


def vendor_key(name: str) -> str:
    """A vendor's name for comparing: "DoorDash - Merit Kitchen, Inc." -> "merit kitchen"."""
    text = VIA_AFTER.sub("", VIA.sub("", " ".join(name.split())))
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return " ".join(w for w in words if w not in FILLER)


def same_vendor(a: str, b: str) -> bool:
    """The same place: equal once normalised, or one's words all in the other's."""
    ka, kb = vendor_key(a), vendor_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    wa, wb = set(ka.split()), set(kb.split())
    return wa <= wb or wb <= wa


def same_amount(a: int | None, b: int | None) -> bool:
    return a is not None and b is not None and a == b


def near(a: date | None, b: date | None, within: timedelta = SAME_SPEND) -> bool:
    return a is not None and b is not None and abs(a - b) <= within


@dataclass(frozen=True)
class Known:
    """What an entry (or a receipt) says about a spend: unknown is None."""

    amount: int | None
    on: date | None
    vendor: str | None


def match(entry: Known, receipt: Known, text: str = "") -> int:
    """How well a receipt matches an entry: 0 for not the same spend, else how many of
    amount, date and vendor agree. Each one the entry has must agree; the date always must,
    and at least one of amount or vendor too. A vendor agrees when the receipt's text names
    the entry's place, too ("Your order from Thai Place", from DoorDash)."""
    if not near(entry.on, receipt.on):
        return 0
    score = 1
    if entry.amount is not None:
        if not same_amount(entry.amount, receipt.amount):
            return 0
        score += 1
    if entry.vendor is not None:
        named = bool(text) and name_line(entry.vendor, text) is not None
        if not (receipt.vendor and same_vendor(entry.vendor, receipt.vendor)) and not named:
            return 0
        score += 1
    return score if score > 1 else 0


def best_match[T](receipt: Known, entries: Iterable[tuple[T, Known]], text: str = "") -> T | None:
    """The entry a receipt belongs to: the most that agree, then the closest date, then the
    newest. None when nothing matches."""
    best: tuple[int, int, int, T] | None = None
    for n, (entry, known) in enumerate(entries):
        score = match(known, receipt, text)
        if not score:
            continue
        assert known.on is not None and receipt.on is not None
        rank = (score, -abs((known.on - receipt.on).days), n)
        if best is None or rank > best[:3]:
            best = (*rank, entry)
    return best[3] if best else None


def _plain(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").split())


def quoted(quote: str, source: str) -> bool:
    """The quote is in the source, word for word (spacing and case aside)."""
    q = _plain(quote)
    return bool(q) and q in _plain(source)


def checked(value: Any, quote: str, source: str, *, what: str = "a value") -> Any:
    """`value` if its quote is found in `source`, else None (the miss is logged, never
    shown)."""
    if value is None:
        return None
    if quoted(quote, source):
        return value
    log.info("Dropped %s: its quote isn't in the text", what)
    return None


def money_forms(cents: int) -> list[str]:
    """How an amount may be written: 1234.5 -> "1,234.50", "1234.50"."""
    whole = f"{cents / 100:.2f}"
    return list(dict.fromkeys([f"{cents / 100:,.2f}", whole]))


def amount_line(cents: int, text: str) -> str | None:
    """The line of `text` where this amount is written, or None (then it isn't kept)."""
    forms = money_forms(cents)
    for line in text.splitlines():
        for form in forms:
            if re.search(rf"(?<![\d.,]){re.escape(form)}(?!\d)", line):
                return " ".join(line.split())[:200]
    return None


def name_line(name: str, text: str) -> str | None:
    """The line of `text` that names this vendor (once normalised), or None."""
    key = vendor_key(name)
    if not key:
        return None
    for line in text.splitlines():
        if key in vendor_key(line) or _plain(name) in _plain(line):
            return " ".join(line.split())[:200]
    return None


def event_vendor(title: str, location: str) -> str | None:
    """The place a calendar event is at: its location's first part, else "... at Merit"."""
    place = location.split(",")[0].strip()
    if place and not re.search(r"\d{2,}", place):  # a street address isn't a vendor
        return place[:80]
    found = re.search(r"\bat\s+([A-Z][\w'&]*(?:\s+[A-Z][\w'&]*){0,3})", title)
    return found.group(1)[:80] if found else None


def event_fits(title: str, location: str, clients: Iterable[str]) -> bool:
    """A calendar event that may be where a spend was: a meal, or with a client by name."""
    if MEAL_WORDS.search(title):
        return True
    words = _plain(f"{title} {location}")
    return any(c and re.search(rf"\b{re.escape(_plain(c))}\b", words) for c in clients)
