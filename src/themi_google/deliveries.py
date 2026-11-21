"""WL8, PT2: parcels on their way, from the shipping emails triage sorts.

Triage fills `parcels` for an email about parcels coming to the family: for each, the
shop's name, its tracking number (only one that code found in the email, PT1), the day it's
expected (or came), how far along it is (`on_the_way`, `out_for_delivery`, `problem`,
`delivered`) and, for a problem, a short plain line ("Delivery attempted").

This keeps one row per parcel (`parcels`, the Themi Package Tracking Plan's "The parcel
table"), so a shop's "shipped" email and the carrier's "out for delivery" are one parcel:

- An email with a number updates that parcel. Numbers found in two carriers' patterns keep
  both carriers until a lookup settles it (PT5).
- An email without a number joins a parcel from the same shop already on its day, else
  the nearest open one due within `NEAR_DAYS`; failing that it's a numberless parcel when
  it gives a day (an undated "on its way" is left out, as in WL8).
- A numbered parcel takes in a numberless one from the same shop on the same day (or, when
  it's known only by its carrier, the day's only numberless parcel).
- The newest fact wins whatever said it, and a parcel never goes back from `delivered`. A
  carrier's name never replaces a shop's ("UPS" for a Chewy parcel).

Only the shop's name is kept, never what's in the parcel: the wall is a shared screen, and
a parcel can be a present. Delivered parcels go after two weeks; others 30 days after the
last news. `on(day)` answers what's due or came on a day, a line per parcel; the wall's
note uses it ("A delivery from Chewy is due today").
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.localtime import to_utc_iso
from themi_google.tracking import from_json

if TYPE_CHECKING:
    from themi.accounts import LinkedAccount, Member
    from themi.core.services import Services
    from themi_google.triage import Verdict

STATUSES = ("on_the_way", "out_for_delivery", "problem", "delivered")
DATED = ("out_for_delivery", "delivered")  # undated, these happened the day the email came
KEEP_DELIVERED = timedelta(days=14)
KEEP_QUIET = timedelta(days=30)  # a parcel with no news for this long is dropped
NEAR_DAYS = 3
MAX_SHOP = 40
MAX_PROBLEM = 80
MAX_PARCELS = 12  # an email's parcels
CARRIER_NAMES = frozenset(
    {
        "ups",
        "ups my choice",
        "usps",
        "us postal service",
        "u.s. postal service",
        "united states postal service",
        "postal service",
        "informed delivery",
        "usps informed delivery",
        "fedex",
        "fedex delivery manager",
    }
)


@dataclass(frozen=True)
class Delivery:
    shop: str  # "Chewy"
    status: str  # one of STATUSES


@dataclass(frozen=True)
class Parcel:
    id: int
    member_id: int
    carrier: str  # "ups"; "fedex usps" while unsettled; "" without a number
    number: str
    shop: str
    status: str
    expected_day: date | None
    window_start: str  # "14:00", PT5; "" for none
    window_end: str
    problem: str
    delivered_at: datetime | None
    left_at: str
    source: str  # "email" or "lookup"
    updated_at: datetime
    signature: bool = False  # PT6a: someone has to sign for it
    moved_from: date | None = None  # PT6a: the day it was due before it was moved later

    @property
    def carriers(self) -> list[str]:
        return self.carrier.split()


@dataclass(frozen=True)
class Fact:
    """Something an email or a carrier says about one parcel, true at `at`."""

    shop: str
    status: str
    at: datetime
    number: str = ""
    carriers: tuple[str, ...] = ()
    day: date | None = None
    problem: str = ""
    source: str = "email"
    window_start: str = ""
    window_end: str = ""
    delivered_at: datetime | None = None
    left_at: str = ""
    signature: bool = False


def is_carrier_name(shop: str) -> bool:
    return _key(shop) in CARRIER_NAMES


def _key(shop: str) -> str:
    return " ".join(shop.casefold().split())


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def parse(raw: Any, numbers: Collection[str] = ()) -> dict[str, str] | None:
    """One of the model's `parcels`, or None when it isn't a parcel. Its `tracking` is kept
    only when it's one of the numbers code found in the email (`numbers`)."""
    if not isinstance(raw, dict):
        return None
    shop = _clean(raw.get("shop"), MAX_SHOP)
    status = str(raw.get("status") or "")
    if not shop or status not in STATUSES:
        return None
    day = str(raw.get("date") or "").strip()
    try:
        day = date.fromisoformat(day).isoformat() if day else ""
    except ValueError:
        day = ""
    tracking = re.sub(r"\s+", "", str(raw.get("tracking") or "")).upper()
    problem = _clean(raw.get("problem"), MAX_PROBLEM) if status == "problem" else ""
    start, end = _window(raw.get("window"))
    return {
        "shop": shop,
        "tracking": tracking if tracking in numbers else "",
        "date": day,
        "status": status,
        "problem": problem,
        "window_start": start,
        "window_end": end,
    }


