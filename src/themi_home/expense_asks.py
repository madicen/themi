"""When Themi asks about expense sheets (EX2b, the spec's table).

| Sheet    | Missing field      | What the search found | What Themi does                      |
|----------|--------------------|-----------------------|--------------------------------------|
| Personal | Amount (critical)  | A matching receipt    | Fills it in quietly (EX2a)           |
| Personal | Amount (critical)  | Nothing               | Asks, once, after a wait             |
| Personal | Vendor or category | Nothing               | Leaves it empty, doesn't ask         |
| Business | Any field          | Little or nothing     | Saves the question for a review      |

- Personal (and custom) sheets: a key field still empty a while after the entry (24 hours by
  default, a setting: receipts often come hours after the meal) brings one message through
  the outbox at a good time: "What did dinner at Merit come to?" [Skip]. A typed amount fills
  it (`direct_user_input`). Skip leaves it empty and never asks again about that entry. A
  sheet with "ask about a key field" off is never asked about. One question at a time.
- Business sheets: what's missing waits for the person's review, one message on the day and
  time they chose (Friday 15:00 by default), listing the entries that need something, a
  button each and [Later] for the lot. Never during a break, burnout mode, a body double
  session or cooking: the "expense" kinds are in those pauses, so it waits until after.
- A receipt that fills the field before the question goes out takes it back
  (`Outbox.cancel`); a question that's still queued when its field is filled some other way
  is dropped as it's about to go (the outbox's refresher).
- The Spending page shows a "Needs filling in" list any time.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

from pydantic import field_validator

from themi import clock
from themi.accounts import Member
from themi.accounts.preferences import Preferences
from themi.accounts.store import parse_hhmm
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.localtime import to_utc_iso
from themi_home.expense_sheets import (
    ENTRY_BUTTON,
    ExpenseSheets,
    Shown,
    estimate_confidence,
    parse_value,
    show,
)
from themi_home.expenses import Entry, Expenses, Field, Sheet, Value

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

ASK_KIND = "expense"  # a question about one entry
REVIEW_KIND = "expense_review"  # the weekly business review
ASK_EVERY = timedelta(minutes=15)
REVIEW_MOST = 8  # entries with a button each on the review
RECENT = timedelta(days=14)  # entries older than this aren't asked about
ANSWER_FOR = timedelta(days=2)  # a typed answer counts this long after the question
# An answer on its own: "84.20", "$84", "it was 84 with the tip", "about 40 bucks".
BARE_AMOUNT = re.compile(
    r"^\s*(?:it was|it came to|that was|about|around|roughly|maybe)?\s*\$?\s*\d[\d,]*"
    r"(?:\.\d{1,2})?\s*(?:dollars|bucks|miles)?\s*(?:with (?:the )?tip|including tip)?"
    r"\s*[.!]?\s*$",
    re.IGNORECASE,
)
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

SKIPPED_TEXT = "Left empty, and I won't ask about that one again."
LATER_TEXT = "Okay, they'll keep until next week's review."
GOT_TEXT = "Got it: {what}."
REVIEW_TEXT = "Business expenses with something still empty, whenever suits:"
NOTHING_TEXT = "That one's filled in already."


class SpendingPreferences(Preferences):
    """EX2b: when Themi asks about expense sheets."""

    module: ClassVar[str] = "spending"
    expense_ask_after_hours: int = 24
    expense_review_day: str = "friday"
    expense_review_time: time = time(15, 0)

    @field_validator("expense_ask_after_hours")
    @classmethod
    def _after(cls, value: int) -> int:
        if not 1 <= value <= 168:
            raise ValueError("the wait before asking is between 1 hour and a week")
        return value

    @field_validator("expense_review_day")
    @classmethod
    def _day(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in DAYS:
            raise ValueError("the review day is a day of the week")
        return value

    @field_validator("expense_review_time", mode="before")
    @classmethod
    def _time(cls, value: object) -> time:
        if isinstance(value, time):
            return value
        if isinstance(value, str) and value.count(":") == 2:
            return time.fromisoformat(value)
        return parse_hhmm(value)  # type: ignore[arg-type]


def thing(entry: Entry, sheet: Sheet, fields: list[Field]) -> str:
    """How a question names an entry: "dinner at Merit on Tue 20 Oct", "the $40 one on Kitchen
    project"."""
    by_key = {f.key: f for f in fields}
    on = entry.get("date")
    day = f" on {date.fromisoformat(on):%a %-d %b}" if on else ""
    vendor = entry.get("vendor")
    category = entry.get("category")
    meal = {"eating_out": "eating out", "takeout": "takeout"}.get(str(category or ""), "")
    if vendor:
        return f"{meal + ' at ' if meal else ''}{vendor}{day}"
    for key in ("note", "purpose", "what", "description", "item"):
        if entry.get(key):
            return f"{entry.get(key)}{day}"
    if entry.get("amount") is not None and "amount" in by_key:
        return f"the {show(by_key['amount'], entry.get('amount'))} one on {sheet.title}{day}"
    return f"the one on {sheet.title}{day}"


