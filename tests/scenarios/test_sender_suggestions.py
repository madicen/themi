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


async def test_likely_senders_are_offered_and_only_a_tap_adds_one(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await mail(scenario, inbox)
    await scenario.run_periodic("email.senders")
    await scenario.app.outbox.flush()
    (offer,) = [t for t in scenario.inbox("Erin") if t.startswith("A few senders")]
    assert offer == (
        f"A few senders in {ERIN} might always count as urgent: Schwab Alerts (money) and Bob "
        "Tenant (waiting on replies). Tap any that should; nothing changes otherwise."
    )
    account = scenario.app.store.linked_accounts(scenario.member("Erin").id)[0]
    assert account.urgent_senders == ()  # nothing until she taps

    replies = await scenario.tap("Erin", "Schwab Alerts")
    assert replies == [
        "Added: mail from Schwab Alerts (alerts@schwab.example) always counts as urgent now."
    ]
    account = scenario.app.store.get_linked_account(account.id)
    assert account.urgent_senders == ("alerts@schwab.example",)

    await scenario.run_periodic("email.senders")  # each is offered once
    await scenario.app.outbox.flush()
    assert len([t for t in scenario.inbox("Erin") if t.startswith("A few senders")]) == 1
