"""Takeout rescue (35a): dinner ordered in when the household is running on empty.

In the dinner window (17:00 to 19:30 by default, a household setting), the
`takeout.rescue` job stages a DoorDash order when all of these hold:

- everyone in the household reads as low on energy (the chores' read, `suggested_level`;
  someone with tracking off has no read, so it doesn't happen),
- nobody has logged a meal in the last 3 hours (meals.py's log),
- nothing was staged today, and no takeout or eating out is on today's spending,
- a saved favourite costs no more than the cap per order and what's left of the month's
  takeout budget (with no budget set, the cap alone).

It goes through the `doordash_order` category, which always asks (Tier 1, capped), to an
admin, at once rather than at a good moment (approvals' `timely`). Saying yes sends the
store link and the items; a person does the checkout on DoorDash, so nothing is bought by
Themi. The receipt email then counts
toward the budget as any takeout does (X1). The favourites are kept on the website
(`/takeout`). The card's words carry money, never an energy score.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

from pydantic import field_validator

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.accounts.household import HouseholdSettings
from themi.autonomy import ExecutionContext
from themi.core import keys
from themi.core.approvals import ApprovalsUI
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi_home.spending import SpendingSettings, money

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi_home.meals import Meals
    from themi_home.spending import Spending

log = logging.getLogger(__name__)

CATEGORY, EXECUTOR = "doordash_order", "takeout.order"
NO_MEAL_FOR = timedelta(hours=3)
CHECK_EVERY = timedelta(minutes=15)
CARD_LASTS = timedelta(hours=1)  # after the dinner window ends, an unanswered card lapses
MAX_ITEMS = 20


@dataclass(frozen=True)
class Favourite:
    id: int
    name: str
    store_url: str
    items: tuple[str, ...]
    cents: int


def _clock_time(value: str) -> str:
    try:
        hour, minute = (int(part) for part in value.strip().split(":")[:2])
        parsed = time(hour, minute)
    except ValueError as exc:
        raise ValueError(f"'{value}' isn't a time like 17:00") from exc
    return f"{parsed:%H:%M}"


class TakeoutSettings(HouseholdSettings):
    """The dinner window the rescue looks in, and the most one order may cost."""

    module: ClassVar[str] = "takeout"
    dinner_from: str = "17:00"
    dinner_until: str = "19:30"
    order_cap_cents: int = 60_00

    @field_validator("dinner_from", "dinner_until")
    @classmethod
    def _time(cls, value: str) -> str:
        return _clock_time(value)

    @field_validator("order_cap_cents")
    @classmethod
    def _cap(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("the most an order may cost is more than nothing")
        return value


def _favourite(row: dict[str, Any]) -> Favourite:
    return Favourite(
        row["id"], row["name"], row["store_url"], tuple(json.loads(row["items"])), row["cents"]
    )


def clean_items(lines: list[str]) -> tuple[str, ...]:
    items = [" ".join(line.lstrip("-•* ").split()) for line in lines]
    return tuple(i[:120] for i in items if i)[:MAX_ITEMS]


class Takeout:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.takeout, self)
        self.services.autonomy.executors.register(EXECUTOR)(self._execute)

    # ----- favourites -----------------------------------------------------------------

    def favourites(self) -> list[Favourite]:
        rows = self.db.query(
            "SELECT * FROM takeout_favourites WHERE removed_at IS NULL ORDER BY name COLLATE NOCASE"
        )
        return [_favourite(r) for r in rows]

    def favourite(self, favourite_id: int) -> Favourite | None:
        row = self.db.one("SELECT * FROM takeout_favourites WHERE id = ?", (favourite_id,))
        return _favourite(row) if row else None

    def save_favourite(
        self,
        by: Member,
        name: str,
        store_url: str,
        items: list[str],
        cents: int,
        favourite_id: int | None = None,
    ) -> Favourite:
        name = " ".join(name.split())[:80]
        store_url = store_url.strip()
        if not name:
            raise InvalidValue("a favourite needs a name")
        if not store_url.startswith("https://"):
            raise InvalidValue("the store link starts with https://")
        if not 0 < cents <= 1_000_00:
            raise InvalidValue("that amount doesn't look right")
        lines = json.dumps(list(clean_items(items)))
        if favourite_id is None:
            favourite_id = self.db.execute(
                "INSERT INTO takeout_favourites (name, store_url, items, cents, created_by, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, store_url, lines, cents, by.id, to_utc_iso(clock.now())),
            )
        else:
            self.db.execute(
                "UPDATE takeout_favourites SET name = ?, store_url = ?, items = ?, cents = ? "
                "WHERE id = ? AND removed_at IS NULL",
                (name, store_url, lines, cents, favourite_id),
            )
        saved = self.favourite(favourite_id)
        assert saved is not None
        return saved

    def remove_favourite(self, favourite_id: int) -> None:
        self.db.execute(
            "UPDATE takeout_favourites SET removed_at = ? WHERE id = ? AND removed_at IS NULL",
            (to_utc_iso(clock.now()), favourite_id),
        )

    # ----- the rescue -----------------------------------------------------------------

    def settings(self) -> TakeoutSettings:
        return self.store.household(TakeoutSettings)

    def budget_left(self, today: date) -> int | None:
        """What's left of this month's takeout budget, in cents (None: no budget set)."""
        budget = self.store.household(SpendingSettings).takeout_budget_cents
        if not budget:
            return None
        spending = self._spending()
        first = today.replace(day=1)
        spent = sum(s.amount_cents for s in spending.month(first, kind="takeout"))
        return budget - spent

    def affordable(self, today: date) -> Favourite | None:
        """The favourite to offer: within the cap and the budget left, the one offered
        longest ago (or never), then the cheapest."""
        limit = self.settings().order_cap_cents
        left = self.budget_left(today)
        if left is not None:
            limit = min(limit, left)
        if limit <= 0:
            return None
        last_offered = {
            r["favourite_id"]: r["day"]
            for r in self.db.query(
                "SELECT favourite_id, MAX(day) AS day FROM takeout_rescues GROUP BY favourite_id"
            )
        }
        fitting = [f for f in self.favourites() if f.cents <= limit]
        if not fitting:
            return None
        return min(fitting, key=lambda f: (last_offered.get(f.id, ""), f.cents, f.id))

    def why_not(self, now: datetime) -> str | None:
        """None when a rescue is due now, else which precondition doesn't hold (for logs
        and tests; never shown to anyone)."""
        local = now.astimezone(self._tz())
        settings = self.settings()
        start, end = (
            time.fromisoformat(settings.dinner_from),
            time.fromisoformat(settings.dinner_until),
        )
        if not start <= local.time() < end:
            return "outside the dinner window"
        today = local.date()
        if self.db.one("SELECT 1 FROM takeout_rescues WHERE day = ?", (today.isoformat(),)):
            return "already staged today"
        members = self.store.list_members()
        if not members:
            return "nobody here"
        energy = self.services.energy
        if any(energy.suggested_level(m) != "low" for m in members):
            return "not everyone is low"
        meals = self._meals()
        if meals is not None and meals.anyone_ate_since(now - NO_MEAL_FOR):
            return "someone ate recently"
        spending = self._spending()
        if any(
            s.spent_on == today and not s.business
            for s in spending.month(today.replace(day=1))
            if s.kind in ("takeout", "eating_out")
        ):
            return "takeout or eating out already today"
        return None

    async def rescue(self) -> bool:
        """Scheduler job: stage a takeout order when every precondition holds."""
        now = clock.now()
        reason = self.why_not(now)
        if reason is not None:
            return False
        today = now.astimezone(self._tz()).date()
        favourite = self.affordable(today)
        if favourite is None:
            log.info("Takeout rescue: no saved favourite fits the cap and the budget left")
            return False
        member = self._who_orders()
        left = self.budget_left(today)
        budget = (
            f", {money(left - favourite.cents)} left of this month's takeout budget after"
            if left is not None
            else ""
        )
        summary = (
            f"Dinner sorted? {favourite.name} on DoorDash, about {money(favourite.cents)}"
            f"{budget}. If that suits, I'll send the store link and what to order; the "
            "checkout is yours."
        )
        until = time.fromisoformat(self.settings().dinner_until)
        expires = now.astimezone(self._tz()).replace(
            hour=until.hour, minute=until.minute, second=0, microsecond=0
        )
        rescue_id = self.db.execute(
            "INSERT INTO takeout_rescues (day, favourite_id, member_id, staged_at) "
            "VALUES (?, ?, ?, ?)",
            (today.isoformat(), favourite.id, member.id, to_utc_iso(now)),
        )
        outcome = await self.services.autonomy.stage(
            CATEGORY,
            member,
            summary,
            {"favourite": favourite.id, "rescue": rescue_id},
            EXECUTOR,
            expires=expires + CARD_LASTS,
        )
        self.db.execute(
            "UPDATE takeout_rescues SET action_id = ? WHERE id = ?", (outcome.action.id, rescue_id)
        )
        return True

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        favourite = self.favourite(int(payload["favourite"]))
        if favourite is None:
            return "That favourite has been removed, so there's nothing to send."
        items = "\n".join(f"- {item}" for item in favourite.items)
        text = f"{favourite.name} on DoorDash: {favourite.store_url}"
        if items:
            text += f"\n{items}"
        return text + "\nAdd those to the cart and check out there."

    # ----- small things ---------------------------------------------------------------

    def _who_orders(self) -> Member:
        """Whose card it is: everyone reads as low, so an admin's (the household's
        category), else the first person here."""
        members = self.store.list_members()
        return min(members, key=lambda m: (not m.is_admin, m.id))

    def _spending(self) -> Spending:
        spending = self.services.maybe(keys.spending)
        assert spending is not None
        return spending

    def _meals(self) -> Meals | None:
        return self.services.maybe(keys.meals)

    def today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


class TakeoutModule(Module):
    """35a: a takeout order staged when everyone is running on empty at dinner time."""

    name = "takeout"
    title = "Takeout rescue"
    summary = (
        "On a night when everyone is worn out and nobody has eaten, offers a saved takeout "
        "favourite within the budget; a person does the checkout."
    )
    website = "Save a few takeout favourites on the Takeout page (/takeout)."
    requires = ("spending", "meals")
    household = TakeoutSettings
    migrations = Path(__file__).parent / "takeout_schema"

    def install(self, ctx: ModuleContext) -> None:
        from themi_home.web import takeout_pages

        takeout = ctx.provide(Takeout(ctx.services))
        takeout.install()
        approvals = ctx.maybe(ApprovalsUI)
        if approvals is not None:
            approvals.timely.add(CATEGORY)  # dinner can't wait for a good moment
        ctx.periodic("takeout.rescue", CHECK_EVERY, takeout.rescue)
        ctx.web(takeout_pages.routes)
