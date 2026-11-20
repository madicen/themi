"""Amounts in other currencies (F50b, bug #232: "HK$816.00" was read as $816.00).

`find_money` reads every amount in a text with its currency: a sign before it ("$",
"HK$", "€", "£"), or a code before or after it ("EUR 12.00", "12,00 EUR"). A bare "$" is
the family's dollars (US dollars: Themi has no other home currency yet). `Converter` turns
one into dollars at the day's rate, kept in `exchange_rates` so a day's rate is asked once.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from themi import clock
from themi.connectors.rates import RateError, RateSource
from themi.localtime import to_utc_iso
from themi.usage import Meter

if TYPE_CHECKING:
    from themi.storage.db import Database

log = logging.getLogger(__name__)

HOME = "USD"
FRANKFURTER_METER = Meter(
    "frankfurter.calls", "Exchange rates (Frankfurter)", "calls", group="Web", order=32
)

# Written before the figure. Longest first, so "HK$" is read as itself, not "$".
SIGNS: dict[str, str] = {
    "US$": "USD", "HK$": "HKD", "CA$": "CAD", "C$": "CAD", "AU$": "AUD", "A$": "AUD",
    "NZ$": "NZD", "NT$": "TWD", "MX$": "MXN", "S$": "SGD", "R$": "BRL", "JP¥": "JPY",
    "CN¥": "CNY", "$": HOME, "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "₩": "KRW",
}  # fmt: skip
CODES = frozenset(
    "USD EUR GBP CAD AUD NZD HKD JPY CNY CHF SEK NOK DKK SGD MXN INR TWD KRW BRL ZAR PLN "
    "CZK HUF ILS THB".split()
)
# How each is written back: its sign where it has one of its own, else its code.
WRITTEN = {code: sign for sign, code in reversed(SIGNS.items())} | {HOME: "$"}

_SIGN = "|".join(re.escape(s) for s in sorted(SIGNS, key=len, reverse=True))
_CODE = "|".join(sorted(CODES))
# 1,112.40  816.00  1.234,56  12,00  269: thousands in threes, then two decimals or none
_NUMBER = r"(?P<int>\d{1,3}(?:[,.]\d{3})+|\d+)(?:[.,](?P<dec>\d{2}))?(?!\d)"
MONEY = re.compile(
    rf"(?:(?<![A-Za-z])(?P<sign>{_SIGN})|\b(?P<code>{_CODE})\s?)\s?{_NUMBER}"
    rf"|(?<![\d.,]){_NUMBER.replace('?P<int>', '?P<int2>').replace('?P<dec>', '?P<dec2>')}"
    rf"\s?(?P<after>{_CODE})\b"
)


@dataclass(frozen=True)
class Money:
    value: Decimal
    currency: str  # ISO code

    @property
    def cents(self) -> int:
        return int(self.value * 100)

    @property
    def foreign(self) -> bool:
        return self.currency != HOME

    def words(self) -> str:
        """HK$816.00, €12.00, CHF 40.00."""
        figure = f"{self.value:,.2f}"
        mark = WRITTEN.get(self.currency)
        return f"{mark}{figure}" if mark else f"{self.currency} {figure}"


@dataclass(frozen=True)
class Found:
    money: Money
    start: int
    end: int


def find_money(text: str) -> list[Found]:
    """Every amount in `text`, with its currency, in order."""
    out = []
    for match in MONEY.finditer(text):
        if match.group("after"):
            whole, dec, currency = match.group("int2"), match.group("dec2"), match["after"]
        else:
            whole, dec = match.group("int"), match.group("dec")
            sign = match.group("sign")
            currency = SIGNS[sign] if sign else str(match.group("code"))
        value = Decimal(re.sub(r"[,.]", "", whole)) + Decimal(dec or 0) / 100
        out.append(Found(Money(value, currency), match.start(), match.end()))
    return out


def written_as(cents: int, text: str) -> list[Money]:
    """The amounts in `text` that are this figure (in hundredths), whatever the currency."""
    return [f.money for f in find_money(text) if f.money.cents == cents]


def about(cents: int) -> str:
    """$105 for 10486: what a converted amount comes to, in round dollars."""
    return f"${round(cents / 100):,}"


class Converter:
    """Foreign amounts in dollars, at the rate on the day."""

    def __init__(self, db: Database, source: RateSource) -> None:
        self.db = db
        self.source = source

    async def to_dollars(self, money: Money, day: date) -> int | None:
        """`money` in cents of dollars on `day`, or None when there's no rate to be had."""
        if not money.foreign:
            return money.cents
        rate = await self.rate(day, money.currency)
        return None if rate is None else round(money.value * Decimal(str(rate)) * 100)

    async def rate(self, day: date, currency: str) -> float | None:
        row = self.db.one(
            "SELECT rate FROM exchange_rates WHERE day = ? AND base = ? AND quote = ?",
            (day.isoformat(), currency, HOME),
        )
        if row is not None:
            return float(row["rate"])
        try:
            rate = await self.source.rate(day, currency, HOME)
        except RateError as exc:
            log.warning("No exchange rate for %s on %s: %s", currency, day, exc)
            return None
        self.db.execute(
            "INSERT OR REPLACE INTO exchange_rates (day, base, quote, rate, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (day.isoformat(), currency, HOME, rate, to_utc_iso(clock.now())),
        )
        return rate


async def in_dollars(converter: Converter | None, cents: int, text: str, day: date) -> int | None:
    """A model's figure with no currency (a receipt's total, in hundredths): dollars, unless
    the receipt writes that figure only in another currency. Then converted, or None
    without a rate (left out rather than counted as dollars)."""
    found = written_as(cents, text)
    if not found or any(not m.foreign for m in found):
        return cents
    return await converter.to_dollars(found[0], day) if converter is not None else None