def _window(raw: Any) -> tuple[str, str]:
    """PT3: "14:15-16:15" (a carrier's delivery window), as two times; ("", "") for none
    or anything else."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", str(raw or ""))
    if not m:
        return "", ""
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if not (h1 < 24 and h2 < 24 and m1 < 60 and m2 < 60 and (h1, m1) < (h2, m2)):
        return "", ""
    return f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}"


def parse_all(raw: Any, numbers: Collection[str] = ()) -> tuple[dict[str, str], ...]:
    """The model's `parcels` for an email: the well-formed ones, at most MAX_PARCELS."""
    if not isinstance(raw, list):
        return ()
    found = (parse(item, numbers) for item in raw[:MAX_PARCELS])
    return tuple(p for p in found if p is not None)


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _parcel(r: dict[str, Any]) -> Parcel:
    return Parcel(
        r["id"],
        r["member_id"],
        r["carrier"],
        r["number"],
        r["shop"],
        r["status"],
        _day(r["expected_day"]),
        r["window_start"],
        r["window_end"],
        r["problem"],
        _when(r["delivered_at"]),
        r["left_at"],
        r["source"],
        datetime.fromisoformat(r["updated_at"]),
        bool(r["signature"]),
        _day(r["moved_from"]),
    )


def _delivered_at(fact: Fact) -> str | None:
    if fact.status != "delivered":
        return None
    return to_utc_iso(fact.delivered_at or fact.at)


