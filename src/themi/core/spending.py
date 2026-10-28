"""Money spent: takeout, eating out and business expenses (X1, bug #36 and idea #37).

- Said in chat ("just spent $51.97 on DoorDash", "$40 business lunch at Merit"):
  `log_spending`, kept at once (it's Themi's own record, nothing outside changes), and told
  back with the month's takeout so far against the family's budget, in money words.
- A takeout receipt in email (triage finds receipts; the pantry reads them) becomes a spend
  too, quietly. One already said in chat (the same amount within two days) is the same
  meal: the receipt is attached to it rather than counted twice, and the other way round.
- Business expenses are marked when they say so ("for work", "business lunch"), and each
  person's month of them exports as CSV from the website, with the receipt email linked
  when there is one.

Takeout and eating out are the household's (the budget is the family's); business
expenses are each person's own.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.accounts.setup import parse_money_to_cents
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

KINDS = ("takeout", "eating_out", "other")
KIND_WORDS = {"takeout": "takeout", "eating_out": "eating out", "other": "other"}
SAME_MEAL = timedelta(days=2)  # a receipt and a chat spend this close, same amount: one meal
MAX_CENTS = 10_000_00


@dataclass(frozen=True)
class Spend:
    id: int
    member_id: int
    amount_cents: int
    place: str
    kind: str
    business: bool
    note: str
    spent_on: date
    email_id: int | None
    source: str


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _spend(row: dict[str, Any]) -> Spend:
    return Spend(
        row["id"], row["member_id"], row["amount_cents"], row["place"], row["kind"],
        bool(row["business"]), row["note"], date.fromisoformat(row["spent_on"]),
        row["email_id"], row["source"],
    )  # fmt: skip


def month_of(text: str, today: date) -> date:
    """The first of the month they mean: 'YYYY-MM', or '' for this month."""
    text = text.strip()
    if not text:
        return today.replace(day=1)
    try:
        return date.fromisoformat(f"{text[:7]}-01")
    except ValueError as exc:
        raise ToolFailed(f"'{text}' isn't a month like 2026-10.") from exc


def _next_month(first: date) -> date:
    return (first + timedelta(days=32)).replace(day=1)


class Spending:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.spending = self
        for t in (log_spending, spending_summary, mark_business_expense, remove_spending):
            self.services.tools.register(t)

    # ----- keeping them -------------------------------------------------------------------

    def log(
        self, member: Member, cents: int, place: str, kind: str, *, business: bool = False,
        note: str = "", on: date | None = None,
    ) -> Spend:  # fmt: skip
        """A spend said in chat. An emailed receipt for the same meal already here: that's
        the one (ToolDeclined says so)."""
        if kind not in KINDS:
            raise InvalidValue(f"the kind is one of {', '.join(KINDS)}")
        if not 0 < cents <= MAX_CENTS:
            raise InvalidValue("that amount doesn't look right")
        on = on or self.today()
        same = self._same_meal(cents, kind, on, "email")
        if same is not None:
            if business and not same.business:
                self.mark_business(same.id, member, True)
            raise ToolDeclined(
                f"Already logged from the receipt email: {self.describe(same)}. Nothing new "
                "was added."
            )
        spend_id = self.db.execute(
            "INSERT INTO spending (member_id, amount_cents, place, kind, business, note, "
            "spent_on, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'chat', ?)",
            (member.id, cents, place[:80], kind, int(business), note[:200], on.isoformat(),
             to_utc_iso(clock.now())),
        )  # fmt: skip
        return self.get(spend_id)

    def from_receipt(
        self, member: Member, email_id: int, place: str, cents: int, when: datetime
    ) -> Spend | None:
        """A takeout receipt from email. Said in chat already: the receipt joins it."""
        if cents <= 0 or self.db.one("SELECT 1 FROM spending WHERE email_id = ?", (email_id,)):
            return None
        on = when.astimezone(self._tz()).date()
        same = self._same_meal(cents, "takeout", on, "chat")
        if same is not None:
            self.db.execute("UPDATE spending SET email_id = ? WHERE id = ?", (email_id, same.id))
            return self.get(same.id)
        spend_id = self.db.execute(
            "INSERT INTO spending (member_id, amount_cents, place, kind, business, note, "
            "spent_on, email_id, source, created_at) "
            "VALUES (?, ?, ?, 'takeout', 0, '', ?, ?, 'email', ?)",
            (member.id, cents, place[:80], on.isoformat(), email_id, to_utc_iso(clock.now())),
        )
        return self.get(spend_id)

    def _same_meal(self, cents: int, kind: str, on: date, source: str) -> Spend | None:
        unmatched = "email_id IS NULL" if source == "chat" else "email_id IS NOT NULL"
        row = self.db.one(
            f"SELECT * FROM spending WHERE source = ? AND {unmatched} AND amount_cents = ? "
            "AND kind = ? AND spent_on BETWEEN ? AND ? ORDER BY id DESC",
            (source, cents, kind, (on - SAME_MEAL).isoformat(), (on + SAME_MEAL).isoformat()),
        )
        return _spend(row) if row else None

    def get(self, spend_id: int) -> Spend:
        row = self.db.one("SELECT * FROM spending WHERE id = ?", (spend_id,))
        if row is None:
            raise InvalidValue(f"there's no spend {spend_id}")
        return _spend(row)

    def _editable(self, spend_id: int, member: Member) -> Spend:
        """Their own; an admin may also fix the household's (never another's business ones)."""
        spend = self.get(spend_id)
        if spend.member_id != member.id and (spend.business or not member.is_admin):
            raise InvalidValue("that one is someone else's")
        return spend

    def mark_business(self, spend_id: int, member: Member, business: bool) -> Spend:
        spend = self._editable(spend_id, member)
        self.db.execute("UPDATE spending SET business = ? WHERE id = ?", (int(business), spend.id))
        return self.get(spend.id)

    def remove(self, spend_id: int, member: Member) -> Spend:
        spend = self._editable(spend_id, member)
        self.db.execute("DELETE FROM spending WHERE id = ?", (spend.id,))
        return spend

    # ----- reading them -------------------------------------------------------------------

    def month(
        self, first: date, *, kind: str | None = None, business_of: Member | None = None
    ) -> list[Spend]:
        """A month's spends, oldest first: one kind (the household's), or one person's
        business expenses, or the household's takeout and eating out plus `business_of`'s."""
        rows = self.db.query(
            "SELECT * FROM spending WHERE spent_on >= ? AND spent_on < ? ORDER BY spent_on, id",
            (first.isoformat(), _next_month(first).isoformat()),
        )
        spends = [_spend(r) for r in rows]
        if kind == "business":
            assert business_of is not None
            return [s for s in spends if s.business and s.member_id == business_of.id]
        if kind is not None:
            return [s for s in spends if s.kind == kind and not s.business]
        return [
            s
            for s in spends
            if (not s.business and s.kind != "other")
            or (business_of is not None and s.member_id == business_of.id)
        ]

    def takeout_words(self, today: date | None = None) -> str:
        """ "Takeout this month: $51.97 of the $300.00 budget ($248.03 left)." """
        first = (today or self.today()).replace(day=1)
        spent = sum(s.amount_cents for s in self.month(first, kind="takeout"))
        family = self.store.get_family()
        budget = family.takeout_budget_cents if family else 0
        if not budget:
            return f"Takeout this month: {money(spent)} (no monthly budget is set)."
        left = budget - spent
        rest = f"{money(left)} left" if left >= 0 else f"{money(-left)} over"
        return f"Takeout this month: {money(spent)} of the {money(budget)} budget ({rest})."

    def describe(self, spend: Spend) -> str:
        who = self.store.get_member(spend.member_id).name
        parts = [
            f"{spend.spent_on:%a %d %b}", money(spend.amount_cents), spend.place or "somewhere",
            KIND_WORDS[spend.kind] + (", business" if spend.business else ""), who,
        ]  # fmt: skip
        return " · ".join(parts)

    def business_csv(self, member: Member, first: date) -> str:
        """A person's business expenses for a month, for their records."""
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["date", "place", "amount", "kind", "note", "receipt"])
        for s in self.month(first, kind="business", business_of=member):
            writer.writerow(
                [s.spent_on.isoformat(), s.place, f"{s.amount_cents / 100:.2f}",
                 KIND_WORDS[s.kind], s.note, self._receipt_link(s)]
            )  # fmt: skip
        return out.getvalue()

    def _receipt_link(self, spend: Spend) -> str:
        if spend.email_id is None:
            return ""
        row = self.db.one(
            "SELECT e.gmail_id, a.address FROM emails e JOIN linked_accounts a "
            "ON a.id = e.account_id WHERE e.id = ?",
            (spend.email_id,),
        )
        if row is None:
            return ""
        return f"https://mail.google.com/mail/u/{row['address']}/#all/{row['gmail_id']}"

    def today(self) -> date:
        return clock.now().astimezone(self._tz()).date()

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _spending(ctx: ToolContext) -> Spending:
    spending = ctx.services.spending
    if spending is None:
        raise ToolFailed("Spending isn't set up.")
    return spending


