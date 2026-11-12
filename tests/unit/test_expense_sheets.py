"""EX1a: expense sheets' data model, and X1's spending moved onto it."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.modules import bare_services
from tests.fixtures.family import SeededFamily, make_store, seed_family
from themi.accounts import InvalidValue
from themi.accounts.store import SYSTEM
from themi.core.tools import ToolFailed
from themi.storage.migrations import apply_track
from themi.storage.secrets import Secret
from themi_home.expense_sheets import ExpenseSheets
from themi_home.expenses import BUSINESS_FIELDS, Expenses, FieldDef, Value

TRACK = Path(__file__).parents[2] / "src" / "themi_home" / "spending_schema"
NOW = "2026-10-21T16:00:00+00:00"


def spend(
    family: SeededFamily, member_id: int, cents: int, place: str, kind: str, *,
    business: bool = False, email_id: int | None = None, source: str = "chat", note: str = "",
) -> int:  # fmt: skip
    return family.db.execute(
        "INSERT INTO spending (member_id, amount_cents, place, kind, business, note, spent_on, "
        "email_id, source, created_at) VALUES (?, ?, ?, ?, ?, ?, '2026-10-20', ?, ?, ?)",
        (member_id, cents, place, kind, int(business), note, email_id, source, NOW),
    )


@pytest.fixture
def before() -> SeededFamily:
    """A database from X1, before EX1a: chat, email and business spends."""
    family = seed_family(make_store())
    account = family.store.add_linked_account(
        SYSTEM, family.erin.id, "gmail", "erin@gmail.com", Secret("1//refresh")
    )
    for gmail_id in ("g-doordash", "g-thai"):
        family.db.execute(
            "INSERT INTO emails (account_id, gmail_id, thread_id, from_address, subject, "
            "received_at, created_at) VALUES (?, ?, 't', 'no-reply@doordash.com', 'Order', ?, ?)",
            (account.id, gmail_id, NOW, NOW),
        )
    spend(family, family.erin.id, 5197, "DoorDash", "takeout")
    spend(family, family.erin.id, 2550, "Thai Place", "takeout", email_id=1, source="email")
    spend(family, family.husband.id, 4210, "Merit", "eating_out", business=True, note="Henderson")
    spend(family, family.husband.id, 3100, "", "takeout", email_id=2)  # said, then its receipt
    return family


def test_the_spends_move_onto_the_built_in_sheets(before: SeededFamily) -> None:
    old = before.db.query("SELECT * FROM spending ORDER BY id")
    assert apply_track(before.db, "spending", TRACK)[0] == 1
    expenses = Expenses(before.db)

    takeout = expenses.takeout_sheet()
    assert (takeout.title, takeout.builtin, takeout.member_id) == (
        "Takeout & eating out",
        "takeout",
        None,
    )
    assert expenses.book(takeout.book_id).title == "Takeout & eating out"
    business = expenses.business_sheet(before.husband)
    assert expenses.book(business.book_id).title == "Business"
    assert expenses.book(business.book_id).member_id == before.husband.id
    assert [f.key for f in expenses.fields(business.id)] == [f.key for f in BUSINESS_FIELDS]

    assert [e.id for e in expenses.entries([takeout.id])] == [1, 2, 4]  # the same numbers
    (lunch,) = expenses.entries([business.id])
    assert (lunch.id, lunch.get("amount"), lunch.get("vendor"), lunch.get("note")) == (
        3,
        4210,
        "Merit",
        "Henderson",
    )
    assert lunch.get("category") == "eating_out"

    # The view reads as the table did, for one release.
    columns = ("id", "member_id", "amount_cents", "place", "kind", "business", "note",
               "spent_on", "email_id", "source", "created_at")  # fmt: skip
    view = before.db.query("SELECT * FROM spending ORDER BY id")
    assert [{c: r[c] for c in columns} for r in view] == [{c: r[c] for c in columns} for r in old]
    assert before.db.scalar("SELECT type FROM sqlite_master WHERE name = 'spending'") == "view"


def test_values_keep_their_lineage(before: SeededFamily) -> None:
    apply_track(before.db, "spending", TRACK)
    expenses = Expenses(before.db)
    said, receipt, _, joined = (expenses.entry(i) for i in (1, 2, 3, 4))

    amount = said.values["amount"]
    assert (amount.status, amount.confidence, amount.source_type) == (
        "verified",
        1.0,
        "direct_user_input",
    )
    assert said.origin == "chat" and said.email_id is None
    assert "vendor" in said.values and "note" not in said.values  # no note said: no value

    read = receipt.values["amount"]
    assert (read.status, read.confidence, read.source_type, read.source_ref) == (
        "unverified",
        0.95,
        "email_receipt",
        "g-doordash",
    )
    assert receipt.origin == "email" and receipt.email_id == 1
    assert receipt.get("date") == "2026-10-20"

    # Said in chat, then its receipt joined it: still what they said, with the receipt.
    assert joined.values["amount"].source_type == "direct_user_input"
    assert joined.email_id == 2
    assert "vendor" not in joined.values  # no place said: unknown, never made up


def test_a_database_with_no_spending_migrates_too() -> None:
    family = seed_family(make_store())
    apply_track(family.db, "spending", TRACK)
    expenses = Expenses(family.db)
    assert expenses.entries([expenses.takeout_sheet().id]) == []
    assert family.db.query("SELECT * FROM expense_sheets WHERE builtin = 'business'") == []
    sheet = expenses.business_sheet(family.erin)  # made when first needed
    assert expenses.book(sheet.book_id).member_id == family.erin.id


@pytest.fixture
def expenses(before: SeededFamily) -> Expenses:
    apply_track(before.db, "spending", TRACK)
    return Expenses(before.db)


def test_values_are_checked_against_their_field(before: SeededFamily, expenses: Expenses) -> None:
    sheet = expenses.takeout_sheet()
    with pytest.raises(InvalidValue, match="cents"):
        expenses.add(sheet, before.erin, {"amount": Value.said("12.50")})
    with pytest.raises(InvalidValue, match="one of takeout"):
        expenses.add(sheet, before.erin, {"category": Value.said("groceries")})
    with pytest.raises(InvalidValue, match="no mileage field"):
        expenses.add(sheet, before.erin, {"mileage": Value.said(3)})
    entry = expenses.add(
        sheet, before.erin, {"amount": Value.said(900), "vendor": Value.said(None)}
    )
    assert entry.get("vendor") is None and entry.values["vendor"].value is None


def test_a_change_replaces_the_value_and_is_heard(before: SeededFamily, expenses: Expenses) -> None:
    heard: list[tuple[int, int]] = []
    expenses.change_listeners.append(lambda entry, sheet: heard.append((entry, sheet)))
    sheet = expenses.takeout_sheet()
    entry = expenses.add(sheet, before.erin, {"amount": Value.estimate(4000, 0.8)})
    entry = expenses.set(
        entry.id, "amount", Value.filled(4120, 0.95, "email_receipt", "g-1", "Total $41.20")
    )
    assert entry.values["amount"].value == 4120
    assert (
        before.db.scalar("SELECT COUNT(*) FROM expense_values WHERE entry_id = ?", (entry.id,)) == 1
    )
    assert heard == [(entry.id, sheet.id)] * 2

    business = expenses.business_sheet(before.erin)
    moved = expenses.move(entry.id, business)
    assert moved.sheet_id == business.id and moved.get("amount") == 4120
    assert heard[-2:] == [(entry.id, sheet.id), (entry.id, business.id)]


def test_verifying_checks_every_value(before: SeededFamily, expenses: Expenses) -> None:
    entry = expenses.add(
        expenses.takeout_sheet(),
        before.erin,
        {
            "amount": Value.estimate(4000, 0.5),
            "vendor": Value.filled("Merit", 0.6, "calendar_event", "ev1", "Lunch at Merit"),
        },
    )
    checked = expenses.verify(entry.id)
    assert {v.status for v in checked.values.values()} == {"verified"}
    assert checked.values["vendor"].source_type == "calendar_event"  # where it came from stays


def test_books_hold_tabs_in_order(before: SeededFamily, expenses: Expenses) -> None:
    """Idea #167: the business spreadsheet has tabs for expenses, income and mileage."""
    business = expenses.business_sheet(before.husband)
    book = expenses.book(business.book_id)
    mileage = expenses.make_sheet(
        book, "Mileage", "business",
        [FieldDef("date", "Date", "date", critical=True),
         FieldDef("miles", "Miles", "number", critical=True)],
        counts_as_spending=False,
    )  # fmt: skip
    income = expenses.make_sheet(
        book, "Income", "business", [FieldDef("amount", "Amount", "money")]
    )
    assert [s.title for s in expenses.sheets(book.id)] == ["Business", "Mileage", "Income"]
    assert mileage.member_id == before.husband.id and not mileage.counts_as_spending
    expenses.move_tab(income.id, 1)
    assert [s.title for s in expenses.sheets(book.id)] == ["Business", "Income", "Mileage"]

    assert book in expenses.books(before.husband)
    assert book not in expenses.books(before.erin)  # his own
    assert expenses.can_see(before.erin, expenses.takeout_sheet())
    assert not expenses.can_see(before.erin, mileage)


