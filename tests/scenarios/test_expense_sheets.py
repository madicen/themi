"""EX1b: expense sheets made and filled in from chat, and shown on the website. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_spending import tool_result
from themi.core import keys
from themi_home.expenses import Expenses


def expenses(scenario: Scenario) -> Expenses:
    found = scenario.app.services.maybe(keys.expenses)
    assert found is not None
    return found


def field(label: str, kind: str = "text", critical: bool = False, choices: Any = ()) -> dict:
    return {"label": label, "type": kind, "choices": list(choices), "critical": critical}


TRAVEL = {
    "book_title": "Business travel",
    "shared": False,
    "sheets": [
        {
            "title": "Business travel",
            "mode": "business",
            "counts_as_spending": True,
            "keywords": ["trip", "flight", "hotel"],
            "fields": [
                field("Amount", "money", True),
                field("Date", "date", True),
                field("Vendor"),
                field("Business purpose", critical=True),
            ],
        }
    ],
}


async def make(
    scenario: Scenario, name: str, said: str, proposal: dict, book: str = ""
) -> list[str]:
    scenario.primary.queue_tool_call("make_expense_sheet", {"request": said, "book": book})
    scenario.primary.queue_structured(proposal)
    return await scenario.say(name, said)


async def add(scenario: Scenario, name: str, said: str, sheet: str, values: list[dict]) -> str:
    scenario.primary.queue_tool_call("add_expense", {"sheet": sheet, "values": values})
    scenario.primary.queue_text("Okay.")
    await scenario.say(name, said)
    return tool_result(scenario)


def value(field_name: str, said: str, estimate: bool = False) -> dict:
    return {"field": field_name, "value": said, "estimate": estimate}


async def test_a_business_travel_sheet_made_in_chat_and_added_to(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    replies = await make(scenario, "Husband", "Start a sheet for business travel", TRAVEL)
    card = next(r for r in replies if r.startswith("Here's the sheet:"))
    assert "Business travel, yours (business)" in card
    assert "Fields: Amount, Date, Vendor, Business purpose" in card
    assert "Key fields (worth filling in): Amount, Date, Business purpose" in card
    assert scenario.last_buttons("Husband") == ["Make it", "Change it"]
    assert expenses(scenario).books(scenario.member("Husband"))[-1].title != "Business travel"

    await scenario.tap("Husband", "Make it")
    assert scenario.edits("Husband")[-1]["text"].startswith("Made: Business travel.")
    husband = scenario.member("Husband")
    book = expenses(scenario).books(husband)[-1]
    assert (book.title, book.member_id) == ("Business travel", husband.id)
    (sheet,) = expenses(scenario).sheets(book.id)

    result = await add(
        scenario, "Husband", "$412 for the flight to Denver, the Acme pitch", "business travel",
        [value("amount", "412"), value("vendor", "United"),
         value("business purpose", "Acme pitch")],
    )  # fmt: skip
    assert result == (
        "Added expense 1 on Business travel: $412.00 · Wed 21 Oct · United · Acme pitch."
    )
    (entry,) = expenses(scenario).entries([sheet.id])
    assert entry.values["amount"].source_type == "direct_user_input"
    assert entry.values["date"].status == "verified"  # said today

    await sign_in(scenario, site, "Husband")
    page = (await site.get(f"/spending/sheets/{sheet.id}")).text
    assert "expense 1: $412.00 · Wed 21 Oct · United · Acme pitch" in page
    assert "✓</span> Checked" in page
    await sign_in(scenario, site, "Erin")
    hidden = await site.get(f"/spending/sheets/{sheet.id}", follow_redirects=False)
    assert hidden.status_code == 303  # his own


async def test_change_it_takes_their_words(scenario: Scenario) -> None:
    await make(scenario, "Erin", "Track what we spend on the kitchen project", {
        "book_title": "Kitchen project", "shared": True,
        "sheets": [{"title": "Kitchen project", "mode": "custom", "counts_as_spending": True,
                    "keywords": ["kitchen", "paint"],
                    "fields": [field("Amount", "money", True), field("Date", "date", True)]}],
    })  # fmt: skip
    await scenario.tap("Erin", "Change it")
    assert (
        scenario.edits("Erin")[-1]["text"] == "How would you change it? Tell me in your own words."
    )
    scenario.primary.queue_structured({
        "book_title": "Kitchen project", "shared": True,
        "sheets": [{"title": "Kitchen project", "mode": "custom", "counts_as_spending": True,
                    "keywords": ["kitchen", "paint"],
                    "fields": [field("Amount", "money", True), field("Date", "date", True),
                               field("Room", "choice", choices=["kitchen", "pantry"])]}],
    })  # fmt: skip
    replies = await scenario.say("Erin", "add which room it was for, kitchen or pantry")
    assert any("Room (kitchen / pantry)" in r for r in replies)
    asked = [r for r in scenario.primary.requests if r.schema and "their words" in r.prompt]
    assert asked and "add which room it was for" in asked[-1].prompt
    await scenario.tap("Erin", "Make it")
    book = expenses(scenario).books(scenario.member("Erin"))[-1]
    assert (book.title, book.member_id) == ("Kitchen project", None)  # the household's


async def test_an_estimate_later_checked(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await make(scenario, "Erin", "Track what we spend on the kitchen project", {
        "book_title": "Kitchen project", "shared": True,
        "sheets": [{"title": "Kitchen project", "mode": "custom", "counts_as_spending": True,
                    "keywords": ["kitchen", "paint"],
                    "fields": [field("Amount", "money", True), field("Date", "date", True),
                               field("What", critical=False)]}],
    })  # fmt: skip
    await scenario.tap("Erin", "Make it")
    result = await add(
        scenario, "Erin", "About $40 on paint, pretty sure", "",
        [value("amount", "40", estimate=True), value("what", "paint")],
    )  # fmt: skip
    assert (
        result == "Added expense 1 on Kitchen project: $40.00 (your estimate) · Wed 21 Oct · paint."
    )
    entry = expenses(scenario).entry(1)
    assert (entry.values["amount"].status, entry.values["amount"].confidence) == (
        "user_estimate",
        0.8,
    )

    await sign_in(scenario, site, "Erin")
    sheet_id = entry.sheet_id
    page = (await site.get(f"/spending/sheets/{sheet_id}")).text
    assert "≈</span> Your estimate" in page and "80% sure" in page

    scenario.primary.queue_tool_call("verify_expense", {"expense": 1})
    scenario.primary.queue_text("Checked.")
    await scenario.say("Erin", "The paint one is right")
    assert (
        tool_result(scenario)
        == "Checked: expense 1 on Kitchen project: $40.00 · Wed 21 Oct · paint."
    )
    assert expenses(scenario).entry(1).values["amount"].status == "verified"

    scenario.primary.queue_tool_call("verify_expense", {"expense": 1})
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "Erin's paint is right")
    assert tool_result(scenario).startswith("That one is someone else's to check.")


async def test_a_business_book_with_expenses_income_and_mileage(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """Idea #167: the business spreadsheet has tabs for expenses, income and mileage."""
    husband = scenario.member("Husband")
    business = expenses(scenario).business_sheet(husband)  # his Business book's first tab
    replies = await make(
        scenario, "Husband", "The business spreadsheet should have expenses, income and mileage",
        {"book_title": "Business", "shared": False, "sheets": [
            {"title": "Income", "mode": "business", "counts_as_spending": False,
             "keywords": ["invoice", "paid me"],
             "fields": [field("Amount", "money", True), field("Date", "date", True),
                        field("Client", critical=True)]},
            {"title": "Mileage", "mode": "business", "counts_as_spending": False,
             "keywords": ["miles", "drove"],
             "fields": [field("Date", "date", True), field("Miles", "number", True),
                        field("From"), field("To"), field("Purpose", critical=True)]},
        ]},
        book="the business spreadsheet",
    )  # fmt: skip
    card = next(r for r in replies if r.startswith("Here's the spreadsheet:"))
    assert "New tabs in Business:" in card
    assert "- Mileage (business) (not counted as spending)" in card
    await scenario.tap("Husband", "Make it")
    book = expenses(scenario).book(business.book_id)
    tabs = expenses(scenario).sheets(book.id)
    assert [t.title for t in tabs] == ["Business", "Income", "Mileage"]

    await add(
        scenario, "Husband", "Drove 32 miles to the Acme office", "mileage",
        [value("miles", "32"), value("to", "Acme office"), value("purpose", "pitch")],
    )  # fmt: skip
    await add(scenario, "Husband", "$60 lunch with Acme", "business",
              [value("amount", "60"), value("vendor", "Nopa"),
               value("business purpose", "Acme")])  # fmt: skip
    scenario.primary.queue_tool_call("expense_summary", {"sheet": "", "month": ""})
    scenario.primary.queue_text("Here.")
    await scenario.say("Husband", "What's on my sheets this month?")
    summary = tool_result(scenario)
    assert "- Mileage: 1 entries" in summary
    assert "Spent in all (sheets that count as spending): $60.00." in summary  # miles aren't money

    scenario.primary.queue_tool_call(
        "change_expense_sheet",
        {"sheet": "mileage", "rename": "Driving", "position": 2, "archive": False},
    )  # fmt: skip
    scenario.primary.queue_text("Done.")
    await scenario.say("Husband", "Call the mileage tab Driving and put it second")
    assert tool_result(scenario) == "Done: renamed Driving; tabs now Business, Driving, Income."

    await sign_in(scenario, site, "Husband")
    page = (await site.get("/spending")).text
    assert ">Business</a>, <a" in page and ">Driving</a>" in page
