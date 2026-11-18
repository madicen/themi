"""How much of each outside service Themi uses, against its free-tier limit (UC1; the
Themi Usage Plan).

A `Meter` is one thing that's used up: an AI backend's requests, a device cloud's calls,
a search API's credits. Modules register theirs (`ModuleContext.usage_meter`) the way they
add settings sections, and count as they spend (`UsageBook.count`). Totals are kept a day
at a time in `usage_daily`, for 400 days.

- A meter's day starts at midnight in its limit's reset zone (Gemini's at midnight
  Pacific); a meter with no zone uses the family's.
- Counting never fails or slows the call it counts: a database error is logged and dropped.
- `scope` is an id (a backend's, a device's) or empty; no names or text are kept.
- An admin's override (`usage_limits`) wins over the module's default, for one scope or
  for every scope of the meter.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from themi import clock
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.storage.db import Database

log = logging.getLogger(__name__)

KEPT_DAYS = 400
GROUPS = ("AI", "Devices", "Google", "Web", "Other")  # the card's order


@dataclass(frozen=True)
class Limits:
    """A free tier's limits, as the module knows them. `resets` is the zone its day starts
    in ("America/Los_Angeles", "UTC"); empty is the family's. `source` says where the
    numbers came from and `checked` when ("2026-11")."""

    per_day: float | None = None
    per_month: float | None = None
    resets: str = ""
    source: str = ""
    checked: str = ""


@dataclass(frozen=True)
class Price:
    """A paid model's price, in dollars, for an estimate of the month's spend."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    per_request: float = 0.0  # a picture model's price per picture

    def estimate(self, totals: Totals) -> float:
        cost = totals.input_tokens / 1e6 * self.input_per_mtok
        cost += totals.output_tokens / 1e6 * self.output_per_mtok
        return cost + totals.count * self.per_request


@dataclass(frozen=True)
class Totals:
    count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    amount: float = 0.0

    def __add__(self, other: Totals) -> Totals:
        return Totals(
            self.count + other.count,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.amount + other.amount,
        )


@dataclass(frozen=True)
class Reading:
    """A `read` meter's figures, from the provider itself."""

    today: float
    month: float = 0.0


@dataclass(frozen=True)
class Meter:
    """One thing that's used up. `measure` is what its limit counts: "count" (requests,
    calls) or "amount" (neurons, credits: what `count(amount=...)` adds). `prices` are by
    model, for paid backends. `amounts` is what one request of a model adds to `amount`
    when the caller doesn't say (Cloudflare's neurons a picture).
    """

    key: str  # module-prefixed: "gemini.requests", "homeconnect.calls"
    label: str  # "Gemini", "Home Connect"
    unit: str  # "requests", "calls", "neurons"
    group: str = "Other"  # AI, Devices, Google, Web, Other
    order: int = 50  # place in its group
    limits: Limits | None = None
    measure: str = "count"
    read: Callable[[], Reading] | None = None
    prices: dict[str, Price] = field(default_factory=dict)
    amounts: dict[str, float] = field(default_factory=dict)
    module: str = ""  # set when it's registered


@dataclass(frozen=True)
class Limit:
    """The limit in use for a meter and scope: the module's default or an override."""

    per_day: float | None
    per_month: float | None
    source: str = ""
    checked: str = ""
    set_by: str = ""  # an override's admin; empty for the module's default
    set_at: str = ""

    @property
    def overridden(self) -> bool:
        return bool(self.set_by)