def test_archiving_a_books_last_tab_archives_the_book(
    before: SeededFamily, expenses: Expenses
) -> None:
    book = expenses.make_book("Kitchen project", None)
    sheet = expenses.make_sheet(
        book, "Kitchen project", "custom", [FieldDef("amount", "Amount", "money")]
    )
    expenses.archive_sheet(sheet.id)
    assert expenses.book(book.id).archived_at is not None
    assert book.id not in [b.id for b in expenses.books(before.erin)]
    with pytest.raises(InvalidValue, match="built-in"):
        expenses.archive_sheet(expenses.takeout_sheet().id)


@pytest.fixture
def sheets(before: SeededFamily, expenses: Expenses) -> ExpenseSheets:
    return ExpenseSheets(bare_services(before.store), expenses)


def test_routing_by_words(before: SeededFamily, expenses: Expenses, sheets: ExpenseSheets) -> None:
    """The open decision: "for work" is Business; else each sheet's keywords decide."""
    kitchen = expenses.make_sheet(
        expenses.make_book("Kitchen project", None), "Kitchen project", "custom",
        [FieldDef("amount", "Amount", "money")], keywords=("paint", "kitchen"),
    )  # fmt: skip
    erin = before.erin
    assert sheets.route(erin, "$84 lunch for work at Merit") == expenses.business_sheet(erin)
    assert sheets.route(erin, "about $40 on paint") == kitchen
    assert sheets.route(erin, "dinner out at Nopa, $60") == expenses.takeout_sheet()
    assert sheets.route(erin, "$12 on stamps") is None  # the model asks which