@tool(
    "log_spending",
    "Keep a record of money they spent ('just spent $51.97 on DoorDash', 'a $40 business "
    "lunch at Merit'). amount: as they said it ('51.97'); place: where; kind: takeout "
    "(delivered or picked up restaurant food), eating_out (at a restaurant) or other; "
    "business: true only when they say it's for work; date: YYYY-MM-DD, or '' for today. "
    "Never a list item. The result says the month's takeout so far; say it back plainly.",
    {
        "amount": {"type": "string"},
        "place": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
        "business": {"type": "boolean"},
        "date": {"type": "string"},
    },
)
async def log_spending(ctx: ToolContext, args: dict[str, Any]) -> str:
    spending = _spending(ctx)
    try:
        cents = parse_money_to_cents(str(args["amount"]))
        on = date.fromisoformat(args["date"]) if str(args["date"]).strip() else None
    except (InvalidValue, ValueError) as exc:
        raise ToolFailed(f"Not logged: {exc}. Try an amount like 51.97.") from exc
    if on is not None and on > spending.today():
        raise ToolFailed("Not logged: that date hasn't come yet.")
    place = " ".join(str(args["place"]).split())
    try:
        spend = spending.log(
            ctx.member, cents, place, str(args["kind"]), business=bool(args["business"]), on=on
        )
    except InvalidValue as exc:
        raise ToolFailed(f"Not logged: {exc}.") from exc
    text = f"Logged (spend {spend.id}): {spending.describe(spend)}."
    if spend.business:
        text += " Marked as a business expense."
    if spend.kind == "takeout":
        text += " " + spending.takeout_words()
    return text