def question(entry: Entry, sheet: Sheet, fields: list[Field], missing: Field) -> str:
    what = thing(entry, sheet, fields)
    if missing.type == "money":
        return f"What did {what} come to?"
    return f"For {what}: what was the {missing.label.lower()}?"


class ExpenseAsks:
    def __init__(self, services: Services, expenses: Expenses, sheets: ExpenseSheets) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.expenses = expenses
        self.sheets = sheets
        self.outbox = services.outbox

    def install(self) -> None:
        s = self.services
        s.provide(keys.expense_asks, self)
        s.text_handlers.append(self.on_text)
        self.sheets.entry_actions["skip"] = self.on_skip
        self.sheets.entry_actions["ask"] = self.on_ask
        s.button_handlers["expense_review"] = self.on_review_button
        self.outbox.refreshers[ASK_KIND] = self._refresh
        fill = s.maybe(keys.expense_fill)
        if fill is not None:
            fill.receipt_listeners.append(self.on_filled)

    def prefs(self, member: Member) -> SpendingPreferences:
        return self.store.preferences(member.id, SpendingPreferences)

    # ----- what needs filling in ---------------------------------------------------------

    def _skipped(self, entry_id: int) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM expense_asks WHERE entry_id = ? AND status = 'skipped'",
                (entry_id,),
            )
        )

    def needs_filling(self, member: Member) -> list[tuple[Entry, Sheet, list[Field]]]:
        """Their entries (on sheets they can see) with a key field still empty, newest first:
        the Spending page's list."""
        found = []
        for sheet in self.expenses.visible_sheets(member):
            fields = self.expenses.fields(sheet.id)
            for entry in self.expenses.entries([sheet.id]):
                if entry.member_id != member.id and sheet.member_id != member.id:
                    continue
                missing = entry.missing(fields)
                if missing and not self._skipped(entry.id):
                    found.append((entry, sheet, missing))
        return sorted(found, key=lambda x: x[0].id, reverse=True)

    # ----- asking ------------------------------------------------------------------------

    async def run(self) -> int:
        """Queue what's due: a personal question each (one at a time a person), and each
        person's business review on their day. Returns how many were queued."""
        queued = 0
        for member in self.store.list_members():
            if await self._ask_one(member):
                queued += 1
            if await self._review(member):
                queued += 1
        return queued

    def _open_ask(self, member: Member) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM expense_asks WHERE member_id = ? AND kind = 'ask' "
                "AND (status = 'queued' OR (status = 'sent' AND updated_at > ?))",
                (member.id, to_utc_iso(clock.now() - ANSWER_FOR)),
            )
        )

    async def _ask_one(self, member: Member) -> bool:
        if self._open_ask(member):
            return False
        wait = timedelta(hours=self.prefs(member).expense_ask_after_hours)
        now = clock.now()
        for entry, sheet, missing in reversed(self.needs_filling(member)):  # oldest first
            if sheet.mode == "business" or not sheet.prompt_on_missing_critical:
                continue
            if entry.member_id != member.id or not now - RECENT <= entry.created_at <= now - wait:
                continue
            if self.db.one("SELECT 1 FROM expense_asks WHERE entry_id = ?", (entry.id,)):
                continue  # asked once already
            await self._send_ask(member, entry, sheet, missing[0])
            return True
        return False

    async def _send_ask(
        self, member: Member, entry: Entry, sheet: Sheet, missing: Field, *, reply: bool = False
    ) -> None:
        fields = self.expenses.fields(sheet.id)
        stamp = to_utc_iso(clock.now())
        ask_id = self.db.execute(
            "INSERT INTO expense_asks (member_id, kind, entry_id, field_key, created_at, "
            "updated_at) VALUES (?, 'ask', ?, ?, ?, ?)",
            (member.id, entry.id, missing.key, stamp, stamp),
        )
        result = await self.outbox.send(
            member,
            question(entry, sheet, fields, missing),
            priority=Priority.REPLY if reply else Priority.NORMAL,
            kind=ASK_KIND,
            buttons=[Button("Skip", ENTRY_BUTTON, {"entry": entry.id, "action": "skip"})],
        )
        self.db.execute(
            "UPDATE expense_asks SET outbox_id = ?, status = ? WHERE id = ?",
            (result.outbox_id, "sent" if result.status == "sent" else "queued", ask_id),
        )

    def _refresh(self, member: Member, row: dict[str, Any]) -> str | None:
        """A question about to go: still worth asking? (Filled meanwhile: nothing to say.)"""
        ask = self.db.one("SELECT * FROM expense_asks WHERE outbox_id = ?", (row["id"],))
        if ask is None:
            return row["text"]
        entry = self.expenses.entry(ask["entry_id"])
        if entry.removed_at is not None or entry.get(ask["field_key"]) is not None:
            self._set(ask["id"], "cancelled")
            return None
        self._set(ask["id"], "sent")
        return row["text"]

    def _set(self, ask_id: int, status: str) -> None:
        self.db.execute(
            "UPDATE expense_asks SET status = ?, updated_at = ? WHERE id = ?",
            (status, to_utc_iso(clock.now()), ask_id),
        )

    def on_filled(self, entry: Entry) -> None:
        """A receipt filled the entry in: a question still waiting to go is taken back."""
        for ask in self.db.query(
            "SELECT * FROM expense_asks WHERE entry_id = ? AND status = 'queued'", (entry.id,)
        ):
            if entry.get(ask["field_key"]) is None:
                continue
            if ask["outbox_id"] is not None:
                self.outbox.cancel(ask["outbox_id"])
            self._set(ask["id"], "cancelled")

    # ----- answers -----------------------------------------------------------------------

    def _waiting(self, member: Member) -> dict[str, Any] | None:
        """The question they're most likely answering: the latest sent in the last two days."""
        return self.db.one(
            "SELECT * FROM expense_asks WHERE member_id = ? AND kind = 'ask' AND status = 'sent' "
            "AND updated_at > ? ORDER BY updated_at DESC, id DESC",
            (member.id, to_utc_iso(clock.now() - ANSWER_FOR)),
        )

    async def on_text(self, event: InboundEvent, member: Member, text: str) -> bool:
        """A typed answer: an amount for an amount question (short, or a Reply to it), or
        anything as a Reply to the question."""
        ask = self._waiting(member)
        if ask is None:
            return False
        entry = self.expenses.entry(ask["entry_id"])
        f = self.expenses.field(entry.sheet_id, ask["field_key"])
        if f is None or entry.removed_at is not None:
            return False
        replied = event.reply_to_message_id is not None and (
            event.reply_to_message_id == self.outbox.message_id(ask["outbox_id"] or 0)
        )
        words = text.split()
        if not replied and not (f.type in ("money", "number") and BARE_AMOUNT.match(text)):
            return False
        try:
            value = parse_value(f, text, self.sheets.today())
        except Exception:
            return False
        if value is None:
            return False
        said = " ".join(words)[:200]
        sure = estimate_confidence(text)
        answer = Value.estimate(value, sure, said) if sure else Value.said(value, said)
        entry = self.expenses.set(entry.id, f.key, answer)
        self._set(ask["id"], "answered")
        sheet = self.expenses.sheet(entry.sheet_id)
        what = self.sheets.describe(entry, sheet).split(": ", 1)[1]
        await self.outbox.send(member, GOT_TEXT.format(what=what), priority=Priority.REPLY)
        return True

    async def on_skip(self, event: InboundEvent, entry: Entry) -> Shown:
        member = self.store.get_member(event.member.id)
        stamp = to_utc_iso(clock.now())
        updated = self.db.update(
            "UPDATE expense_asks SET status = 'skipped', updated_at = ? WHERE entry_id = ? "
            "AND member_id = ? AND status IN ('queued', 'sent')",
            (stamp, entry.id, member.id),
        )
        if not updated:
            self.db.execute(
                "INSERT INTO expense_asks (member_id, kind, entry_id, status, created_at, "
                "updated_at) VALUES (?, 'ask', ?, 'skipped', ?, ?)",
                (member.id, entry.id, stamp, stamp),
            )
        return SKIPPED_TEXT

    async def on_ask(self, event: InboundEvent, entry: Entry) -> Shown:
        """A button on the review: ask about that entry's first empty key field now."""
        member = self.store.get_member(event.member.id)
        sheet = self.expenses.sheet(entry.sheet_id)
        missing = entry.missing(self.expenses.fields(sheet.id))
        if not missing:
            await self.outbox.send(member, NOTHING_TEXT, priority=Priority.REPLY)
            return None
        await self._send_ask(member, entry, sheet, missing[0], reply=True)
        week = str(self.db.scalar(
            "SELECT week FROM expense_asks WHERE member_id = ? AND kind = 'review' "
            "ORDER BY id DESC LIMIT 1",
            (member.id,),
        ) or "")  # fmt: skip
        return self.review_message(member, week, leaving_out=entry.id) or "That's all of them."

    # ----- the business review -----------------------------------------------------------

    def review_moment(self, member: Member, now: datetime) -> datetime:
        """This week's review moment for them, in their family's time."""
        prefs = self.prefs(member)
        family = self.store.get_family()
        tz = ZoneInfo(family.timezone if family else "UTC")
        local = now.astimezone(tz)
        monday = local.date() - timedelta(days=local.weekday())
        day = monday + timedelta(days=DAYS.index(prefs.expense_review_day))
        return datetime.combine(day, prefs.expense_review_time, tz)

    async def _review(self, member: Member) -> bool:
        now = clock.now()
        moment = self.review_moment(member, now)
        if now < moment:
            return False
        week = f"{moment.isocalendar().year}-W{moment.isocalendar().week:02d}"
        if self.db.one(
            "SELECT 1 FROM expense_asks WHERE member_id = ? AND kind = 'review' AND week = ?",
            (member.id, week),
        ):
            return False
        shown = self.review_message(member, week)
        if shown is None:
            return False
        text, buttons = shown
        result = await self.outbox.send(
            member, text, priority=Priority.NORMAL, kind=REVIEW_KIND, buttons=buttons
        )
        stamp = to_utc_iso(now)
        self.db.execute(
            "INSERT INTO expense_asks (member_id, kind, week, outbox_id, status, created_at, "
            "updated_at) VALUES (?, 'review', ?, ?, ?, ?, ?)",
            (member.id, week, result.outbox_id, "sent" if result.status == "sent" else "queued",
             stamp, stamp),
        )  # fmt: skip
        return True

    def review_message(
        self, member: Member, week: str, *, leaving_out: int | None = None
    ) -> tuple[str, list[Button]] | None:
        """The review: their business entries with a key field empty, a button each (oldest
        first, eight at most) and [Later]. None when there's nothing."""
        waiting = [
            (entry, sheet)
            for entry, sheet, _ in reversed(self.needs_filling(member))
            if sheet.mode == "business" and sheet.member_id == member.id
            and entry.id != leaving_out
        ]  # fmt: skip
        if not waiting:
            return None
        lines = [REVIEW_TEXT]
        buttons = []
        for entry, sheet in waiting[:REVIEW_MOST]:
            fields = self.expenses.fields(sheet.id)
            empty = ", ".join(f.label.lower() for f in entry.missing(fields))
            lines.append(f"- {thing(entry, sheet, fields)} ({sheet.title}): no {empty} yet")
            buttons.append(
                Button(
                    _label(entry, sheet, fields), ENTRY_BUTTON, {"entry": entry.id, "action": "ask"}
                )
            )
        if len(waiting) > REVIEW_MOST:
            lines.append(f"And {len(waiting) - REVIEW_MOST} more on the Spending page.")
        buttons.append(Button("Later", "expense_review", {"week": week}))
        return "\n".join(lines), buttons

    async def on_review_button(self, event: InboundEvent) -> None:
        """[Later]: the lot waits for next week's review."""
        assert event.button is not None
        member = self.store.get_member(event.member.id)
        if event.button.message_id is not None:
            await self.outbox.edit(member, event.button.message_id, LATER_TEXT)


def _label(entry: Entry, sheet: Sheet, fields: list[Field]) -> str:
    text = thing(entry, sheet, fields)
    return text if len(text) <= 40 else text[:39] + "…"
