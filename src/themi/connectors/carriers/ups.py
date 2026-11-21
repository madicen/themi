"""PT4: UPS's Tracking API (developer.ups.com; the shapes are from UPS's published OpenAPI
files, github.com/UPS-API/api-documentation, `Tracking.yaml` and
`OAuthClientCredentials.yaml`).

- A token: POST /security/v1/oauth/token with the app's client ID and secret as Basic auth
  and `grant_type=client_credentials`; it lasts `expires_in` seconds.
- A parcel: GET /api/track/v1/details/{number}, with the token and the `transId` and
  `transactionSrc` headers UPS asks for.

How UPS's answer becomes a `Tracking` (`STATUS_TYPES` is the one table to change):
`currentStatus.type` D is delivered and X an exception (a problem, in its description's
words); "Out For Delivery" in the description is out for delivery; anything else is on its
way, and an unknown type is logged. The day is the rescheduled delivery date (RDD), else
the scheduled one (SDD); a window is an estimated, confirmed or imminent delivery window
(EDW, CDW, IDW). Where it was left is `deliveryInformation.location`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
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

UPS_URL = "https://onlinetools.ups.com"
# currentStatus.type -> a status; anything else is on its way (and logged when it's new).
STATUS_TYPES = {"D": "delivered", "X": "problem", "I": "on_the_way", "P": "on_the_way",
                "M": "on_the_way", "O": "out_for_delivery"}  # fmt: skip
WINDOWS = ("IDW", "CDW", "EDW")  # imminent, confirmed, estimated: the surest first


def _day(raw: object) -> date | None:
    try:
        digits = str(raw or "")
        return date.fromisoformat(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}")
    except ValueError:
        return None


def _when(activity: dict[str, Any]) -> datetime | None:
    """An activity's moment: its local date and time with its GMT offset, else GMT."""
    day, time = str(activity.get("date") or ""), str(activity.get("time") or "").zfill(6)
    offset = str(activity.get("gmtOffset") or "")
    try:
        sign = -1 if offset.startswith("-") else 1
        hours, minutes = (int(x) for x in offset.lstrip("+-").split(":"))
        zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return datetime.strptime(day + time + offset.replace(":", ""), "%Y%m%d%H%M%S%z").astimezone(
            zone
        )
    except ValueError:
        pass
    gmt_day, gmt_time = str(activity.get("gmtDate") or ""), str(activity.get("gmtTime") or "")
    try:
        clock_part = gmt_time.replace(":", "").zfill(6)
        return datetime.strptime(gmt_day + clock_part + "+0000", "%Y%m%d%H%M%S%z").astimezone(UTC)
    except ValueError:
        return None


def tracking_from(data: dict[str, Any]) -> Tracking:
    """UPS's answer for one number as a `Tracking`. NotFound when it holds no package."""
    try:
        package = data["trackResponse"]["shipment"][0]["package"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise NotFound("UPS's answer has no package") from exc
    current = package.get("currentStatus") or {}
    kind = str(current.get("type") or "")
    words = f"{current.get('description') or ''} {current.get('simplifiedTextDescription') or ''}"
    status = STATUS_TYPES.get(kind)
    if status is None:
        log.info("UPS status type %r (%s): counted as on its way", kind, text(words))
        status = "on_the_way"
    if status == "on_the_way" and "out for delivery" in words.lower():
        status = "out_for_delivery"
    dates = {d.get("type"): _day(d.get("date")) for d in package.get("deliveryDate") or []}
    expected = dates.get("DEL") or dates.get("RDD") or dates.get("SDD")
    window = package.get("deliveryTime") or {}
    start = end = ""
    if window.get("type") in WINDOWS:
        start, end = hhmm(window.get("startTime")), hhmm(window.get("endTime"))
        if not (start and end):
            start = end = ""
    moments = [m for m in (_when(a) for a in package.get("activity") or []) if m]
    newest = max(moments, default=None)
    delivered_at = None
    if status == "delivered":
        scans = [
            a for a in package.get("activity") or [] if (a.get("status") or {}).get("type") == "D"
        ]
        delivered_at = _when(scans[0]) if scans else newest
    services = f"{package.get('additionalServices') or ''} {package.get('service') or ''}"
    return Tracking(
        status=status,
        expected_day=expected,
        window_start=start,
        window_end=end,
        problem=text(current.get("description")) if status == "problem" else "",
        delivered_at=delivered_at,
        left_at=text((package.get("deliveryInformation") or {}).get("location")),
        last_event_at=newest,
        signature="signature" in services.lower(),
    )


class UpsClient:
    name = "ups"
    tally: Tally = NO_TALLY  # UC3: set by the module

    def __init__(
        self,
        client_id: str,
        client_secret: Secret,
        *,
        base_url: str = UPS_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
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
                    f"{self.base_url}/security/v1/oauth/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self.client_id, self.client_secret.reveal()),
                )
        except httpx.HTTPError as exc:
            raise CarrierError(f"UPS sign-in: {type(exc).__name__}") from exc
        self.tally(response.status_code)
        if response.status_code in (400, 401, 403):
            raise CarrierError("UPS turned the client ID and secret down")
        if response.status_code != 200:
            raise CarrierError(f"UPS sign-in: HTTP {response.status_code}")
        try:
            body = response.json()
            return str(body["access_token"]), int(body.get("expires_in") or 3600)
        except (ValueError, KeyError, TypeError) as exc:
            raise CarrierError("UPS sign-in: an answer without a token") from exc

    async def check(self) -> None:
        self.token.forget()
        await self.token.get()

    async def track(self, number: str) -> Tracking:
        for attempt in (1, 2):
            token = await self.token.get()
            try:
                async with self._client() as client:
                    response = await client.get(
                        f"{self.base_url}/api/track/v1/details/{number}",
                        params={"locale": "en_US"},
                        headers={
                            "Authorization": f"Bearer {token}",
                            "transId": uuid.uuid4().hex,
                            "transactionSrc": "themi",
                        },
                    )
            except httpx.HTTPError as exc:
                raise CarrierError(f"UPS: {type(exc).__name__}") from exc
            self.tally(response.status_code)
            if response.status_code == 401 and attempt == 1:
                self.token.forget()  # it ran out early: once more with a new one
                continue
            if response.status_code == 404:
                raise NotFound("UPS doesn't know the number")
            if response.status_code != 200:
                raise CarrierError(f"UPS: HTTP {response.status_code}")
            try:
                return tracking_from(response.json())
            except ValueError as exc:
                raise CarrierError("UPS: an answer that isn't JSON") from exc
        raise CarrierError("UPS kept refusing the token")  # pragma: no cover
