"""Fake UPS and USPS tracking services (PT4), over `httpx.MockTransport`.

    fake_carriers.answer("ups", "1Z...", "ups_out_for_delivery")   # a fixture's answer
    fake_carriers.fail("usps", 429, times=2)                       # the next two answer 429
    fake_carriers.timeout("ups")                                   # the next one times out
    fake_carriers.clients()                                        # {"ups": ..., "usps": ...}
    fake_carriers.tracked("ups")                                   # numbers asked about

Answers are the JSON files in `tests/fixtures/carriers/` (in each carrier's published
shape), with NUMBER replaced. A number nobody set answers 404. Tokens are handed out with
the client ID and secret below and last an hour; `revoke()` makes the current ones fail
once with 401, as an expired token does. Without the `fake_carriers` fixture a scenario
gets no carriers, so no test reaches the real services.
"""

from __future__ import annotations

import base64
import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from themi.connectors.carriers import UpsClient, UspsClient
from themi.storage.secrets import Secret

FIXTURES = Path(__file__).parents[1] / "fixtures" / "carriers"
UPS_URL = "https://ups.fake"
USPS_URL = "https://usps.fake"
UPS_ID, UPS_SECRET = "ups-client", "ups-secret"
USPS_KEY, USPS_SECRET = "usps-key", "usps-secret"


def fixture(name: str, number: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text().replace("NUMBER", number))


class FakeCarriers:
    def __init__(self) -> None:
        self.answers: dict[tuple[str, str], str] = {}
        self.failures: dict[str, list[int]] = {"ups": [], "usps": []}
        self.timeouts: Counter[str] = Counter()
        self.revoked: set[str] = set()
        self.tokens: Counter[str] = Counter()
        self.requests: list[tuple[str, str]] = []  # (carrier, number) for each lookup
        self._issued = 0
        self._valid: dict[str, str] = {}

    # ----- scripting ------------------------------------------------------------------

    def answer(self, carrier: str, number: str, name: str) -> None:
        self.answers[(carrier, number)] = name

    def fail(self, carrier: str, status: int, *, times: int = 1) -> None:
        self.failures[carrier] += [status] * times

    def timeout(self, carrier: str, times: int = 1) -> None:
        self.timeouts[carrier] += times

    def revoke(self, carrier: str) -> None:
        self.revoked.add(carrier)

    def tracked(self, carrier: str) -> list[str]:
        return [n for c, n in self.requests if c == carrier]

    def clients(self) -> dict[str, Any]:
        return {
            "ups": UpsClient(
                UPS_ID, Secret(UPS_SECRET), base_url=UPS_URL, transport=self.transport("ups")
            ),
            "usps": UspsClient(
                USPS_KEY, Secret(USPS_SECRET), base_url=USPS_URL, transport=self.transport("usps")
            ),
        }

    def transport(self, carrier: str) -> httpx.MockTransport:
        handle = self._ups if carrier == "ups" else self._usps
        return httpx.MockTransport(lambda request: self._guard(carrier, request, handle))

    # ----- serving --------------------------------------------------------------------

    def _guard(self, carrier: str, request: httpx.Request, handle: Any) -> httpx.Response:
        if self.timeouts[carrier]:
            self.timeouts[carrier] -= 1
            raise httpx.ReadTimeout("fake timeout", request=request)
        if self.failures[carrier]:
            return httpx.Response(self.failures[carrier].pop(0), json={"error": "fake"})
        return handle(request)

    def _token(self, carrier: str) -> httpx.Response:
        self._issued += 1
        token = f"{carrier}-token-{self._issued}"
        self._valid[carrier] = token
        self.tokens[carrier] += 1
        self.revoked.discard(carrier)
        return httpx.Response(
            200, json={"access_token": token, "expires_in": "3599", "token_type": "Bearer"}
        )

    def _authorised(self, carrier: str, request: httpx.Request) -> bool:
        given = request.headers.get("Authorization", "")
        return carrier not in self.revoked and given == f"Bearer {self._valid.get(carrier)}"

    def _ups(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/security/v1/oauth/token":
            expected = base64.b64encode(f"{UPS_ID}:{UPS_SECRET}".encode()).decode()
            if request.headers.get("Authorization") != f"Basic {expected}":
                return httpx.Response(401, json={"response": {"errors": [{"code": "250003"}]}})
            return self._token("ups")
        if path.startswith("/api/track/v1/details/"):
            if not (request.headers.get("transId") and request.headers.get("transactionSrc")):
                return httpx.Response(400, json={"response": {"errors": [{"code": "x"}]}})
            if not self._authorised("ups", request):
                return httpx.Response(401, json={"response": {"errors": [{"code": "250002"}]}})
            number = path.rsplit("/", 1)[-1]
            self.requests.append(("ups", number))
            name = self.answers.get(("ups", number))
            if name is None:
                return httpx.Response(404, json={"response": {"errors": [{"code": "151018"}]}})
            return httpx.Response(200, json=fixture(name, number))
        return httpx.Response(404)

    def _usps(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth2/v3/token":
            body = json.loads(request.content or b"{}")
            if (body.get("client_id"), body.get("client_secret")) != (USPS_KEY, USPS_SECRET):
                return httpx.Response(401, json={"error": "invalid_client"})
            return self._token("usps")
        if path == "/tracking/v3r2/tracking":
            if not self._authorised("usps", request):
                return httpx.Response(401, json={"error": {"code": "401"}})
            [asked] = json.loads(request.content)
            number = asked["trackingNumber"]
            self.requests.append(("usps", number))
            name = self.answers.get(("usps", number), "usps_not_found")
            status = 207 if name == "usps_not_found" else 200
            return httpx.Response(status, json=fixture(name, number))
        return httpx.Response(404)


@pytest.fixture
def fake_carriers() -> FakeCarriers:
    return FakeCarriers()
