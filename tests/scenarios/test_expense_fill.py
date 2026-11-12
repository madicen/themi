"""EX2a: expense sheets filled in from receipts, calendars and the chat around a spend. The
clock starts Wednesday 21 October 2026, 9 am; Erin's Gmail is linked and watched."""

from __future__ import annotations

from datetime import timedelta

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_expense_sheets import add, expenses, value
from tests.scenarios.test_spending import inbox
from tests.scenarios.test_triage import arrive, verdict
from themi import clock
from themi.localtime import to_utc_iso

__all__ = ["inbox"]

MERIT = {
    "sender": "Merit <receipts@meritsf.com>",
    "subject": "Your receipt from Merit",
    "text": "Merit\nBurrata $14.00\nSteak frites $58.00\nTip $12.20\nTotal $84.20",
}


async def receipt(
    scenario: Scenario, fake: FakeGmail, mail: dict, total: int, kind: str = "takeout"
) -> int:
    (email,) = await arrive(scenario, fake, mail)
    scenario.primary.queue_structured({"results": [verdict(email, "receipt", mail["subject"])]})
    scenario.primary.queue_structured(
        {"kind": kind, "vendor": "Merit", "total_cents": total, "items": []}
    )
    await scenario.run_periodic("email.triage")
    return email


async def test_a_lunch_said_in_chat_then_its_receipt_fills_the_amount_quietly(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    erin = scenario.member("Erin")
    await add(
        scenario, "Erin", "Lunch at Merit with Henderson, for work", "business",
        [value("vendor", "Merit"), value("business purpose", "Henderson lunch")],
    )  # fmt: skip
    (entry,) = expenses(scenario).entries([expenses(scenario).business_sheet(erin).id])
    assert entry.get("amount") is None

    before = len(scenario.inbox("Erin"))
    email = await receipt(scenario, inbox, MERIT, 8420)
    entry = expenses(scenario).entry(entry.id)
    amount = entry.values["amount"]
    assert (amount.value, amount.status, amount.confidence, amount.source_type) == (
        8420,
        "unverified",
        0.95,
        "email_receipt",
    )
    assert amount.evidence == "Total $84.20"  # the line, quoted
    assert amount.source_ref == scenario.app.db.scalar(
        "SELECT gmail_id FROM emails WHERE id = ?", (email,)
    )
    assert entry.values["vendor"].source_type == "direct_user_input"  # what she said stays
    assert entry.email_id == email
    assert scenario.inbox("Erin")[before:] == []  # quietly
    assert expenses(scenario).entries([expenses(scenario).takeout_sheet().id]) == []  # not twice


async def test_a_receipt_for_a_meal_never_mentioned(scenario: Scenario, inbox: FakeGmail) -> None:
    email = await receipt(scenario, inbox, MERIT, 8420)
    (entry,) = expenses(scenario).entries([expenses(scenario).takeout_sheet().id])
    assert (entry.origin, entry.email_id, entry.get("amount"), entry.get("vendor")) == (
        "email",
        email,
        8420,
        "Merit",
    )
    assert {v.status for v in entry.values.values()} == {"unverified"}
    assert entry.values["vendor"].evidence == "Merit"


async def test_a_total_the_receipt_doesnt_say_isnt_kept(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await receipt(scenario, inbox, MERIT, 9999)  # the model's number, written nowhere
    (entry,) = expenses(scenario).entries([expenses(scenario).takeout_sheet().id])
    assert entry.get("amount") is None and entry.get("vendor") == "Merit"


def calendar_lunch(scenario: Scenario, title: str, location: str) -> None:
    db = scenario.app.db
    account = db.scalar("SELECT id FROM linked_accounts ORDER BY id LIMIT 1")
    start = clock.now() + timedelta(hours=3)
    db.execute(
        "INSERT INTO calendar_entries (member_id, account_id, calendar_id, event_id, title, "
        "location, starts_at, ends_at, fetched_at) VALUES (?, ?, 'erin@example.com', 'ev1', ?, "
        "?, ?, ?, ?)",
        (scenario.member("Erin").id, account, title, location, to_utc_iso(start),
         to_utc_iso(start + timedelta(hours=1)), to_utc_iso(clock.now())),
    )  # fmt: skip


async def test_a_calendar_lunch_fills_the_place_and_why(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    calendar_lunch(scenario, "Lunch with Henderson", "Merit, 123 Valencia St")
    await add(scenario, "Erin", "$84 business lunch", "business", [value("amount", "84")])
    await scenario.run_periodic("expenses.fill")
    (entry,) = expenses(scenario).entries(
        [expenses(scenario).business_sheet(scenario.member("Erin")).id]
    )
    vendor, purpose = entry.values["vendor"], entry.values["purpose"]
    assert (vendor.value, vendor.confidence, vendor.source_type, vendor.source_ref) == (
        "Merit",
        0.6,
        "calendar_event",
        "erin@example.com|ev1",
    )
    assert purpose.value == "Lunch with Henderson" and purpose.status == "unverified"
    assert entry.values["amount"].status == "verified"  # hers, untouched


async def test_an_event_alone_never_makes_an_entry(scenario: Scenario, inbox: FakeGmail) -> None:
    calendar_lunch(scenario, "Dinner at Nopa", "")
    await scenario.run_periodic("expenses.fill")
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM expense_entries") == 0


async def test_the_chat_around_a_spend_fills_what_it_says(scenario: Scenario) -> None:
    scenario.primary.queue_text("Sounds lovely.")
    await scenario.say("Erin", "Had lunch with Henderson at Merit today")
    await add(scenario, "Erin", "$84 for that lunch, for work", "business", [value("amount", "84")])
    await scenario.run_periodic("expenses.fill")
    from_chat = "SELECT COUNT(*) FROM expense_values WHERE source_type = 'chat_context'"
    assert scenario.app.db.scalar(from_chat) == 0

    clock.advance(timedelta(minutes=6))  # once the conversation's had time to go on
    scenario.primary.queue_structured(
        {"values": [
            {"field": "vendor", "value": "Merit", "quote": "at Merit"},
            {"field": "attendees", "value": "Henderson", "quote": "lunch with Henderson"},
            {"field": "note", "value": "the steak was great", "quote": "the steak was great"},
            {"field": "purpose", "value": "client pitch", "quote": "for work"},
        ]}
    )  # fmt: skip
    await scenario.run_periodic("expenses.fill")
    erin = scenario.member("Erin")
    (entry,) = expenses(scenario).entries([expenses(scenario).business_sheet(erin).id])
    assert entry.get("vendor") == "Merit" and entry.get("attendees") == "Henderson"
    assert entry.values["vendor"].source_type == "chat_context"
    assert entry.values["vendor"].confidence == 0.7
    assert entry.values["vendor"].source_ref.startswith("message:")
    assert entry.get("note") is None  # never said: dropped
    assert entry.get("purpose") is None  # "client pitch" isn't in "for work"
    prompt = scenario.primary.requests[-1].prompt
    assert '<data source="the chat">' in prompt

    await scenario.run_periodic("expenses.fill")  # read once
    assert len([r for r in scenario.primary.requests if r.schema and "the chat" in r.prompt]) == 1