class UsageBook:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.meters: dict[str, Meter] = {}

    # ----- meters --------------------------------------------------------------------

    def add(self, meter: Meter) -> Meter:
        if meter.key in self.meters:
            first = self.meters[meter.key].module or "the core"
            raise ValueError(f"usage meter {meter.key} is registered twice (first by {first})")
        self.meters[meter.key] = meter
        return meter

    def zone(self, key: str) -> ZoneInfo:
        meter = self.meters.get(key)
        name = meter.limits.resets if meter is not None and meter.limits is not None else ""
        if not name:
            name = self._family_zone()
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    def _family_zone(self) -> str:
        try:
            row = self.db.one("SELECT timezone FROM family WHERE id = 1")
        except sqlite3.Error:
            return "UTC"
        return str(row["timezone"]) if row and row["timezone"] else "UTC"

    def day(self, key: str) -> date:
        """Today, for this meter: in its reset zone."""
        return clock.now().astimezone(self.zone(key)).date()

    # ----- counting -------------------------------------------------------------------

    def count(
        self,
        key: str,
        n: int = 1,
        *,
        scope: str | int = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        amount: float = 0.0,
    ) -> None:
        """Add to today's row. Never raises: a note about a call never costs the call."""
        meter = self.meters.get(key)
        if not amount and meter is not None and model in meter.amounts:
            amount = meter.amounts[model] * n
        try:
            self.db.execute(
                "INSERT INTO usage_daily (day, meter, scope, model, count, input_tokens, "
                "output_tokens, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (day, meter, scope, model) DO UPDATE SET "
                "count = count + excluded.count, "
                "input_tokens = input_tokens + excluded.input_tokens, "
                "output_tokens = output_tokens + excluded.output_tokens, "
                "amount = amount + excluded.amount",
                (
                    self.day(key).isoformat(), key, str(scope), model, n,
                    input_tokens, output_tokens, amount,
                ),
            )  # fmt: skip
        except (sqlite3.Error, ValueError):
            log.warning("Couldn't count usage of %s", key, exc_info=True)

    # ----- reading --------------------------------------------------------------------

    def totals(
        self, key: str, start: date, end: date, scope: str | None = None, model: str | None = None
    ) -> Totals:
        """From `start` to `end`, both included. `scope` None is every scope."""
        sql = (
            "SELECT COALESCE(SUM(count), 0) AS c, COALESCE(SUM(input_tokens), 0) AS i, "
            "COALESCE(SUM(output_tokens), 0) AS o, COALESCE(SUM(amount), 0) AS a "
            "FROM usage_daily WHERE meter = ? AND day >= ? AND day <= ?"
        )
        params: list[object] = [key, start.isoformat(), end.isoformat()]
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        if model is not None:
            sql += " AND model = ?"
            params.append(model)
        row = self.db.one(sql, tuple(params))
        if row is None:
            return Totals()
        return Totals(int(row["c"]), int(row["i"]), int(row["o"]), float(row["a"]))

    def today(self, key: str, scope: str | None = None) -> Totals:
        day = self.day(key)
        return self.totals(key, day, day, scope)

    def month(self, key: str, scope: str | None = None) -> Totals:
        day = self.day(key)
        return self.totals(key, day.replace(day=1), day, scope)

    def days(self, key: str, n: int = 30, scope: str | None = None) -> list[tuple[date, Totals]]:
        """The last `n` days, oldest first, today last; a day with no use is zero."""
        end = self.day(key)
        start = end - timedelta(days=n - 1)
        sql = (
            "SELECT day, SUM(count) AS c, SUM(input_tokens) AS i, SUM(output_tokens) AS o, "
            "SUM(amount) AS a FROM usage_daily WHERE meter = ? AND day >= ? AND day <= ?"
        )
        params: list[object] = [key, start.isoformat(), end.isoformat()]
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        rows = {
            r["day"]: Totals(int(r["c"]), int(r["i"]), int(r["o"]), float(r["a"]))
            for r in self.db.query(sql + " GROUP BY day", tuple(params))
        }
        out = []
        for i in range(n):
            day = start + timedelta(days=i)
            out.append((day, rows.get(day.isoformat(), Totals())))
        return out

    def scopes(self, key: str) -> list[str]:
        """The scopes with use this month, in the order they were first used."""
        day = self.day(key)
        rows = self.db.query(
            "SELECT scope, MIN(day) AS first FROM usage_daily WHERE meter = ? AND day >= ? "
            "GROUP BY scope ORDER BY first, scope",
            (key, day.replace(day=1).isoformat()),
        )
        return [str(r["scope"]) for r in rows]

    def models(self, key: str, scope: str | None = None) -> dict[str, Totals]:
        """This month's totals by model."""
        day = self.day(key)
        sql = (
            "SELECT model, SUM(count) AS c, SUM(input_tokens) AS i, SUM(output_tokens) AS o, "
            "SUM(amount) AS a FROM usage_daily WHERE meter = ? AND day >= ?"
        )
        params: list[object] = [key, day.replace(day=1).isoformat()]
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        return {
            str(r["model"]): Totals(int(r["c"]), int(r["i"]), int(r["o"]), float(r["a"]))
            for r in self.db.query(sql + " GROUP BY model", tuple(params))
        }

    def estimate(self, key: str, scope: str | None = None) -> float | None:
        """This month's spend in dollars, when the meter has a price for a model it used;
        None when it has none (a free tier)."""
        meter = self.meters.get(key)
        if meter is None or not meter.prices:
            return None
        priced = False
        cost = 0.0
        for model, totals in self.models(key, scope).items():
            price = meter.prices.get(model)
            if price is not None:
                priced = True
                cost += price.estimate(totals)
        return cost if priced else None

    # ----- limits ---------------------------------------------------------------------

    def limit_for(self, key: str, scope: str = "") -> Limit | None:
        """An override for this scope, then one for every scope, then the module's."""
        for wanted in [scope, ""] if scope else [""]:
            row = self.db.one(
                "SELECT per_day, per_month, set_by, set_at FROM usage_limits "
                "WHERE meter = ? AND scope = ?",
                (key, wanted),
            )
            if row is not None:
                return Limit(row["per_day"], row["per_month"], set_by=row["set_by"],
                             set_at=row["set_at"])  # fmt: skip
        meter = self.meters.get(key)
        if meter is None or meter.limits is None:
            return None
        limits = meter.limits
        if limits.per_day is None and limits.per_month is None:
            return None
        return Limit(limits.per_day, limits.per_month, limits.source, limits.checked)

    def set_limit(
        self,
        key: str,
        *,
        per_day: float | None,
        per_month: float | None,
        set_by: str,
        scope: str = "",
    ) -> None:
        self.db.execute(
            "INSERT INTO usage_limits (meter, scope, per_day, per_month, set_by, set_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (meter, scope) DO UPDATE SET "
            "per_day = excluded.per_day, per_month = excluded.per_month, "
            "set_by = excluded.set_by, set_at = excluded.set_at",
            (key, scope, per_day, per_month, set_by, to_utc_iso(clock.now())),
        )

    def clear_limit(self, key: str, scope: str = "") -> None:
        self.db.execute("DELETE FROM usage_limits WHERE meter = ? AND scope = ?", (key, scope))

    # ----- keeping --------------------------------------------------------------------

    def prune(self) -> int:
        """Delete days older than 400 (the core's `usage.prune` job)."""
        cutoff = clock.now().date() - timedelta(days=KEPT_DAYS)
        return self.db.update("DELETE FROM usage_daily WHERE day < ?", (cutoff.isoformat(),))


class Tally:
    """What a connector's client calls once for each request it sends (UC3): the module
    sets it on the client (`client.tally = ctx.usage_meter(...)`). `status` is the answer's
    HTTP status when there is one: a 429 counts as refused (`<meter>.refused`)."""

    def __init__(self, usage: UsageBook | None, key: str, scope: str | int = "") -> None:
        self.usage = usage
        self.key = key
        self.scope = scope

    def __call__(self, status: int | None = None, n: int = 1) -> None:
        if self.usage is None:
            return
        key = f"{self.key}.refused" if status == 429 else self.key
        self.usage.count(key, n, scope=self.scope)

    def for_scope(self, scope: str | int) -> Tally:
        return Tally(self.usage, self.key, scope)


NO_TALLY = Tally(None, "")  # a client nobody counts (its own unit tests)
