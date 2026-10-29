"""Expected emails and anomalies end to end: the Tier 3 override for email."""

from __future__ import annotations

from html import unescape
from typing import Any

import httpx
import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, link, verdict
from themi.accounts import PermissionDenied
from themi.autonomy import Tier
from themi.core.expected import ExpectedEmail, ExpectedEmails

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

CATEGORY = "email_mark_read"


def pge_mail(amount: str = "$112.40", sender: str = "billing@pge.com", **extra: Any) -> dict:
    return {
        "sender": f"PG&E <{sender}>",
        "subject": "Payment confirmation",
        "text": f"We received your payment of {amount}. Thank you.",
        **extra,
    }


HOTEL = {"sender": "Hotel <stay@hotel.example>", "subject": "Booking confirmed", "text": "Fri"}


def expected_emails(scenario: Scenario) -> ExpectedEmails:
    assert scenario.app.services.expected is not None
    return scenario.app.services.expected


def expect_pge(scenario: Scenario, address: str = ERIN, name: str = "Erin") -> ExpectedEmail:
    account = scenario.app.store.linked_account_by_address("gmail", address)
    assert account is not None
    return expected_emails(scenario).add(
        scenario.member(name),
        account.id,
        name="the PG&E confirmation",
        sender="pge.com",
        subject="payment confirmation",
        cadence_days=30,
        grace_days=3,
    )


def automatic(scenario: Scenario, name: str = "Erin") -> None:
    """Marking their confirmations read is automatic, as their locked rule would make it."""
    scenario.app.services.autonomy.grant_tier2(CATEGORY, via_rule_id=1, by=scenario.member(name))


async def sort(scenario: Scenario, ids: list[int], category: str = "confirmation") -> None:
    scenario.primary.queue_structured({"results": [verdict(i, category) for i in ids]})
    await scenario.run_periodic("email.triage")


def last_action(scenario: Scenario) -> dict[str, Any]:
    row = scenario.app.db.one("SELECT * FROM pending_actions ORDER BY id DESC LIMIT 1")
    assert row is not None
    return row


def queued_since(scenario: Scenario, outbox_id: int, name: str = "Erin") -> list[str]:
    """What Themi wrote to `name` after outbox row `outbox_id` (sent now or waiting a window)."""
    rows = scenario.app.db.query(
        "SELECT text FROM outbox WHERE id > ? AND member_id = ? ORDER BY id",
        (outbox_id, scenario.member(name).id),
    )
    return [r["text"] for r in rows]


def outbox_mark(scenario: Scenario) -> int:
    return scenario.app.db.scalar("SELECT COALESCE(MAX(id), 0) FROM outbox")


async def overdue(scenario: Scenario, days: float = 34, name: str = "Erin") -> list[str]:
    """Let `days` pass, run the check, and return what it wrote to `name`."""
    await scenario.advance(hours=days * 24)
    mark = outbox_mark(scenario)
    await scenario.run_periodic("email.expected")
    return queued_since(scenario, mark, name)


# ----- the plan's scenario 4 -------------------------------------------------------


