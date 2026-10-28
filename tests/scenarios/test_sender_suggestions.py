"""E1, Erin's idea #27: likely urgent senders are suggested, a button each; only a tap adds
one."""

from __future__ import annotations

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, verdict

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios


async def mail(scenario: Scenario, fake: FakeGmail) -> None:
    sent = [
        {
            "sender": "Schwab Alerts <alerts@schwab.example>",
            "subject": "Card declined",
            "text": "x",
        },
        {"sender": "Bob Tenant <bob@example.com>", "subject": "The sink", "text": "x"},
        {"sender": "Bob Tenant <bob@example.com>", "subject": "Still the sink", "text": "x"},
        {"sender": "Carol <carol@example.com>", "subject": "Lunch?", "text": "x"},
        {"sender": "Deals <promo@shop.example>", "subject": "50% off", "text": "x"},
    ]
    ids = await arrive(scenario, fake, *sent)
    scenario.primary.queue_structured(
        {
            "results": [
                verdict(ids[0], "urgent", "Card declined", urgent_kind="financial"),
                verdict(ids[1], "needs_reply", "Sink", reply_draft="We'll look."),
                verdict(ids[2], "needs_reply", "Sink again", reply_draft="On it."),
                verdict(ids[3], "needs_reply", "Lunch", reply_draft="Sure."),  # once: not yet
                verdict(ids[4], "noise", "A sale"),
            ]
        }
    )
    await scenario.run_periodic("email.triage")


async def test_likely_senders_wait_in_the_audit_and_only_an_answer_adds_one(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """E2 (idea #50): they wait in the email audit, not a message of their own."""
    await mail(scenario, inbox)
    await scenario.run_periodic("email.senders")
    await scenario.app.outbox.flush()
    assert not any(t.startswith("A few senders") for t in scenario.inbox("Erin"))
    account = scenario.app.store.linked_accounts(scenario.member("Erin").id)[0]
    assert account.urgent_senders == ()  # nothing until she answers

    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Same day")  # Schwab Alerts first: the likeliest
    await scenario.tap("Erin", "Not important")
    account = scenario.app.store.get_linked_account(account.id)
    assert account.urgent_senders == ("alerts@schwab.example",)

    await scenario.run_periodic("email.senders")  # each is offered once
    audit = scenario.app.services.email_audit
    assert audit is not None
    assert len(audit.waiting(scenario.member("Erin"))) == 1  # Bob Tenant, still


async def test_what_each_inbox_has_set_and_whats_waiting(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """Bug #45: "remind me which [senders] I needed to evaluate?" got "you haven't set up
    any watched inboxes": the model only had the expected-emails list to look in."""
    from themi.ai.types import ToolResult

    await mail(scenario, inbox)
    await scenario.run_periodic("email.senders")
    await scenario.app.outbox.flush()
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Same day")  # Schwab Alerts
    await scenario.tap("Erin", "Not important")
    scenario.primary.queue_tool_call("inbox_setup", {})
    scenario.primary.queue_text("Bob Tenant is the one left.")
    await scenario.say(
        "Erin", "Let's do some email configuration. Which ones did I need to look at?"
    )
    (result,) = [
        b.content
        for m in scenario.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ]
    assert result == (
        f"{ERIN}: watched. Urgent senders: alerts@schwab.example. Suggested, not answered "
        "yet: Bob Tenant (bob@example.com). Expected emails: none."
    )
