"""PT4: USPS's Tracking v3r2 (developers.usps.com; the shapes are from USPS's published
OpenAPI files, `tracking-v3r2` and `oauth2`). Tracking v3r2 is the one to build on: USPS
retires the older Tracking 3.0 on 31 July 2027.

- A token: POST https://apis.usps.com/oauth2/v3/token with the app's consumer key and
  secret as `client_id` and `client_secret`, `grant_type=client_credentials`.
- A parcel: POST /tracking/v3r2/tracking with `[{"trackingNumber": ...}]`; the answer is
  a list (200), or a list of successes and failures (207).

How USPS's answer becomes a `Tracking` (`CATEGORIES` is the one table to change): the
`statusCategory` says delivered, out for delivery or a problem ("Alert", "Delivery
Attempt", "Available for Pickup", "Return to Sender"), in its `status` words; anything else
is on its way, and an unknown category is logged. The day is the expected delivery date,
else the predicted one, with the predicted window; where it was left is what follows
"Delivered, " in the status ("Front Door/Porch").
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import httpx

from themi.connectors.carriers.base import (
    TIMEOUT,
    CarrierError,
    NotFound,
    Token,
    Tracking,
    hhmm,
    text,
)
from themi.http import tls
from themi.storage.secrets import Secret
from themi.usage import NO_TALLY, Tally

log = logging.getLogger(__name__)

USPS_URL = "https://apis.usps.com"
CATEGORIES = {
    "delivered": "delivered",
    "out for delivery": "out_for_delivery",
    "alert": "problem",
    "delivery attempt": "problem",
    "available for pickup": "problem",
    "return to sender": "problem",
    "pre-shipment": "on_the_way",
    "accepted": "on_the_way",
    "in transit": "on_the_way",
    "in-transit": "on_the_way",
}


def _day(raw: object) -> date | None:
    try:
        return date.fromisoformat(str(raw or "")[:10])
    except ValueError:
        return None


def _when(raw: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def _clock(raw: object) -> str:
    value = str(raw or "")
    return hhmm(value.split("T", 1)[1] if "T" in value else value)


def tracking_from(item: dict[str, Any]) -> Tracking:
    """One of USPS's answers as a `Tracking`. NotFound for a failure."""
    if "error" in item or str(item.get("statusCode") or "200") not in ("200", ""):
        raise NotFound("USPS doesn't know the number")
    category = " ".join(str(item.get("statusCategory") or "").lower().split())
    words = text(item.get("status"))
    status = CATEGORIES.get(category)
    if status is None:
        log.info("USPS status category %r (%s): counted as on its way", category, words)
        status = "on_the_way"
    expect = item.get("deliveryDateExpectation") or {}
    expected = _day(expect.get("expectedDeliveryDate")) or _day(expect.get("predictedDeliveryDate"))
    start = _clock(expect.get("predictedDeliveryWindowStartTime"))
    end = _clock(expect.get("predictedDeliveryWindowEndTime"))
    if not (start and end):
        start = end = ""
    events = [e for e in item.get("trackingEvents") or [] if isinstance(e, dict)]
    moments = [m for m in (_when(e.get("GMTTimestamp")) for e in events) if m]
    delivered_at = None
    left_at = ""
    if status == "delivered":
        scans = [e for e in events if str(e.get("eventType") or "").lower().startswith("delivered")]
        delivered_at = _when(scans[0].get("GMTTimestamp")) if scans else max(moments, default=None)
        if words.lower().startswith("delivered, "):
            left_at = words[len("delivered, ") :]
        expected = delivered_at.date() if delivered_at else expected
    services = " ".join(str(s) for s in item.get("services") or [])
    return Tracking(
        status=status,
        expected_day=expected,
        window_start=start,
        window_end=end,
        problem=words if status == "problem" else "",
        delivered_at=delivered_at,
        left_at=text(left_at),
        last_event_at=max(moments, default=None),
        signature="signature" in services.lower(),
    )


class UspsClient:
    name = "usps"
    tally: Tally = NO_TALLY  # UC3: set by the module

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: Secret,
        *,
        base_url: str = USPS_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout
        self.token = Token(self._fetch_token)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=self.timeout, verify=tls())

    async def _fetch_token(self) -> tuple[str, int]:
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self.base_url}/oauth2/v3/token",
                    json={
                        "grant_type": "client_credentials",
                        "client_id": self.consumer_key,
                        "client_secret": self.consumer_secret.reveal(),
                    },
                )
        except httpx.HTTPError as exc:
            raise CarrierError(f"USPS sign-in: {type(exc).__name__}") from exc
        self.tally(response.status_code)
        if response.status_code in (400, 401, 403):
            raise CarrierError("USPS turned the consumer key and secret down")
        if response.status_code != 200:
            raise CarrierError(f"USPS sign-in: HTTP {response.status_code}")
        try:
            body = response.json()
            return str(body["access_token"]), int(body.get("expires_in") or 3600)
        except (ValueError, KeyError, TypeError) as exc:
            raise CarrierError("USPS sign-in: an answer without a token") from exc

    async def check(self) -> None:
        self.token.forget()
        await self.token.get()

    async def track(self, number: str) -> Tracking:
        for attempt in (1, 2):
            token = await self.token.get()
            try:
                async with self._client() as client:
                    response = await client.post(
                        f"{self.base_url}/tracking/v3r2/tracking",
                        json=[{"trackingNumber": number}],
                        headers={"Authorization": f"Bearer {token}"},
                    )
            except httpx.HTTPError as exc:
                raise CarrierError(f"USPS: {type(exc).__name__}") from exc
            self.tally(response.status_code)
            if response.status_code == 401 and attempt == 1:
                self.token.forget()
                continue
            if response.status_code == 404:
                raise NotFound("USPS doesn't know the number")
            if response.status_code not in (200, 207):
                raise CarrierError(f"USPS: HTTP {response.status_code}")
            try:
                body = response.json()
            except ValueError as exc:
                raise CarrierError("USPS: an answer that isn't JSON") from exc
            items = body if isinstance(body, list) else [body]
            if not items or not isinstance(items[0], dict):
                raise CarrierError("USPS: an empty answer")
            return tracking_from(items[0])
        raise CarrierError("USPS kept refusing the token")  # pragma: no cover