async def test_a_missing_bill_confirmation_alerts_and_drops_to_tier_1(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    automatic(scenario)
    expect_pge(scenario)
    await sort(scenario, await arrive(scenario, inbox, pge_mail()))
    assert inbox.calls_to("modify") == 1  # automatic: marked read with nobody asked
    assert expected_emails(scenario).for_member(scenario.member("Erin"))[0].last_seen_at

    assert await overdue(scenario, days=32) == []  # due, but inside its grace period
    sent = await overdue(scenario, days=2)
    (alert,) = [t for t in sent if "hasn't shown up" in t]
    assert alert.startswith(
        f"The PG&E confirmation hasn't shown up in {ERIN} yet. It usually comes every month; "
        "the last one arrived on "
    )
    assert alert.endswith(
        '"Mark confirmation emails as read" is back to asking first until it\'s resumed.'
    )
    assert scenario.last_buttons("Erin") == ["Resume automatic"]
    category = scenario.app.services.autonomy.category(CATEGORY)
    assert category.escalated and category.effective_tier is Tier.SUPERVISED
    assert category.escalation_reason == "the PG&E confirmation is overdue"

    await sort(scenario, await arrive(scenario, inbox, HOTEL))
    assert last_action(scenario)["status"] == "pending"  # asks first now
    assert inbox.calls_to("modify") == 1


async def test_one_alert_per_missed_period(scenario: Scenario, inbox: FakeGmail) -> None:
    expect_pge(scenario)
    alerts = [t for t in await overdue(scenario) if "hasn't shown up" in t]
    assert len(alerts) == 1
    assert "before Themi started watching" in alerts[0]
    # A supervised category has nothing to pause: just the alert.
    assert "back to asking first" not in alerts[0]
    assert not scenario.app.services.autonomy.category(CATEGORY).escalated

    assert await scenario.run_periodic("email.expected") == 0
    assert await scenario.run_periodic("email.expected") == 0
    assert [t for t in await overdue(scenario, days=10) if "hasn't shown up" in t] == []
    assert len([t for t in await overdue(scenario, days=21) if "hasn't shown up" in t]) == 1

    await arrive(scenario, inbox, pge_mail())  # it turns up at last: the clock restarts
    assert [t for t in await overdue(scenario, days=20) if "hasn't shown up" in t] == []


# ----- other anomalies -------------------------------------------------------------


async def test_an_unknown_sender_inside_a_trusted_pattern(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    automatic(scenario)
    expect_pge(scenario)
    await sort(scenario, await arrive(scenario, inbox, pge_mail()))
    outage = {"sender": "PG&E <news@pge.com>", "subject": "Outage update", "text": "Fixed"}
    await sort(scenario, await arrive(scenario, inbox, outage), "routine")
    assert not scenario.app.services.autonomy.category(CATEGORY).escalated  # not the pattern

    mark = outbox_mark(scenario)
    ids = await arrive(scenario, inbox, pge_mail(sender="security-update@pge.com"))
    category = scenario.app.services.autonomy.category(CATEGORY)
    assert category.escalated
    assert category.escalation_reason == (
        "the PG&E confirmation came from a new address (security-update@pge.com)"
    )
    await sort(scenario, ids)
    assert last_action(scenario)["status"] == "pending"  # this one waits for a yes
    sent = queued_since(scenario, mark)
    assert any(
        t.startswith(
            "An email that looks like the PG&E confirmation came from an address not "
            "seen for it before: PG&E <security-update@pge.com>"
        )
        for t in sent
    )


async def test_an_unusually_large_amount_in_a_confirmation(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    automatic(scenario)
    for amount in ("$100.00", "$104.10", "$98.00", "$106.00"):  # the usual, and one a bit higher
        await sort(scenario, await arrive(scenario, inbox, pge_mail(amount)))
    assert not scenario.app.services.autonomy.category(CATEGORY).escalated
    assert inbox.calls_to("modify") == 4

    mark = outbox_mark(scenario)
    await sort(scenario, await arrive(scenario, inbox, pge_mail("$460.00")))
    category = scenario.app.services.autonomy.category(CATEGORY)
    assert category.escalated
    assert category.escalation_reason == "an unusually large amount ($460.00) from billing@pge.com"
    assert last_action(scenario)["status"] == "pending"
    assert inbox.calls_to("modify") == 4
    sent = queued_since(scenario, mark)
    assert any(
        t.startswith("A confirmation from PG&E shows $460.00, well above the usual $102.05: ")
        for t in sent
    )
    amounts = scenario.app.db.query("SELECT amount_cents FROM emails ORDER BY id")
    assert [r["amount_cents"] for r in amounts] == [10000, 10410, 9800, 10600, 46000]


# ----- resuming --------------------------------------------------------------------


async def test_resume_restores_tier_2(scenario: Scenario, inbox: FakeGmail) -> None:
    automatic(scenario)
    expect_pge(scenario)
    await overdue(scenario)
    assert scenario.app.services.autonomy.category(CATEGORY).escalated

    await scenario.tap("Erin", "Resume automatic")
    assert (
        scenario.edits("Erin")[-1]["text"]
        == '"Mark confirmation emails as read" is automatic again.'
    )
    autonomy = scenario.app.services.autonomy
    assert autonomy.is_automatic(CATEGORY, scenario.member("Erin"))

    await sort(scenario, await arrive(scenario, inbox, HOTEL))
    assert last_action(scenario)["status"] == "done"
    assert inbox.calls_to("modify") == 1


async def test_only_admins_get_the_resume_button(
    scenario: Scenario, fake_google: FakeGoogle, fake_gmail: FakeGmail, site: httpx.AsyncClient
) -> None:
    await link(scenario, site, fake_google, "Husband", "dan@gmail.com")
    await scenario.tap("Husband", "Watch it")
    automatic(scenario, "Husband")
    expect_pge(scenario, "dan@gmail.com", "Husband")
    (alert,) = [t for t in await overdue(scenario, name="Husband") if "hasn't shown up" in t]
    assert "an admin can resume it from the website's Trust page" in alert
    buttons = scenario.app.db.scalar(
        "SELECT buttons FROM outbox WHERE member_id = ? ORDER BY id DESC LIMIT 1",
        (scenario.member("Husband").id,),
    )
    assert buttons == "[]"
    with pytest.raises(PermissionDenied):
        expect_pge(scenario, "dan@gmail.com", "Erin")  # nobody sets these on someone else's inbox


# ----- managing them ---------------------------------------------------------------


async def test_expected_emails_in_chat(scenario: Scenario, inbox: FakeGmail) -> None:
    await arrive(scenario, inbox, pge_mail())
    scenario.primary.queue_tool_call(
        "expect_email",
        {
            "name": "the PG&E confirmation",
            "sender": "PG&E",  # looked up from earlier mail
            "subject": "Payment confirmation",
            "cadence_days": 30,
            "grace_days": 3,
            "inbox": "",
        },
    )
    scenario.primary.queue_text("Okay, I'll say so if it's late.")
    await scenario.say("Erin", "tell me if the PG&E confirmation doesn't show up")
    (item,) = expected_emails(scenario).for_member(scenario.member("Erin"))
    assert (item.sender_pattern, item.subject_pattern) == ("@pge.com", "Payment confirmation")
    assert item.last_seen_at is not None and item.known_senders == ("billing@pge.com",)
    tool_result = str(scenario.primary.requests[-1].messages[-1])
    assert "Watching for the PG&E confirmation in erin@gmail.com: from @pge.com" in tool_result

    scenario.primary.queue_tool_call("forget_expected_email", {"name": "The PG&E confirmation"})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "never mind the PG&E one")
    assert expected_emails(scenario).for_member(scenario.member("Erin")) == []


async def test_expected_emails_on_the_website(
    scenario: Scenario, inbox: FakeGmail, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    account = scenario.app.store.linked_account_by_address("gmail", ERIN)
    assert account is not None
    assert "Expected emails" in (await site.get("/accounts")).text
    form = {
        "csrf": csrf,
        "name": "the PG&E confirmation",
        "sender": "@pge.com",
        "subject": "Payment confirmation",
        "cadence_days": "30",
        "grace_days": "3",
        "category": CATEGORY,
    }
    await site.post(f"/accounts/{account.id}/expected", data=form)
    assert "Watching for the PG&amp;E confirmation." in await flash(site, "/accounts")
    page = unescape((await site.get("/accounts")).text)
    assert "the PG&E confirmation</strong>: from @pge.com" in page

    await site.post(f"/accounts/{account.id}/expected", data={**form, "cadence_days": "0"})
    assert "How often it comes should be between 1 and 400 days." in await flash(site, "/accounts")
    await site.post(f"/accounts/{account.id}/expected", data={**form, "category": "email_reply"})
    assert "always asks first" in await flash(site, "/accounts")

    (item,) = expected_emails(scenario).for_account(account.id)
    await site.post(f"/accounts/{account.id}/expected/{item.id}/remove", data={"csrf": csrf})
    assert "No longer watching for the PG&amp;E confirmation." in await flash(site, "/accounts")
    assert expected_emails(scenario).for_account(account.id) == []