def test_finding_a_sheet_by_name(
    before: SeededFamily, expenses: Expenses, sheets: ExpenseSheets
) -> None:
    business = expenses.business_sheet(before.husband)
    mileage = expenses.make_sheet(
        expenses.book(business.book_id),
        "Mileage",
        "business",
        [FieldDef("miles", "Miles", "number")],
    )
    husband = before.husband
    assert sheets.find_sheet(husband, "mileage") == mileage
    assert sheets.find_sheet(husband, str(mileage.id)) == mileage
    assert sheets.find_sheet(husband, "the business spreadsheet") == business
    assert sheets.find_sheet(husband, "takeout") == expenses.takeout_sheet()
    with pytest.raises(ToolFailed, match="Which sheet"):
        sheets.find_sheet(before.erin, "mileage")  # his own: not hers to see


def test_only_the_person_checks(
    before: SeededFamily, expenses: Expenses, sheets: ExpenseSheets
) -> None:
    entry = expenses.add(
        expenses.takeout_sheet(), before.erin, {"amount": Value.estimate(900, 0.5)}
    )
    with pytest.raises(ToolFailed, match="someone else's to check"):
        sheets.verify(before.husband, entry.id)
    assert sheets.verify(before.erin, entry.id).startswith("Checked: expense")
    own = expenses.add(
        expenses.business_sheet(before.husband), before.husband, {"amount": Value.said(1)}
    )
    with pytest.raises(ToolFailed, match="no expense"):
        sheets.verify(before.erin, own.id)  # can't even see it
