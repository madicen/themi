"""F16c: Erin's ideas #59 and #60 (2026-10-28). "Set similar emails to medium urgency and
medium importance" got "always urgent?", then made-up explanations; and "urgent" read as
"drop everything" for mail that could wait a day or two."""

from __future__ import annotations

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, verdict
from themi.ai.types import ToolResult
from themi.core.email_audit import LEVELS_TEXT

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

STANFORD = {
    "sender": "Stanford Health Care <donotreply.myhealth@stanfordhealthcare.org>",
    "subject": "New message from your care team",
    "text": "You have a new message.",
}


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def sort(scenario: Scenario, inbox: FakeGmail, category: str, **extra: object) -> int:
    (email,) = await arrive(scenario, inbox, STANFORD)
    scenario.primary.queue_structured(
        {"results": [verdict(email, category, "A message from the care team", **extra)]}
    )
    await scenario.run_periodic("email.triage")
    return email


async def test_an_alert_that_can_wait_is_time_sensitive(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await sort(scenario, inbox, "urgent", urgent_kind="family")
    alert = next(t for t in scenario.inbox("Erin") if t.startswith("An email that looks"))
    assert alert.startswith("An email that looks time-sensitive (family)")


async def test_urgent_is_kept_for_drop_everything(scenario: Scenario, inbox: FakeGmail) -> None:
    await sort(scenario, inbox, "urgent", urgent_kind="family", severe=True)
    alert = next(t for t in scenario.inbox("Erin") if t.startswith("An email that looks"))
    assert alert.startswith("An email that looks urgent (family)")


async def test_medium_urgency_and_importance_in_her_words(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await sort(scenario, inbox, "urgent", urgent_kind="family")
    scenario.primary.queue_tool_call(
        "set_sender_levels",
        {"sender": "Stanford", "urgency": "time_sensitive", "importance": "somewhat"},
    )
    scenario.primary.queue_text("Done.")
    await scenario.say(
        "Erin", "For the future, set similar emails to medium urgency and medium importance"
    )
    result = tool_result(scenario)
    assert result.startswith(
        "Set: mail from Stanford Health Care (donotreply.myhealth@stanfordhealthcare.org) is "
        f"time-sensitive and somewhat important, in {ERIN}. "
    )
    assert result.endswith(LEVELS_TEXT)
    account = scenario.app.store.linked_account_by_address("gmail", ERIN)
    assert account is not None
    assert account.urgent_senders == ("donotreply.myhealth@stanfordhealthcare.org",)
    audit = scenario.app.services.email_audit
    assert audit is not None
    assert audit.sender_levels(account.id, "donotreply.myhealth@stanfordhealthcare.org") == (1, 1)

    await sort(scenario, inbox, "noise")  # somewhat important: never offered for archiving
    assert (
        scenario.app.db.scalar(
            "SELECT COUNT(*) FROM pending_actions WHERE category = 'email_archive_noise'"
        )
        == 0
    )

    scenario.primary.queue_tool_call(
        "set_sender_levels",
        {"sender": "Stanford", "urgency": "no_rush", "importance": "not"},
    )
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Actually Stanford emails can wait")
    account = scenario.app.store.linked_account_by_address("gmail", ERIN)
    assert account is not None and account.urgent_senders == ()


async def test_what_urgent_means_is_said_as_it_is(scenario: Scenario, inbox: FakeGmail) -> None:
    # "Urgent emails appear at the top of your inbox or in your daily digest": neither exists.
    assert "Nothing is moved, highlighted or reordered" in LEVELS_TEXT
    scenario.primary.queue_tool_call("inbox_setup", {})
    scenario.primary.queue_text("Here's what they mean.")
    await scenario.say("Erin", "What's the difference between urgent and normal emails?")
    assert tool_result(scenario).endswith(LEVELS_TEXT)
