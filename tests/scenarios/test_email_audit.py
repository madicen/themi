"""E2, Erin's idea #50: "Instead of individual emails, create an 'email audit' task... it goes
through one by one and the user can select 'urgent' 'important' 'both' or 'neither'. When all
emails have been categorized, Themi gives a brief confirmation and ends the email audit."""
# E2b: with sliding scales (idea #44), how urgent and then how important; off the wall.

from __future__ import annotations

import re

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_sender_suggestions import mail
from tests.scenarios.test_triage import arrive, inbox, verdict
from themi.core.email_audit import EmailAudit
from themi.core.tasks import TaskBoard

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

HOW_URGENT = "\nHow soon does it need you?"
HOW_IMPORTANT = "\nHow important is it?"
LINK = "https://mail.google.com/mail/u/erin@gmail.com/#all/ID"
# Idea #69: the exact subject (a sender's latest email) and a link to it in Gmail.
SCHWAB = (
    "1 of 2. Mail from Schwab Alerts (alerts@schwab.example), money.\n"
    f'Latest: "Card declined"\n{LINK}'
)
BOB = (
    "2 of 2. Mail from Bob Tenant (bob@example.com), waiting on replies.\n"
    f'Latest: "Still the sink"\n{LINK}'
)
URGENCY = ["No rush", "Time-sensitive", "Urgent", "Stop for now"]
IMPORTANCE = ["Not important", "Somewhat", "Very", "Stop for now"]


def masked(texts: list[str]) -> list[str]:
    """Gmail's ids in the links, which the fake numbers across tests, as ID."""
    return [re.sub(r"#all/\w+", "#all/ID", t) for t in texts]


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

    assert masked(await scenario.tap("Erin", "Start")) == [SCHWAB + HOW_URGENT]
    assert scenario.last_buttons("Erin") == URGENCY
    assert await scenario.tap("Erin", "Time-sensitive") == []
    edit = scenario.edits("Erin")[-1]
    assert masked([edit["text"]]) == [SCHWAB + HOW_IMPORTANT]
    assert [b["text"] for b in edit["reply_markup"]["inline_keyboard"][0]] == IMPORTANCE
    assert masked(await scenario.tap("Erin", "Somewhat")) == [BOB + HOW_URGENT]
    assert scenario.edits("Erin")[-1]["text"] == (
        "Schwab Alerts: time-sensitive, somewhat important."
    )
    assert audit_titles(scenario) == ["Email audit (1 to look at)"]
    await scenario.tap("Erin", "No rush")
    replies = await scenario.tap("Erin", "Not important")
    assert replies == [
        "All 2 sorted: 1 time-sensitive and important, 1 neither. That's the email audit done."
    ]
    assert audit_titles(scenario) == []

    account = scenario.app.store.linked_accounts(scenario.member("Erin").id)[0]
    assert account.urgent_senders == ("alerts@schwab.example",)  # both: urgent too


async def test_an_important_sender_isnt_offered_for_archiving(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await suggested(scenario, inbox)
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "No rush")
    await scenario.tap("Erin", "Somewhat")
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
    assert not any(
        t.startswith("An email that looks time-sensitive") for t in scenario.inbox("Erin")
    )
    assert audit_titles(scenario) == ["Email audit (1 to look at)"]
    assert masked(await scenario.tap("Erin", "Start")) == [
        f"1 of 1. An email from Joyous Care: Your invoice\nAn invoice for $120\n{LINK}" + HOW_URGENT
    ]
    await scenario.tap("Erin", "Time-sensitive")
    await scenario.tap("Erin", "Not important")
    assert scenario.app.db.scalar("SELECT category FROM emails WHERE id = ?", (email,)) == "urgent"


async def test_stopping_partway_brings_it_back_later(scenario: Scenario, inbox: FakeGmail) -> None:
    await suggested(scenario, inbox)
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Time-sensitive")
    await scenario.tap("Erin", "Not important")
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
    assert masked(replies[:1]) == [SCHWAB + HOW_URGENT]


