"""Exchange rates (F50b, bug #232): the ECB's daily reference rates through Frankfurter
(frankfurter.dev: free, no key). Plain HTTP over `httpx`; tests hand in a transport
(`tests/fakes/rates.py`).

    rate = await FrankfurterClient().rate(date(2026, 11, 19), "HKD", "USD")  # 0.1285

A day without rates (a weekend, a holiday) gets the last working day's, as Frankfurter
gives it. Anything else (a currency it doesn't have, a timeout, a bad answer) is a
`RateError`: the caller goes without.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

import httpx

from themi.http import tls
from themi.usage import NO_TALLY, Tally

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"
TIMEOUT = 5.0  # seconds: an email's alert doesn't wait longer for a rate


class RateError(Exception):
    pass


class RateSource(Protocol):
    async def rate(self, day: date, base: str, quote: str) -> float: ...


class FrankfurterClient:
    tally: Tally = NO_TALLY  # UC3: set by the module

    def __init__(
        self,
        base_url: str = FRANKFURTER_URL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout

    async def rate(self, day: date, base: str, quote: str) -> float:
        """How many `quote` one `base` bought on `day`."""
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout,
                verify=tls(),
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    f"{self.base_url}/{day.isoformat()}", params={"from": base, "to": quote}
                )
        except httpx.HTTPError as exc:
            raise RateError(f"{type(exc).__name__} asking for {base} in {quote}") from exc
        self.tally(response.status_code)
        if response.status_code != 200:
            raise RateError(f"HTTP {response.status_code} asking for {base} in {quote}")
        try:
            rate = float(response.json()["rates"][quote])
        except (ValueError, KeyError, TypeError) as exc:
            raise RateError(f"No {base} rate in {quote} in the answer") from exc
        if rate <= 0:
            raise RateError(f"A {base} rate of {rate}")
        return rate
