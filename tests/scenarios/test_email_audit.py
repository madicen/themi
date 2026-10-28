"""E2, Erin's idea #50: "Instead of individual emails, create an 'email audit' task... it goes
through one by one and the user can select 'urgent' 'important' 'both' or 'neither'. When all
emails have been categorized, Themi gives a brief confirmation and ends the email audit."""

from __future__ import annotations

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_sender_suggestions import mail
from tests.scenarios.test_triage import arrive, inbox, verdict
from themi.core.email_audit import EmailAudit
from themi.core.tasks import TaskBoard

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

ASK = "\nUrgent, important, both or neither?"
SCHWAB = "1 of 2. Mail from Schwab Alerts (alerts@schwab.example), money." + ASK
BOB = "2 of 2. Mail from Bob Tenant (bob@example.com), waiting on replies." + ASK


def audit(scenario: Scenario) -> EmailAudit:
    assert scenario.app.services.email_audit is not None
    return scenario.app.services.email_audit


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def audit_titles(scenario: Scenario) -> list[str]:
    return [
        t.title for t in board(scenario).open_for(scenario.member("Erin"))
        if t.title.startswith("Email audit")
    ]  # fmt: skip


async def suggested(scenario: Scenario, inbox: FakeGmail) -> None:
    await mail(scenario, inbox)
    await scenario.run_periodic("email.senders")
    await scenario.app.outbox.flush()


async def test_one_task_one_at_a_time_then_a_short_confirmation(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await suggested(scenario, inbox)
    assert audit_titles(scenario) == ["Email audit (2 to look at)"]
    assert "Email audit: 2 to look at, one at a time. Start now, or later?" in scenario.inbox(
        "Erin"
    )
    assert scenario.last_buttons("Erin") == ["Start", "Later"]

    assert await scenario.tap("Erin", "Start") == [SCHWAB]
    assert scenario.last_buttons("Erin") == [
        "Urgent",
        "Important",
        "Both",
        "Neither",
        "Stop for now",
    ]
    assert await scenario.tap("Erin", "Both") == [BOB]
    assert scenario.edits("Erin")[-1]["text"] == "Schwab Alerts: urgent and important."
    assert audit_titles(scenario) == ["Email audit (1 to look at)"]
    replies = await scenario.tap("Erin", "Neither")
    assert replies == [
        "All 2 sorted: 1 urgent and important, 1 neither. That's the email audit done."
    ]
    assert audit_titles(scenario) == []

    account = scenario.app.store.linked_accounts(scenario.member("Erin").id)[0]
    assert account.urgent_senders == ("alerts@schwab.example",)  # both: urgent too


async def test_an_important_sender_isnt_offered_for_archiving(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await suggested(scenario, inbox)
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Important")
    (email,) = await arrive(
        scenario,
        inbox,
        {"sender": "Schwab Alerts <alerts@schwab.example>", "subject": "News", "text": "x"},
    )
    scenario.primary.queue_structured({"results": [verdict(email, "noise", "Schwab newsletter")]})
    await scenario.run_periodic("email.triage")
    staged = scenario.app.db.query(
        "SELECT 1 FROM pending_actions WHERE category = 'email_archive_noise' "
        "AND summary LIKE '%News%'"
    )
    assert staged == []


async def test_an_email_triage_isnt_sure_about_waits_in_the_audit(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    (email,) = await arrive(
        scenario, inbox,
        {"sender": "Joyous Care <billing@joyous.example>", "subject": "Your invoice", "text": "x"},
    )  # fmt: skip
    scenario.primary.queue_structured(
        {
            "results": [
                verdict(
                    email, "urgent", "An invoice for $120", urgent_kind="financial", unsure=True
                )
            ]
        }
    )
    await scenario.run_periodic("email.triage")
    await scenario.app.outbox.flush()
    assert not any(t.startswith("An email that looks urgent") for t in scenario.inbox("Erin"))
    assert audit_titles(scenario) == ["Email audit (1 to look at)"]
    assert await scenario.tap("Erin", "Start") == [
        "1 of 1. An email from Joyous Care: Your invoice\nAn invoice for $120\n"
        "Urgent, important, both or neither?"
    ]
    await scenario.tap("Erin", "Urgent")
    assert scenario.app.db.scalar("SELECT category FROM emails WHERE id = ?", (email,)) == "urgent"


async def test_stopping_partway_brings_it_back_later(scenario: Scenario, inbox: FakeGmail) -> None:
    await suggested(scenario, inbox)
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Urgent")
    await scenario.tap("Erin", "Stop for now")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Stopped for now; 1 still to look at. The audit comes back later."
    )
    (task,) = [
        t for t in board(scenario).open_for(scenario.member("Erin")) if t.title.startswith("Email")
    ]
    assert task.status == "snoozed"
    await scenario.advance(hours=4, minutes=1)
    await scenario.run_periodic("tasks.resurface")
    texts = [r["text"] for r in scenario.app.db.query("SELECT text FROM outbox ORDER BY id")]
    assert texts[-1] == "Email audit: 1 to look at, one at a time. Start now, or later?"


async def test_asked_for_in_chat(scenario: Scenario, inbox: FakeGmail) -> None:
    await suggested(scenario, inbox)
    scenario.primary.queue_tool_call("start_email_audit", {})
    scenario.primary.queue_text("Here's the first.")
    replies = await scenario.say("Erin", "Let's do the email audit")
    assert replies[0] == SCHWAB
