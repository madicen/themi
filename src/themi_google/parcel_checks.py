"""PT5: asking the carriers about parcels on a schedule (the Themi Package Tracking Plan,
Part 3, "When Themi asks").

`parcels.check` runs every 15 minutes, 7 am to 9 pm in the family's time zone, and asks
about at most `PER_RUN` parcels that are due a look, those never looked at first:

| Parcel                                   | Asked                    |
| ---------------------------------------- | ------------------------ |
| Just found by number, or news by email   | at the next run          |
| On the way, due later                    | every 6 hours            |
| Due today, or out for delivery           | every hour               |
| A problem                                | every 2 hours            |
| Delivered, or no news in 21 days         | never again              |
| Amazon, or no carrier with keys          | never: email only        |

A lookup is a read: it sends the tracking number only and goes through no trust tier. What
the carrier says is the newest fact (`Fact.at` is now), applied by `Deliveries.record`'s
rules; a parcel the carrier says nothing new about is only marked as looked at, so its
"no news" age keeps counting. A number that two carriers' patterns both fit is asked of
each carrier with keys until one knows it, which settles the carrier. A carrier that
fails (`CarrierError`) leaves the parcel for its next turn.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from themi import clock
from themi.connectors.carriers import Carrier, CarrierError, NotFound, Tracking
from themi.localtime import to_utc_iso
from themi_google.deliveries import Deliveries, Fact, Parcel

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

EVERY = timedelta(minutes=15)
PER_RUN = 20
STARTS, ENDS = time(7, 0), time(21, 0)
LATER = timedelta(hours=6)
SOON = timedelta(hours=1)
TROUBLE = timedelta(hours=2)
QUIET = timedelta(days=21)


class ParcelChecks:
    def __init__(self, deliveries: Deliveries, carriers: Mapping[str, Carrier]) -> None:
        self.deliveries = deliveries
        self.db = deliveries.db
        self.carriers = dict(carriers)

    # ----- what's due ---------------------------------------------------------------

    def askable(self, parcel: Parcel) -> list[str]:
        """The carriers with keys this parcel could be asked of; [] for none."""
        return [c for c in parcel.carriers if c in self.carriers]

    def pace(self, parcel: Parcel, now: datetime) -> timedelta | None:
        """How often it's asked about now; None for never again."""
        if parcel.status == "delivered" or not parcel.number or not self.askable(parcel):
            return None
        if now - parcel.updated_at > QUIET:
            return None
        if parcel.status == "problem":
            return TROUBLE
        today = now.astimezone(self.deliveries.tz()).date()
        if parcel.status == "out_for_delivery" or parcel.expected_day == today:
            return SOON
        return LATER

    def due(self, now: datetime) -> list[Parcel]:
        """The parcels due a look, never-looked-at and email news first, then the longest
        since their last look."""
        rows = self.db.query(
            "SELECT id, checked_at, look_after FROM parcels WHERE status != 'delivered' "
            "AND number != ''"
        )
        marks = {r["id"]: (r["checked_at"], r["look_after"]) for r in rows}
        found: list[tuple[int, datetime, Parcel]] = []
        for parcel in self.deliveries.parcels(marks):
            pace = self.pace(parcel, now)
            if pace is None:
                continue
            checked, look_after = marks[parcel.id]
            if checked is None or (look_after and datetime.fromisoformat(look_after) <= now):
                found.append((0, datetime.min.replace(tzinfo=now.tzinfo), parcel))
            elif now - datetime.fromisoformat(checked) >= pace:
                found.append((1, datetime.fromisoformat(checked), parcel))
        found.sort(key=lambda f: (f[0], f[1], f[2].id))
        return [p for _, _, p in found]

    # ----- the job ------------------------------------------------------------------

    async def run(self) -> int:
        """Scheduler job: ask about what's due. Returns how many parcels were looked up."""
        now = clock.now()
        local = now.astimezone(self.deliveries.tz()).time()
        if not (STARTS <= local < ENDS):
            return 0
        asked = 0
        for parcel in self.due(now)[:PER_RUN]:
            await self.look(parcel)
            asked += 1
        return asked

    async def look(self, parcel: Parcel) -> None:
        """Ask the parcel's carrier (each possible one, until one knows it)."""
        now = clock.now()
        try:
            for name in self.askable(parcel):
                try:
                    tracking = await self.carriers[name].track(parcel.number)
                except NotFound:
                    continue
                self._apply(parcel, name, tracking)
                return
        except CarrierError as exc:
            log.info("A carrier couldn't answer about parcel %s: %s", parcel.id, exc)
        finally:
            self.db.execute(
                "UPDATE parcels SET checked_at = ?, look_after = NULL WHERE id = ?",
                (to_utc_iso(now), parcel.id),
            )

    def _apply(self, parcel: Parcel, carrier: str, tracking: Tracking) -> None:
        fact = Fact(
            shop=parcel.shop,
            status=tracking.status,
            at=clock.now(),
            number=parcel.number,
            carriers=(carrier,),
            day=tracking.expected_day,
            problem=tracking.problem,
            source="lookup",
            window_start=tracking.window_start,
            window_end=tracking.window_end,
            delivered_at=tracking.delivered_at,
            left_at=tracking.left_at,
            signature=tracking.signature,
        )
        if _same(parcel, fact):
            if parcel.carrier != carrier:  # settled: it was "fedex usps"
                self.db.execute("UPDATE parcels SET carrier = ? WHERE id = ?", (carrier, parcel.id))
            return
        self.deliveries.record(parcel.member_id, fact)


def _same(parcel: Parcel, fact: Fact) -> bool:
    """Whether the carrier says nothing the parcel doesn't already have."""
    return (
        parcel.status == fact.status
        and (fact.day is None or parcel.expected_day == fact.day)
        and (parcel.window_start, parcel.window_end) == (fact.window_start, fact.window_end)
        and parcel.problem == (fact.problem if fact.status == "problem" else "")
        and (not fact.left_at or parcel.left_at == fact.left_at)
        and (parcel.signature or not fact.signature)
    )
