"""F15c, bug #53: "The Charles Schwab email is urgent and shouldn't be archived" became a
proposed rule ("probably shouldn't need a rule for this")."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, verdict
from themi.ai.types import ToolResult

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

SCHWAB = {
    "sender": '"Charles Schwab & Co., Inc." <donotreply@email.schwab.com>',
    "subject": "URGENT: Schwab account requires updated address",
    "text": "Update your mailing address by December 18.",
}


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def sorted_as(scenario: Scenario, inbox: FakeGmail, category: str) -> int:
    (email,) = await arrive(scenario, inbox, SCHWAB)
    scenario.primary.queue_structured({"results": [verdict(email, category, "Schwab notice")]})
    await scenario.run_periodic("email.triage")
    return email


async def keep(
    scenario: Scenario, said: str = "The Schwab email is urgent, don't archive it"
) -> Any:
    scenario.primary.queue_tool_call("keep_email", {"email": "Schwab"})
    scenario.primary.queue_text("Kept.")
    return await scenario.say("Erin", said)


def labels(inbox: FakeGmail, scenario: Scenario, email: int) -> list[str]:
    gmail_id = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (email,))
    return inbox.mailbox(ERIN).messages[gmail_id].labels


async def test_an_email_archived_as_noise_comes_back(scenario: Scenario, inbox: FakeGmail) -> None:
    email = await sorted_as(scenario, inbox, "noise")
    await scenario.say("Erin", "/pending")  # F16b: noise has no card of its own
    await scenario.tap("Erin", "Go ahead")  # archived, as Themi offered
    assert "INBOX" not in labels(inbox, scenario, email)

    replies = await keep(scenario)
    assert "INBOX" in labels(inbox, scenario, email)
    assert "Back in the inbox" in tool_result(scenario)
    assert scenario.app.db.scalar("SELECT category FROM emails WHERE id = ?", (email,)) == "urgent"
    assert "Should mail from Charles Schwab & Co., Inc. always count as urgent?" in replies
    await scenario.tap("Erin", "Always urgent: Charles Schwab & Co., Inc."[:40])
    account = scenario.app.store.linked_account_by_address("gmail", ERIN)
    assert account is not None and account.urgent_senders == ("donotreply@email.schwab.com",)


async def test_an_offer_to_archive_it_is_taken_back(scenario: Scenario, inbox: FakeGmail) -> None:
    await sorted_as(scenario, inbox, "noise")
    await keep(scenario)
    assert "taken back" in tool_result(scenario)
    statuses = scenario.app.db.query(
        "SELECT status FROM pending_actions WHERE category = 'email_archive_noise'"
    )
    assert [r["status"] for r in statuses] == ["declined"]
    assert inbox.calls_to("modify") == 0


@pytest.mark.parametrize(
    "said",
    [
        "The Charles Schwab email is urgent and shouldn't be archived",
        "Charles Schwab emails are urgent",
        "mail from the school is always urgent",
    ],
)
async def test_one_email_or_an_urgent_sender_isnt_a_rule(scenario: Scenario, said: str) -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Schwab emails are urgent", "text": "Schwab emails are urgent.",
            "kind": "policy", "category": "", "rule_id": 0, "applies_to": "personal",
        },
    )  # fmt: skip
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", said)
    assert scenario.app.db.query("SELECT 1 FROM rules") == []
    assert "not a rule" in tool_result(scenario) or "isn't a rule" in tool_result(scenario)


async def test_a_rule_about_urgent_mail_in_general_still_works(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Never archive urgent emails", "text": "Never archive urgent emails.",
            "kind": "policy", "category": "", "rule_id": 0, "applies_to": "household",
        },
    )  # fmt: skip
    scenario.primary.queue_text("Drafted.")
    await scenario.say("Husband", "Never archive urgent emails")
    assert len(scenario.app.db.query("SELECT 1 FROM rules")) == 1


async def test_a_security_alert_isnt_called_money(scenario: Scenario, inbox: FakeGmail) -> None:
    """Google's "Claude for Google Drive was granted access" was urgent "(money)"."""
    google = {"sender": "Google <no-reply@accounts.google.com>", "subject": "Alert", "text": "x"}
    (email,) = await arrive(scenario, inbox, google)
    scenario.primary.queue_structured(
        {"results": [verdict(email, "urgent", "New access to the account", urgent_kind="security")]}
    )
    await scenario.run_periodic("email.triage")
    assert any(
        t.startswith("An email that looks urgent (account security)")
        for t in scenario.inbox("Erin")
    )


async def test_keeping_a_second_email_from_a_sender_asked_about_before(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    # #59's conversation, 28 Oct 14:53: keep_email failed with a UNIQUE constraint, because
    # the sender had been offered as always urgent a few minutes earlier.
    await sorted_as(scenario, inbox, "noise")
    await keep(scenario)
    await sorted_as(scenario, inbox, "noise")
    await keep(scenario, "keep this type of email too")
    assert "asked, with a button" in tool_result(scenario)
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM sender_suggestions") == 1
