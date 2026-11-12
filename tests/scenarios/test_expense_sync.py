"""EX4b: expense sheets kept in step in Google Sheets. Erin's Google account is linked with
Drive allowed; the clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gsheets_api import FakeGsheets
from tests.scenarios.harness import Scenario
from tests.scenarios.test_expense_fill import MERIT, receipt
from tests.scenarios.test_expense_sheets import add, expenses, field, make, value
from tests.scenarios.test_gmail import link
from tests.scenarios.test_spending import inbox
from tests.scenarios.test_triage import ERIN
from themi import clock
from themi.autonomy.engine import Decision
from themi.core import keys
from themi_home.expense_sync import (
    COLOURS,
    GONE_TEXT,
    RULE_TEXT,
    ExpenseSync,
    entry_status,
    header,
    row_cells,
)
from themi_home.expenses import Entry, Field, Value

__all__ = ["inbox"]

KITCHEN = {
    "book_title": "Kitchen project", "shared": True,
    "sheets": [{"title": "Kitchen project", "mode": "custom", "counts_as_spending": True,
                "keywords": ["kitchen", "paint"],
                "fields": [field("Amount", "money", True), field("Date", "date", True),
                           field("What")]}],
}  # fmt: skip
AMBER, GREEN, BLUE = COLOURS["unverified"], COLOURS["verified"], COLOURS["user_estimate"]


def sync(scenario: Scenario) -> ExpenseSync:
    found = scenario.app.services.maybe(keys.expense_sync)
    assert found is not None
    return found


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gsheets: FakeGsheets, site: httpx.AsyncClient
) -> FakeGsheets:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gsheets


async def kitchen(scenario: Scenario, *, rule: str = "Yes, always") -> str:
    """Erin makes the kitchen project sheet and puts it in Google Sheets. Its id."""
    await make(scenario, "Erin", "Track what we spend on the kitchen project", KITCHEN)
    await scenario.tap("Erin", "Make it")
    assert scenario.inbox("Erin")[-1] == (
        "Put Kitchen project in Google Sheets? Which account should it live in?"
    )
    assert scenario.last_buttons("Erin") == [ERIN, "Not now"]
    await scenario.tap("Erin", ERIN)
    assert scenario.inbox("Erin")[-1] == RULE_TEXT
    await scenario.tap("Erin", rule)
    book = expenses(scenario).books(scenario.member("Erin"))[-1]
    assert book.google_spreadsheet_id is not None
    return book.google_spreadsheet_id


async def test_a_new_book_goes_in_google_sheets_and_keeps_up(
    scenario: Scenario, linked: FakeGsheets
) -> None:
    sid = await kitchen(scenario)
    assert linked.spreadsheets[sid].title == "Kitchen project"
    assert linked.values(sid, "Kitchen project", shown=True) == [
        ["Amount", "Date", "What", "Status"]
    ]
    assert scenario.edits("Erin")[-1]["text"] == (
        "It'll keep itself up to date. (The Rules page can change that.)"
    )

    await add(scenario, "Erin", "About $40 on paint, pretty sure", "",
              [value("amount", "40", estimate=True), value("what", "paint")])  # fmt: skip
    await scenario.run_periodic("expense_sync.drain")
    assert linked.values(sid, "Kitchen project", shown=True)[1] == [
        40.0,
        "2026-10-21",
        "paint",
        "Your estimate",
    ]
    assert linked.colour(sid, "Kitchen project", 1, 1) == BLUE
    assert linked.note(sid, "Kitchen project", 1, 1) == (
        "Your estimate, from their estimate. 80% sure."
    )
    assert linked.colour(sid, "Kitchen project", 1, 4) == BLUE  # the Status column too


async def test_a_receipt_fill_reaches_the_spreadsheet_and_a_check_turns_it_green(
    scenario: Scenario, linked: FakeGsheets, inbox: FakeGmail
) -> None:
    scenario.primary.queue_tool_call("put_in_google_sheets", {"book": "takeout"})
    await scenario.say("Erin", "Put the takeout sheet in Google Sheets")
    await scenario.tap("Erin", ERIN)
    await scenario.tap("Erin", "Yes, always")
    book = expenses(scenario).book(expenses(scenario).takeout_sheet().book_id)
    sid = book.google_spreadsheet_id
    assert sid is not None

    email = await receipt(scenario, inbox, MERIT, 8420)
    await scenario.run_periodic("expense_sync.drain")
    tab = "Takeout & eating out"
    assert linked.values(sid, tab, shown=True)[1] == [
        84.2,
        "2026-10-21",
        "Merit",
        "takeout",
        "",
        "Filled in by Themi",
    ]
    assert linked.colour(sid, tab, 1, 1) == AMBER
    gmail_id = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (email,))
    note = linked.note(sid, tab, 1, 1)
    assert note.startswith(
        "Filled in by Themi, from a receipt email. 95% sure. https://mail.google.com/"
    )
    assert note.endswith(f"{gmail_id}.")

    scenario.primary.queue_tool_call("verify_expense", {"expense": 1})
    scenario.primary.queue_text("Checked.")
    await scenario.say("Erin", "The Merit one is right")
    assert expenses(scenario).entry(1).values["amount"].status == "verified"  # the database first
    assert linked.colour(sid, tab, 1, 1) == AMBER  # the cells at the next sync
    await scenario.run_periodic("expense_sync.drain")
    assert linked.colour(sid, tab, 1, 1) == GREEN
    assert linked.values(sid, tab)[1][-1] == "Checked"
    assert len(linked.values(sid, tab)) == 2  # updated in place, never a second row


async def test_asking_first_is_one_approval_a_sheet_a_day(
    scenario: Scenario, linked: FakeGsheets
) -> None:
    sid = await kitchen(scenario, rule="Ask me")
    erin = scenario.member("Erin")
    autonomy = scenario.app.services.autonomy
    await add(scenario, "Erin", "$40 on paint", "kitchen project", [value("amount", "40")])
    await add(scenario, "Erin", "$12 on tape", "kitchen project", [value("amount", "12")])
    await scenario.run_periodic("expense_sync.drain")
    (action,) = autonomy.awaiting(erin)
    assert action.summary == "Update Kitchen project in Google Sheets (2 changes)"
    assert len(linked.values(sid, "Kitchen project")) == 1  # nothing written yet
    await scenario.run_periodic("expense_sync.drain")
    assert len(autonomy.awaiting(erin)) == 1  # not asked twice

    await autonomy.resolve(action.id, Decision.APPROVE, by=erin)
    assert len(linked.values(sid, "Kitchen project")) == 3

    await add(scenario, "Erin", "$8 on brushes", "kitchen project", [value("amount", "8")])
    await scenario.run_periodic("expense_sync.drain")
    assert autonomy.awaiting(erin) == []  # the yes covers the rest of the day
    assert len(linked.values(sid, "Kitchen project")) == 4

    clock.advance(timedelta(days=1))
    await add(scenario, "Erin", "$5 on rags", "kitchen project", [value("amount", "5")])
    await scenario.run_periodic("expense_sync.drain")
    assert [a.summary for a in autonomy.awaiting(erin)] == [
        "Update Kitchen project in Google Sheets (1 change)"
    ]


async def test_a_deleted_spreadsheet_is_forgotten_and_said_once(
    scenario: Scenario, linked: FakeGsheets
) -> None:
    sid = await kitchen(scenario)
    linked.delete(sid)
    await add(scenario, "Erin", "$40 on paint", "kitchen project", [value("amount", "40")])
    before = len(scenario.inbox("Erin"))
    await scenario.run_periodic("expense_sync.drain")
    await scenario.advance(minutes=1)
    assert scenario.inbox("Erin")[before:] == [GONE_TEXT.format(book="Kitchen project")]
    book = expenses(scenario).books(scenario.member("Erin"))[-1]
    assert book.google_spreadsheet_id is None

    await add(scenario, "Erin", "$12 on tape", "kitchen project", [value("amount", "12")])
    await scenario.run_periodic("expense_sync.drain")
    await scenario.advance(minutes=1)
    assert all("deleted" not in t for t in scenario.inbox("Erin")[before + 1 :])  # once
    assert sync(scenario).waiting() == []

    scenario.primary.queue_tool_call("put_in_google_sheets", {"book": "kitchen project"})
    await scenario.say("Erin", "Put the kitchen project in Google Sheets again")
    await scenario.tap("Erin", ERIN)  # it can be made again
    again = expenses(scenario).book(book.id).google_spreadsheet_id
    assert again is not None and again != sid
    assert len(linked.values(again, "Kitchen project")) == 3  # with everything on it


async def test_a_tab_deleted_in_google_comes_back(scenario: Scenario, linked: FakeGsheets) -> None:
    sid = await kitchen(scenario)
    await add(scenario, "Erin", "$40 on paint", "kitchen project", [value("amount", "40")])
    await scenario.run_periodic("expense_sync.drain")
    linked.delete_tab(sid, "Kitchen project")
    await add(scenario, "Erin", "$12 on tape", "kitchen project", [value("amount", "12")])
    await scenario.run_periodic("expense_sync.drain")
    assert [r[1] for r in linked.values(sid, "Kitchen project")[1:]] == [40.0, 12.0]


async def test_a_new_sheet_becomes_a_tab(scenario: Scenario, linked: FakeGsheets) -> None:
    sid = await kitchen(scenario)
    await make(scenario, "Erin", "Add a receipts-to-return tab to the kitchen project", {
        "book_title": "Kitchen project", "shared": True,
        "sheets": [{"title": "Returns", "mode": "custom", "counts_as_spending": False,
                    "keywords": ["return"],
                    "fields": [field("Amount", "money", True), field("Store")]}],
    }, book="kitchen project")  # fmt: skip
    await scenario.tap("Erin", "Make it")
    await scenario.run_periodic("expense_sync.drain")
    assert linked.titles(sid) == ["Kitchen project", "Returns"]
    assert linked.values(sid, "Returns", shown=True) == [["Amount", "Store", "Status"]]

    returns = expenses(scenario).sheets(expenses(scenario).books(scenario.member("Erin"))[-1].id)[1]
    expenses(scenario).rename_sheet(returns.id, "To return")
    expenses(scenario).move_tab(returns.id, 0)
    await scenario.run_periodic("expense_sync.drain")
    assert linked.titles(sid) == ["To return", "Kitchen project"]
    expenses(scenario).archive_sheet(returns.id)  # put away in Themi: its tab goes
    await scenario.run_periodic("expense_sync.drain")
    assert linked.titles(sid) == ["Kitchen project"]


async def test_a_day_of_failures_is_said_once(scenario: Scenario, linked: FakeGsheets) -> None:
    sid = await kitchen(scenario)
    linked.fail("get", 503, times=50)
    await add(scenario, "Erin", "$40 on paint", "kitchen project", [value("amount", "40")])
    before = len(scenario.inbox("Erin"))
    for _ in range(12):  # backing off, for a day and more
        await scenario.run_periodic("expense_sync.drain")
        await scenario.advance(hours=3)
    told = [t for t in scenario.inbox("Erin")[before:] if "hasn't taken the changes" in t]
    assert told == [
        "Google Sheets hasn't taken the changes to Kitchen project since yesterday (it asked "
        "Themi to slow down). Themi keeps trying, and the website has everything meanwhile."
    ]
    linked.failures.clear()
    clock.advance(timedelta(hours=6))
    await scenario.run_periodic("expense_sync.drain")
    assert len(linked.values(sid, "Kitchen project")) == 2


def test_the_cells_per_status() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 10, 21, tzinfo=UTC)
    fields = [
        Field(1, 1, "amount", "Amount", "money", (), True, 0),
        Field(2, 1, "vendor", "Vendor", "text", (), False, 1),
        Field(3, 1, "purpose", "Purpose", "text", (), True, 2),
    ]
    entry = Entry(7, 1, 1, "email", 3, now, None, {
        "amount": Value.filled(8420, 0.95, "email_receipt", "g1", "Total $84.20"),
        "vendor": Value.said("Merit"),
    })  # fmt: skip
    cells = row_cells(entry, fields, lambda v: "https://link" if v.source_ref else "")
    assert [c.value for c in cells] == [84.2, "Merit", "", "Missing"]
    assert [c.colour for c in cells] == [AMBER, GREEN, COLOURS["missing"], COLOURS["missing"]]
    assert cells[0].note == "Filled in by Themi, from a receipt email. 95% sure. https://link."
    assert cells[2].note == "Missing"
    assert entry_status(entry, fields[:2]) == "unverified"
    assert header(fields) == ["Amount", "Vendor", "Purpose", "Status"]
