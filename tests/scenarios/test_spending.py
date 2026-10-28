"""X1 (bug #36, idea #37): money spent, from chat and from takeout receipts. The family's
takeout budget is $200 a month; the clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

import httpx

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import arrive, inbox, verdict
from themi.ai.types import ToolResult
from themi.core.spending import Spending

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

DOORDASH = {
    "sender": "DoorDash <no-reply@doordash.com>",
    "subject": "Your order from Thai Place",
    "text": "Pad thai $18.00\nFees and tip $7.50\nTotal $25.50",
}


def spending(scenario: Scenario) -> Spending:
    assert scenario.app.services.spending is not None
    return scenario.app.services.spending


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def say(scenario: Scenario, name: str, said: str, tool: str, args: dict[str, Any]) -> None:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Okay.")
    await scenario.say(name, said)


def spend(amount: str, place: str, kind: str = "takeout", business: bool = False) -> dict:
    return {"amount": amount, "place": place, "kind": kind, "business": business, "date": ""}


async def receipt(scenario: Scenario, fake: FakeGmail, total: int = 2550) -> int:
    (email,) = await arrive(scenario, fake, DOORDASH)
    scenario.primary.queue_structured({"results": [verdict(email, "receipt", "DoorDash")]})
    scenario.primary.queue_structured(
        {
            "kind": "takeout",
            "vendor": "DoorDash",
            "total_cents": total,
            "items": [{"name": "pad thai", "quantity": "1", "price_cents": 1800}],
        }
    )
    await scenario.run_periodic("email.triage")
    return email


async def test_a_spend_said_in_chat_is_kept_with_the_months_takeout(scenario: Scenario) -> None:
    """Bug #36: "just spent $51.97 on door dash" went to Things to Buy."""
    await say(
        scenario, "Husband", "Just spent $51.97 on door dash", "log_spending",
        spend("51.97", "DoorDash"),
    )  # fmt: skip
    assert tool_result(scenario) == (
        "Logged (spend 1): Wed 21 Oct · $51.97 · DoorDash · takeout · Husband. "
        "Takeout this month: $51.97 of the $200.00 budget ($148.03 left)."
    )
    await say(
        scenario, "Erin", "We spent $160 on takeout for the party", "log_spending",
        spend("160", "Pizza Place"),
    )  # fmt: skip
    assert "$211.97 of the $200.00 budget ($11.97 over)" in tool_result(scenario)


async def test_a_takeout_receipt_counts_once(scenario: Scenario, inbox: FakeGmail) -> None:
    await say(
        scenario,
        "Erin",
        "Just spent $25.50 on DoorDash",
        "log_spending",
        spend("25.50", "DoorDash"),
    )
    email = await receipt(scenario, inbox)
    (only,) = spending(scenario).month(spending(scenario).today().replace(day=1))
    assert (only.amount_cents, only.email_id, only.source) == (2550, email, "chat")

    await receipt(scenario, inbox, total=3100)  # another order, from email only
    await say(
        scenario, "Erin", "Spent $31 on DoorDash yesterday", "log_spending", spend("31", "DoorDash")
    )
    assert tool_result(scenario).startswith("Already logged from the receipt email")
    assert len(spending(scenario).month(spending(scenario).today().replace(day=1))) == 2


async def test_business_expenses_are_your_own_and_export(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """Idea #37: track business expenses."""
    await say(
        scenario, "Husband", "$42.10 business lunch at Merit", "log_spending",
        spend("42.10", "Merit", "eating_out", business=True),
    )  # fmt: skip
    assert "Marked as a business expense." in tool_result(scenario)
    await say(
        scenario, "Husband", "Dinner out was $60", "log_spending", spend("60", "Nopa", "eating_out")
    )
    await say(
        scenario, "Husband", "Actually dinner was for work too", "mark_business_expense",
        {"spend": 2, "business": True},
    )  # fmt: skip
    await say(
        scenario, "Erin", "What are my business expenses this month?", "spending_summary",
        {"month": "", "which": "business"},
    )  # fmt: skip
    assert tool_result(scenario) == "October 2026: nothing logged for business."
    await say(scenario, "Erin", "Take off Michael's lunch", "remove_spending", {"spend": 1})
    assert "someone else's" in tool_result(scenario)

    await sign_in(scenario, site, "Husband")
    page = await site.get("/spending")
    assert "Your business expenses this month: $102.10." in page.text
    exported = await site.get("/spending/business.csv?month=2026-10")
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.text.splitlines() == [
        "date,place,amount,kind,note,receipt",
        "2026-10-21,Merit,42.10,eating out,,",
        "2026-10-21,Nopa,60.00,eating out,,",
    ]
