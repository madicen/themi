"""WL8: parcels on their way, from the shipping emails triage sorts.

Triage fills a `delivery` for an email about a parcel coming to the family: the shop's
name, the day it's expected (or came) and how far along it is (`on_the_way`,
`out_for_delivery`, `delivered`). This keeps them, a row per email, and answers what's
due or came on a day, one line per shop, the furthest along winning. The wall's note uses
it ("A delivery from Chewy is due today").

Only the shop's name is kept, never what's in the parcel: the wall is a shared screen, and
a parcel can be a present. An email that gives no day counts for the day it arrived when
it's out for delivery or delivered; otherwise it's left out. Rows go after two weeks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.accounts import LinkedAccount, Member
    from themi.core.services import Services
    from themi_google.triage import Verdict

STATUSES = ("on_the_way", "out_for_delivery", "delivered")  # in order, furthest last
KEEP = timedelta(days=14)
MAX_SHOP = 40


@dataclass(frozen=True)
class Delivery:
    shop: str  # "Chewy"
    status: str  # one of STATUSES


def parse(raw: Any) -> dict[str, str] | None:
    """The model's `delivery`, or None when the email isn't about a parcel."""
    if not isinstance(raw, dict):
        return None
    shop = " ".join(str(raw.get("shop") or "").split())[:MAX_SHOP]
    status = str(raw.get("status") or "")
    if not shop or status not in STATUSES:
        return None
    day = str(raw.get("date") or "").strip()
    try:
        day = date.fromisoformat(day).isoformat() if day else ""
    except ValueError:
        day = ""
    return {"shop": shop, "date": day, "status": status}


class Deliveries:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    async def on_verdict(
        self, member: Member, account: LinkedAccount, row: dict[str, Any], verdict: Verdict
    ) -> None:
        """A verdict listener: keep the parcel an email is about, if it's about one."""
        found = verdict.delivery
        if found is None:
            return
        day = found["date"]
        if not day:
            if found["status"] == "on_the_way":
                return  # no day to put it on
            received = datetime.fromisoformat(row["received_at"])
            day = received.astimezone(self._tz()).date().isoformat()
        now = clock.now()
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO deliveries (email_id, member_id, shop, day, status, found_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(email_id) DO UPDATE SET "
                "shop = excluded.shop, day = excluded.day, status = excluded.status",
                (row["id"], member.id, found["shop"], day, found["status"], to_utc_iso(now)),
            )
            self.db.execute("DELETE FROM deliveries WHERE found_at < ?", (to_utc_iso(now - KEEP),))

    def on(self, day: date) -> list[Delivery]:
        """What's due or came on a day: a line per shop, the furthest along, by shop."""
        rows = self.db.query(
            "SELECT shop, status FROM deliveries WHERE day = ? ORDER BY id", (day.isoformat(),)
        )
        best: dict[str, Delivery] = {}
        for r in rows:
            key = r["shop"].casefold()
            seen = best.get(key)
            if seen is None or STATUSES.index(r["status"]) >= STATUSES.index(seen.status):
                best[key] = Delivery(r["shop"], r["status"])
        return sorted(best.values(), key=lambda d: d.shop.casefold())
