"""PT4: what every carrier client shares: the answer (`Tracking`), the error, the protocol,
and an OAuth client-credentials token kept until it runs out."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from themi import clock

log = logging.getLogger(__name__)

STATUSES = ("on_the_way", "out_for_delivery", "problem", "delivered")
MAX_TEXT = 80  # a carrier's free text (a problem, where it was left), cut to this
TIMEOUT = 15.0
EARLY = timedelta(minutes=2)  # a token this close to running out is asked for again


class CarrierError(Exception):
    """No answer this time (a 429, a 5xx, a timeout, a bad answer): try again later."""


class NotFound(CarrierError):
    """The carrier doesn't know the number (yet, or it's another carrier's)."""


@dataclass(frozen=True)
class Tracking:
    """What a carrier says about one parcel. Free text is cut to MAX_TEXT and is shown as
    plain text, never given to a model."""

    status: str  # one of STATUSES
    expected_day: date | None = None
    window_start: str = ""  # "14:15", local to the delivery; "" for none
    window_end: str = ""
    problem: str = ""  # "Delivery attempted"; "" unless status is "problem"
    delivered_at: datetime | None = None
    left_at: str = ""  # "Front Door"
    last_event_at: datetime | None = None  # when the newest scan happened
    signature: bool = False  # someone has to sign for it


class Carrier(Protocol):
    name: str  # "ups", "usps"

    async def track(self, number: str) -> Tracking: ...

    async def check(self) -> None:
        """Ask for a token, raising CarrierError when the keys don't work (Test)."""
        ...


def text(value: object) -> str:
    """A carrier's free text, tidied and cut."""
    return " ".join(str(value or "").split())[:MAX_TEXT]


def hhmm(value: object) -> str:
    """ "141500", "14:15:00" or "2:15 PM" as "14:15"; "" for anything else."""
    raw = str(value or "").strip().upper()
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})(?::?\d{2})?\s*(AM|PM)?", raw)
    if not m:
        return ""
    hour, minute = int(m[1]), int(m[2])
    if m[3] == "PM" and hour < 12:
        hour += 12
    if m[3] == "AM" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


class Token:
    """An OAuth access token, asked for again a little before it runs out, or after a 401."""

    def __init__(self, fetch: Callable[[], Awaitable[tuple[str, int]]]) -> None:
        self.fetch = fetch  # -> (token, seconds it lasts)
        self.value = ""
        self.until: datetime | None = None

    async def get(self) -> str:
        now = clock.now()
        if not self.value or self.until is None or now >= self.until - EARLY:
            value, seconds = await self.fetch()
            self.value, self.until = value, now + timedelta(seconds=max(seconds, 60))
        return self.value

    def forget(self) -> None:
        self.value, self.until = "", None
