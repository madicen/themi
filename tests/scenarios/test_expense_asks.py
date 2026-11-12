"""EX2b: when Themi asks about expense sheets, row by row of the spec's table. The clock starts
Wednesday 21 October 2026, 9 am; Erin's quiet hours are 21:30 to 08:00."""

from __future__ import annotations

import httpx

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_expense_fill import MERIT, receipt
from tests.scenarios.test_expense_sheets import add, expenses, value
from tests.scenarios.test_spending import inbox
from themi.core import keys

__all__ = ["inbox"]

DINNER = [value("vendor", "Merit"), value("category", "eating_out")]


def asks(scenario: Scenario) -> list[tuple[str, str]]:
    return [
        (r["kind"], r["status"])
        for r in scenario.app.db.query("SELECT * FROM expense_asks ORDER BY id")
    ]


async def ask_round(scenario: Scenario, hours: float = 0) -> list[str]:
    """Let time pass, run the asking job, and deliver what's due."""
    before = len(scenario.inbox("Erin"))
    await scenario.advance(hours=hours)
    await scenario.run_periodic("expenses.ask")
    await scenario.advance(minutes=1)
    return scenario.inbox("Erin")[before:]


async def test_a_dinner_is_asked_about_the_next_day(scenario: Scenario) -> None:
    await add(scenario, "Erin", "Dinner at Merit tonight, I'll check the cost", "takeout", DINNER)
    assert await ask_round(scenario, hours=23) == []  # receipts often come hours later
    sent = await ask_round(scenario, hours=2)
    assert sent == ["What did eating out at Merit on Wed 21 Oct come to?"]
    assert scenario.last_buttons("Erin") == ["Skip"]

    replies = await scenario.say("Erin", "$84.20")
    assert replies == ["Got it: $84.20 · Wed 21 Oct · Merit · eating_out."]
    amount = expenses(scenario).entry(1).values["amount"]
    assert (amount.value, amount.status, amount.source_type) == (
        8420,
        "verified",
        "direct_user_input",
    )
    assert await ask_round(scenario, hours=24) == []  # once


async def test_skip_leaves_it_empty_for_good(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await add(scenario, "Erin", "Dinner at Merit", "takeout", DINNER)
    await ask_round(scenario, hours=25)
    await scenario.tap("Erin", "Skip")
    assert scenario.edits("Erin")[-1]["text"] == "Left empty, and I won't ask about that one again."
    assert expenses(scenario).entry(1).get("amount") is None
    assert await ask_round(scenario, hours=48) == []
    await sign_in(scenario, site, "Erin")
    assert "Needs filling in" not in (await site.get("/spending")).text


async def test_a_field_that_isnt_key_is_never_asked_about(scenario: Scenario) -> None:
    await add(scenario, "Erin", "$30 takeout", "takeout", [value("amount", "30")])  # no vendor
    assert await ask_round(scenario, hours=48) == []


async def test_a_sheet_that_doesnt_ask_never_asks(scenario: Scenario) -> None:
    sheet = expenses(scenario).takeout_sheet()
    expenses(scenario).set_sheet_options(sheet.id, prompt_on_missing_critical=False)
    await add(scenario, "Erin", "Dinner at Merit", "takeout", DINNER)
    assert await ask_round(scenario, hours=48) == []


async def test_a_receipt_landing_in_time_means_nothing_is_asked(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await add(scenario, "Erin", "Dinner at Merit", "takeout", DINNER)
    await scenario.advance(hours=3)
    await receipt(scenario, inbox, MERIT, 8420)
    assert expenses(scenario).entry(1).get("amount") == 8420
    assert await ask_round(scenario, hours=24) == []
    assert asks(scenario) == []


async def test_a_receipt_takes_back_a_question_still_waiting(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await scenario.advance(hours=12)  # 9 pm
    await add(scenario, "Erin", "Dinner at Merit", "takeout", DINNER)
    sent = await ask_round(scenario, hours=25)  # 10 pm the next day: quiet hours, it waits
    assert sent == [] and asks(scenario) == [("ask", "queued")]
    await receipt(scenario, inbox, MERIT, 8420)  # the receipt comes first
    assert asks(scenario) == [("ask", "cancelled")]
    assert all("come to" not in t for t in await scenario.advance(hours=12))


async def test_a_business_weeks_review(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await add(
        scenario, "Erin", "Lunch with Acme at Merit, for work", "business",
        [value("vendor", "Merit"), value("business purpose", "Acme pitch")],
    )  # fmt: skip
    await add(scenario, "Erin", "$12 parking for work", "business", [value("amount", "12")])
    assert await ask_round(scenario, hours=30) == []  # business waits for the review

    await sign_in(scenario, site, "Erin")
    page = (await site.get("/spending")).text
    assert "Needs filling in" in page and "no amount yet" in page

    erin = scenario.member("Erin")
    breaks = scenario.app.services.get(keys.breaks)
    await scenario.advance(hours=20)  # Friday 11 am
    await breaks.start(erin, 5 * 60)  # resting until 4 pm
    sent = await ask_round(scenario, hours=4)  # Friday 3 pm: the review's time, but a break
    assert all("Business expenses" not in t for t in sent)
    assert asks(scenario) == [("review", "queued")]
    sent = await scenario.advance(hours=1, minutes=15)  # after the break
    review = next(t for t in sent if t.startswith("Business expenses"))
    assert review.splitlines() == [
        "Business expenses with something still empty, whenever suits:",
        "- Merit on Wed 21 Oct (Business): no amount yet",
        "- the $12.00 one on Business on Wed 21 Oct (Business): no vendor, business purpose yet",
    ]
    assert scenario.last_buttons("Erin")[-1] == "Later"

    await scenario.tap("Erin", "Merit on Wed 21 Oct")
    assert scenario.inbox("Erin")[-1] == "What did Merit on Wed 21 Oct come to?"
    left = scenario.edits("Erin")[-1]  # the review, with the one still to look at
    labels = [b["text"] for row in left["reply_markup"]["inline_keyboard"] for b in row]
    assert labels == ["the $12.00 one on Business on Wed 21 Oct", "Later"]
    await scenario.say("Erin", "it was 84 with the tip")
    assert expenses(scenario).entry(1).get("amount") == 8400

    await scenario.tap("Erin", "Later")
    assert scenario.edits("Erin")[-1]["text"] == "Okay, they'll keep until next week's review."
    assert await ask_round(scenario, hours=24) == []  # one review a week