async def test_stopping_between_the_two_questions_picks_up_at_the_second(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await suggested(scenario, inbox)
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Urgent")
    await scenario.tap("Erin", "Stop for now")
    assert len(audit(scenario).waiting(scenario.member("Erin"))) == 2
    scenario.primary.queue_tool_call("start_email_audit", {})
    scenario.primary.queue_text("Here's the first.")
    replies = await scenario.say("Erin", "Let's finish the email audit")
    assert masked(replies[:1]) == [SCHWAB + HOW_IMPORTANT]


async def test_right_away_alerts_at_once_and_very_important_isnt_marked_read(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await suggested(scenario, inbox)
    await scenario.tap("Erin", "Start")
    await scenario.tap("Erin", "Urgent")
    await scenario.tap("Erin", "Very")
    news, receipt = await arrive(
        scenario,
        inbox,
        {"sender": "Schwab Alerts <alerts@schwab.example>", "subject": "Login", "text": "x"},
        {"sender": "Schwab Alerts <alerts@schwab.example>", "subject": "Trade done", "text": "x"},
    )
    scenario.primary.queue_structured(
        {
            "results": [
                verdict(news, "urgent", "A new sign-in", urgent_kind="security"),
                verdict(receipt, "confirmation", "Your trade went through"),
            ]
        }
    )
    await scenario.run_periodic("email.triage")
    priorities = scenario.app.db.query(
        "SELECT priority FROM outbox WHERE dedupe_key = ?", (f"email-urgent:{news}",)
    )
    assert [r["priority"] for r in priorities] == ["urgent"]  # not severe, but right away
    staged = scenario.app.db.query(
        "SELECT 1 FROM pending_actions WHERE category = 'email_mark_read'"
    )
    assert staged == []


async def test_the_audit_never_goes_on_the_wall(
    scenario: Scenario, inbox: FakeGmail, fake_cozyla: FakeCozyla
) -> None:
    """Ticking it off on the wall would close it without the audit."""
    erin = scenario.member("Erin")
    await suggested(scenario, inbox)
    await board(scenario).create(erin, "Call the vet", "call", 2, assignee=erin)
    await scenario.run_periodic("cozyla.sync")
    assert [t["todoTitle"] for t in fake_cozyla.in_list(scenario.cozyla_list)] == ["Call the vet"]


async def test_one_already_on_the_wall_comes_off(
    scenario: Scenario, inbox: FakeGmail, fake_cozyla: FakeCozyla
) -> None:
    """As migration 0066 does for an audit made before E2b."""
    await suggested(scenario, inbox)
    db = scenario.app.db
    (task_id,) = [r["task_id"] for r in db.query("SELECT task_id FROM email_audits")]
    db.execute("UPDATE tasks SET off_wall = 0 WHERE id = ?", (task_id,))
    db.execute("INSERT INTO cozyla_links (task_id) VALUES (?)", (task_id,))
    await scenario.run_periodic("cozyla.sync")
    assert len(fake_cozyla.in_list(scenario.cozyla_list)) == 1
    db.execute("UPDATE tasks SET off_wall = 1 WHERE id = ?", (task_id,))
    db.execute(
        "UPDATE cozyla_links SET state = 'pending', version = version + 1 WHERE task_id = ?",
        (task_id,),
    )
    await scenario.run_periodic("cozyla.sync")
    assert fake_cozyla.in_list(scenario.cozyla_list) == []
    assert board(scenario).get(task_id).status == "open"


async def test_the_link_opens_that_email(scenario: Scenario, inbox: FakeGmail) -> None:
    # Idea #69: "email audits should have an exact subject for each email and a link".
    await suggested(scenario, inbox)
    (question,) = await scenario.tap("Erin", "Start")
    gmail_id = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE subject = 'Card declined'")
    assert f"https://mail.google.com/mail/u/erin@gmail.com/#all/{gmail_id}\n" in question
