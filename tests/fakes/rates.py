"""A fake Frankfurter (F50b): the ECB's daily exchange rates.

    fake_rates.set("HKD", 0.1285)   # one HKD buys 0.1285 USD, any day
    fake_rates.fail = True          # every request answers 500
    fake_rates.count()              # how many requests came

A currency without a rate answers 404, as Frankfurter does for one it doesn't have. The
scenario harness hands Themi a client over this transport; without the `fake_rates`
fixture it gets an empty one, so no test reaches the real service.
"""

from __future__ import annotations

import json

import httpx
import pytest

from themi.connectors.rates import FRANKFURTER_URL, FrankfurterClient


class FakeRates:
    def __init__(self) -> None:
        self.rates: dict[str, float] = {}
        self.fail = False
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def set(self, currency: str, usd: float) -> None:
        self.rates[currency] = usd

    def client(self) -> FrankfurterClient:
        return FrankfurterClient(FRANKFURTER_URL, transport=self.transport)

    def count(self) -> int:
        return len(self.requests)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(500, text="nope")
        base = request.url.params.get("from", "")
        quote = request.url.params.get("to", "")
        day = request.url.path.rsplit("/", 1)[-1]
        if base not in self.rates or quote != "USD":
            return httpx.Response(404, text=json.dumps({"message": "not found"}))
        body = {"amount": 1.0, "base": base, "date": day, "rates": {quote: self.rates[base]}}
        return httpx.Response(200, json=body)


@pytest.fixture
def fake_rates() -> FakeRates:
    return FakeRates()