class Deliveries:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    # ----- from email ------------------------------------------------------------------

    async def on_verdict(
        self, member: Member, account: LinkedAccount, row: dict[str, Any], verdict: Verdict
    ) -> None:
        """A verdict listener: keep the parcels an email is about."""
        if not verdict.parcels:
            return
        carriers: dict[str, list[str]] = {}
        for f in from_json(row.get("tracking")):
            carriers.setdefault(f.number, []).append(f.carrier)
        parcels = list(verdict.parcels)
        if len(parcels) == 1 and not parcels[0]["tracking"] and len(carriers) == 1:
            # one parcel, one number: the model left it out, but there's no doubt
            parcels[0] = {**parcels[0], "tracking": next(iter(carriers))}
        received = datetime.fromisoformat(row["received_at"])
        for p in parcels:
            number = p["tracking"]
            self.record(
                member.id,
                Fact(
                    shop=p["shop"],
                    status=p["status"],
                    at=received,
                    number=number,
                    carriers=tuple(sorted(carriers.get(number, []))),
                    day=_day(p["date"]),
                    problem=p["problem"],
                    window_start=p.get("window_start", ""),
                    window_end=p.get("window_end", ""),
                ),
            )

    # ----- keeping parcels -------------------------------------------------------------

    def record(self, member_id: int, fact: Fact) -> Parcel | None:
        """Apply a fact to its parcel (made if new); None when there's nothing to keep."""
        if fact.day is None and fact.status in DATED:
            fact = replace(fact, day=fact.at.astimezone(self.tz()).date())
        with self.db.transaction():
            if fact.number:
                parcel = self._by_number(fact.number)
                parcel_id = self._apply(parcel, fact) if parcel else self._insert(member_id, fact)
                self._fold(parcel_id)
                if fact.source == "email":  # PT5: news by email brings the next look forward
                    self.db.execute(
                        "UPDATE parcels SET look_after = ? WHERE id = ?",
                        (to_utc_iso(clock.now()), parcel_id),
                    )
            else:
                target = self._numberless_target(fact)
                if target is not None:
                    parcel_id = self._apply(target, fact)
                elif fact.day is not None:
                    parcel_id = self._insert(member_id, fact)
                else:
                    return None  # an undated "on its way": no day to put it on
            self._clean_up()
        return self.get(parcel_id)

    def get(self, parcel_id: int) -> Parcel | None:
        r = self.db.one("SELECT * FROM parcels WHERE id = ?", (parcel_id,))
        return _parcel(r) if r else None

    def _by_number(self, number: str) -> Parcel | None:
        r = self.db.one("SELECT * FROM parcels WHERE number = ?", (number,))
        return _parcel(r) if r else None

    def _numberless_target(self, fact: Fact) -> Parcel | None:
        """The parcel a numberless email is about: one from the same shop already on that
        day, else the nearest open one due within NEAR_DAYS (or undated)."""
        rows = self.db.query(
            "SELECT * FROM parcels WHERE shop_key = ? ORDER BY id", (_key(fact.shop),)
        )
        parcels = [_parcel(r) for r in rows]
        if fact.day is not None:
            same = [p for p in parcels if p.expected_day == fact.day]
            if same:
                return min(same, key=lambda p: (not p.number, p.id))

        def distance(p: Parcel) -> int:
            if p.expected_day is None or fact.day is None:
                return NEAR_DAYS
            return abs((p.expected_day - fact.day).days)

        near = [p for p in parcels if p.status != "delivered" and distance(p) <= NEAR_DAYS]
        if fact.day is None and len(near) > 1:
            return None  # an undated email about one of several: can't tell which
        return min(near, key=lambda p: (distance(p), not p.number, p.id), default=None)

    def _insert(self, member_id: int, fact: Fact) -> int:
        return self.db.execute(
            "INSERT INTO parcels (member_id, carrier, number, shop, shop_key, status, "
            "expected_day, window_start, window_end, problem, delivered_at, left_at, source, "
            "updated_at, created_at, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                member_id,
                " ".join(fact.carriers),
                fact.number,
                fact.shop,
                _key(fact.shop),
                fact.status,
                fact.day.isoformat() if fact.day else "",
                fact.window_start,
                fact.window_end,
                fact.problem if fact.status == "problem" else "",
                _delivered_at(fact),
                fact.left_at,
                fact.source,
                to_utc_iso(fact.at),
                to_utc_iso(clock.now()),
                int(fact.signature),
            ),
        )

    def _apply(self, parcel: Parcel, fact: Fact) -> int:
        """Bring a parcel up to date with a fact. An older fact only fills what's blank."""
        changes: dict[str, Any] = {}
        if fact.signature and not parcel.signature:
            changes["signature"] = 1
        if is_carrier_name(parcel.shop) and not is_carrier_name(fact.shop):
            changes["shop"], changes["shop_key"] = fact.shop, _key(fact.shop)
        if fact.carriers and (
            not parcel.carrier or (len(fact.carriers) == 1 and fact.carriers[0] in parcel.carriers)
        ):
            changes["carrier"] = " ".join(fact.carriers)
        newer = fact.at >= parcel.updated_at
        if newer and not (parcel.status == "delivered" and fact.status != "delivered"):
            changes.update(
                status=fact.status,
                problem=fact.problem if fact.status == "problem" else "",
                source=fact.source,
                updated_at=to_utc_iso(fact.at),
            )
            if fact.day is not None:
                changes["expected_day"] = fact.day.isoformat()
                was = parcel.expected_day
                if was is not None and fact.day > was and fact.status != "delivered":
                    changes["moved_from"] = was.isoformat()  # PT6a: "now due Friday"
            if fact.window_start or fact.status in ("delivered", "problem"):
                changes["window_start"] = fact.window_start
                changes["window_end"] = fact.window_end
            if fact.status == "delivered":
                changes["delivered_at"] = _delivered_at(fact)
                if fact.left_at:
                    changes["left_at"] = fact.left_at
        elif fact.day is not None and parcel.expected_day is None:
            changes["expected_day"] = fact.day.isoformat()
        if changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            self.db.execute(
                f"UPDATE parcels SET {sets} WHERE id = ?", (*changes.values(), parcel.id)
            )
        return parcel.id

    def _fold(self, parcel_id: int) -> None:
        """A numberless parcel from the same shop on the same day is this one. A parcel
        known only by its carrier ("UPS") takes in the day's numberless parcel when there's
        just one: a shop's email without a number and the carrier's with one."""
        parcel = self.get(parcel_id)
        if parcel is None or parcel.expected_day is None:
            return
        rows = self.db.query(
            "SELECT * FROM parcels WHERE number = '' AND expected_day = ? AND id != ? ORDER BY id",
            (parcel.expected_day.isoformat(), parcel.id),
        )
        same = [r for r in rows if r["shop_key"] == _key(parcel.shop)]
        if not same and is_carrier_name(parcel.shop) and len(rows) == 1:
            same = rows
        for r in same:
            other = _parcel(r)
            self._apply(
                parcel,
                Fact(
                    shop=other.shop,
                    status=other.status,
                    at=other.updated_at,
                    day=other.expected_day,
                    problem=other.problem,
                    source=other.source,
                    delivered_at=other.delivered_at,
                ),
            )
            parcel = self.get(parcel.id) or parcel
            self.db.execute("DELETE FROM parcels WHERE id = ?", (other.id,))

    def _clean_up(self) -> None:
        now = clock.now()
        self.db.execute(
            "DELETE FROM parcels WHERE (status = 'delivered' AND "
            "COALESCE(delivered_at, updated_at) < ?) OR updated_at < ?",
            (to_utc_iso(now - KEEP_DELIVERED), to_utc_iso(now - KEEP_QUIET)),
        )

    # ----- reading ---------------------------------------------------------------------

    def parcels(self, ids: Iterable[int] | None = None) -> list[Parcel]:
        """Every parcel kept, or those with these ids, oldest first."""
        wanted = set(ids) if ids is not None else None
        rows = self.db.query("SELECT * FROM parcels ORDER BY id")
        return [_parcel(r) for r in rows if wanted is None or r["id"] in wanted]

    def news(self, day: date) -> list[Parcel]:
        """PT6a: the parcels with something to say on a day: due or delivered that day,
        moved off it to a later one, or with a problem heard of that day."""
        tz = self.tz()
        found = [
            p
            for p in self.parcels()
            if p.expected_day == day
            or p.moved_from == day
            or (p.status == "problem" and p.updated_at.astimezone(tz).date() == day)
        ]
        return sorted(found, key=lambda p: (_key(p.shop), p.id))

    def morning_line(self, member_id: int, day: date) -> str | None:
        """PT6a: the morning message's line about this person's own parcels (found in their
        email): what's due that day and any problem; None for nothing."""
        from themi_google import parcel_words  # its sentences use Parcel

        own = [p for p in self.news(day) if p.member_id == member_id]
        return parcel_words.morning(own, day)

    def on(self, day: date) -> list[Delivery]:
        """What's due or came on a day: a line per parcel, by shop."""
        rows = self.db.query(
            "SELECT shop, status FROM parcels WHERE expected_day = ? ORDER BY shop_key, id",
            (day.isoformat(),),
        )
        return [Delivery(r["shop"], r["status"]) for r in rows]
