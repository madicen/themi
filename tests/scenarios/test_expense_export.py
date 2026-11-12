"""EX3: expense sheets as CSV with an audit trail, from the website and in chat. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import csv
import io
from datetime import date

import httpx
import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_expense_fill import MERIT, receipt
from tests.scenarios.test_expense_sheets import add, expenses, value
from tests.scenarios.test_spending import inbox
from themi_home.expense_export import RangeError, read_range
from themi_home.expenses import FieldDef

__all__ = ["inbox"]


def rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


@pytest.fixture
def travel(scenario: Scenario) -> int:
    husband = scenario.member("Husband")
    book = expenses(scenario).make_book("Business travel", husband)
    return expenses(scenario).make_sheet(
        book, "Business travel", "business",
        [FieldDef("amount", "Amount", "money", critical=True),
         FieldDef("date", "Date", "date", critical=True),
         FieldDef("vendor", "Vendor", "text"),
         FieldDef("purpose", "Purpose", "text", critical=True)],
    ).id  # fmt: skip


async def test_the_columns_and_the_audit_trail(
    scenario: Scenario, site: httpx.AsyncClient, travel: int
) -> None:
    await add(
        scenario, "Husband", "$412 at United, Denver, CO for the Acme pitch", "business travel",
        [value("amount", "412"), value("vendor", "United, Denver, CO"),
         value("purpose", "Acme pitch")],
    )  # fmt: skip
    await add(scenario, "Husband", "about $30 on a cab, pretty sure", "business travel",
              [value("amount", "30", estimate=True)])  # fmt: skip
    await sign_in(scenario, site, "Husband")
    got = await site.get(f"/expenses/{travel}.csv")
    assert got.headers["content-type"].startswith("text/csv")
    assert 'filename="business-travel-2026-10.csv"' in got.headers["content-disposition"]
    assert rows(got.text) == [
        ["expense", "Amount", "Date", "Vendor", "Purpose", "Amount status", "Amount confidence",
         "Date status", "Date confidence", "Vendor status", "Vendor confidence",
         "Purpose status", "Purpose confidence", "source", "source link"],
        ["1", "412.00", "2026-10-21", "United, Denver, CO", "Acme pitch", "Checked", "1.00",
         "Checked", "1.00", "Checked", "1.00", "Checked", "1.00", "direct_user_input", ""],
        ["2", "30.00", "2026-10-21", "", "", "Your estimate", "0.80", "Checked", "1.00", "", "",
         "Missing", "", "user_estimate; direct_user_input", ""],
    ]  # fmt: skip
    assert '"United, Denver, CO"' in got.text  # quoted, so the commas stay in one cell


async def test_only_who_can_see_it_and_only_when_its_on(
    scenario: Scenario, site: httpx.AsyncClient, travel: int
) -> None:
    await sign_in(scenario, site, "Erin")
    assert (await site.get(f"/expenses/{travel}.csv")).status_code == 404  # his own
    await sign_in(scenario, site, "Husband")
    assert (await site.get(f"/expenses/{travel}.csv")).status_code == 200
    expenses(scenario).set_sheet_options(travel, csv_enabled=False)
    assert (await site.get(f"/expenses/{travel}.csv")).status_code == 404
    assert (await site.get("/expenses/999.csv")).status_code == 404


async def test_the_date_range(scenario: Scenario, site: httpx.AsyncClient, travel: int) -> None:
    await add(scenario, "Husband", "$10 parking", "business travel", [value("amount", "10")])
    await add(scenario, "Husband", "$20 parking on the 2nd", "business travel",
              [value("amount", "20"), value("date", "2026-10-02")])  # fmt: skip
    await add(scenario, "Husband", "$30 in September", "business travel",
              [value("amount", "30"), value("date", "2026-09-30")])  # fmt: skip
    await sign_in(scenario, site, "Husband")

    async def amounts(query: str) -> list[str]:
        return [r[1] for r in rows((await site.get(f"/expenses/{travel}.csv{query}")).text)[1:]]

    assert await amounts("") == ["20.00", "10.00"]  # this month, by date
    assert await amounts("?from=2026-09-01&to=2026-10-02") == ["30.00", "20.00"]  # both kept
    assert await amounts("?from=2026-09-01") == ["30.00"]  # that month
    bad = await site.get(f"/expenses/{travel}.csv?from=2026-10-09&to=2026-10-01")
    assert bad.status_code == 400 and "before the start" in bad.text


def test_reading_a_range() -> None:
    today = date(2026, 10, 21)
    assert read_range("", "", today) == (date(2026, 10, 1), date(2026, 10, 31))
    assert read_range("2026-02-03", "", today) == (date(2026, 2, 3), date(2026, 2, 28))
    with pytest.raises(RangeError, match="like 2026-10-01"):
        read_range("Oct", "", today)


async def test_a_receipts_link_is_in_the_file(
    scenario: Scenario, site: httpx.AsyncClient, inbox: FakeGmail
) -> None:
    email = await receipt(scenario, inbox, MERIT, 8420)
    sheet = expenses(scenario).takeout_sheet()
    await sign_in(scenario, site, "Erin")
    (row,) = rows((await site.get(f"/expenses/{sheet.id}.csv")).text)[1:]
    gmail_id = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (email,))
    assert row[1] == "84.20" and row[-2] == "email_receipt"
    assert row[-1].startswith("https://mail.google.com/mail/u/") and row[-1].endswith(gmail_id)


async def test_the_business_csv_keeps_working(scenario: Scenario, site: httpx.AsyncClient) -> None:
    scenario.primary.queue_tool_call("log_spending", {
        "amount": "42.10", "place": "Merit", "kind": "eating_out", "business": True, "date": ""
    })  # fmt: skip
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "$42.10 business lunch at Merit")
    await sign_in(scenario, site, "Husband")
    exported = await site.get("/spending/business.csv?month=2026-10")
    assert exported.text.splitlines()[1] == "2026-10-21,Merit,42.10,eating out,,"


async def test_the_file_sent_in_chat(scenario: Scenario, travel: int) -> None:
    await add(scenario, "Husband", "$412 at United for the Acme pitch", "business travel",
              [value("amount", "412"), value("vendor", "United")])  # fmt: skip
    scenario.primary.queue_tool_call("send_expense_sheet", {"sheet": "travel", "month": "2026-10"})
    replies = await scenario.say("Husband", "Send me the travel sheet for October")
    assert replies == []  # the file is the answer
    (sent,) = scenario.telegram.calls("sendDocument")
    assert sent["document_name"] == "business-travel-2026-10.csv"
    assert sent["caption"] == "Business travel, October 2026: 1 entry."
    assert rows(sent["document_text"])[1][:4] == ["1", "412.00", "2026-10-21", "United"]