@tool(
    "spending_summary",
    "What was spent in a month: month 'YYYY-MM' or '' for this one; which: 'takeout', "
    "'eating_out', 'business' (their own work expenses) or 'all'. Lists each spend with its "
    "number (for mark_business_expense or remove_spending) and the totals.",
    {
        "month": {"type": "string"},
        "which": {"type": "string", "enum": ["takeout", "eating_out", "business", "all"]},
    },
)
async def spending_summary(ctx: ToolContext, args: dict[str, Any]) -> str:
    spending = _spending(ctx)
    first = month_of(str(args["month"]), spending.today())
    which = str(args["which"])
    spends = spending.month(first, kind=None if which == "all" else which, business_of=ctx.member)
    heading = f"{first:%B %Y}"
    if not spends:
        return f"{heading}: nothing logged for {which.replace('_', ' ')}."
    lines = [f"- spend {s.id}: {spending.describe(s)}" for s in spends]
    total = money(sum(s.amount_cents for s in spends))
    text = f"{heading}, {which.replace('_', ' ')}: {total} in all.\n" + "\n".join(lines)
    if which in ("takeout", "all") and first == spending.today().replace(day=1):
        text += "\n" + spending.takeout_words()
    if which == "business":
        text += "\nThe website's Spending page has this month as a CSV to download."
    return text


@tool(
    "mark_business_expense",
    "Mark one of their spends as a business expense, or not ('that lunch was for work'). "
    "spend: its number from log_spending or spending_summary.",
    {"spend": {"type": "integer"}, "business": {"type": "boolean"}},
)
async def mark_business_expense(ctx: ToolContext, args: dict[str, Any]) -> str:
    spending = _spending(ctx)
    try:
        spend = spending.mark_business(int(args["spend"]), ctx.member, bool(args["business"]))
    except InvalidValue as exc:
        raise ToolFailed(f"Not changed: {exc}.") from exc
    return f"{'A business expense' if spend.business else 'Not a business expense'} now: " + (
        spending.describe(spend)
    )


@tool(
    "remove_spending",
    "Take a spend off the record when they say it's wrong or a duplicate. spend: its number.",
    {"spend": {"type": "integer"}},
)
async def remove_spending(ctx: ToolContext, args: dict[str, Any]) -> str:
    spending = _spending(ctx)
    try:
        spend = spending.remove(int(args["spend"]), ctx.member)
    except InvalidValue as exc:
        raise ToolFailed(f"Not removed: {exc}.") from exc
    return f"Removed: {spending.describe(spend)}."
