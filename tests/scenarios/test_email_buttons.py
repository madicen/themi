"""F50c (Michael's idea #233: "urgent email notices aren't actionable"): an email notice
has [Open in Gmail], [Not important], [Mark read] and [Make it a task]."""

from __future__ import annotations

import json
from typing import Any

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.telegram_api import markup
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, verdict
from themi import clock
from themi.channels.events import ButtonPress, InboundEvent
from themi.core import keys

__all__ = ["inbox"]

SCHWAB = {
    "sender": "Schwab <donotreply@email.schwab.com>",
    "subject": "Your November snapshot",
    "text": "Your monthly account snapshot and market commentary.",
}
CRUNCHYROLL = {
    "sender": "Crunchyroll <hello@info.crunchyroll.com>",
    "subject": "New sign-in",
    "text": "Your account was accessed from a new device.",
}
SCHWAB_SUMMARY = "Schwab monthly account snapshot and market commentary for November"
CRUNCHY_SUMMARY = "Crunchyroll account accessed from a new device in Mountain View, CA today"


async def alert(scenario: Scenario, inbox: FakeGmail, mail: dict[str, Any], summary: str) -> int:
    (email_id,) = await arrive(scenario, inbox, mail)
    scenario.primary.queue_structured(
        {"results": [verdict(email_id, "urgent", summary, urgent_kind="financial")]}
    )
    await scenario.run_periodic("email.triage")
    return email_id


def keyboard(scenario: Scenario, starts: str = "") -> list[dict[str, Any]]:
    """The buttons on Erin's latest message (that starts with `starts`), or its latest edit."""
    chat = scenario.member("Erin").telegram_user_id
    for _, params in reversed(scenario.telegram.calls_in_order("sendMessage", "editMessageText")):
        text = str(params.get("text", ""))
        if int(params["chat_id"]) == chat and markup(params) and text.startswith(starts):
            return [b for row in markup(params)["inline_keyboard"] for b in row]
    raise AssertionError("no buttons")


def labels(scenario: Scenario, starts: str = "") -> list[str]:
    return [b["text"] for b in keyboard(scenario, starts)]


def last_edit(scenario: Scenario) -> str:
    return str(scenario.telegram.calls("editMessageText")[-1]["text"])


def alerts(scenario: Scenario) -> list[str]:
    return [t for t in scenario.inbox("Erin") if t.startswith("An email that looks")]


async def test_an_urgent_alert_has_the_four_buttons(scenario: Scenario, inbox: FakeGmail) -> None:
    email_id = await alert(scenario, inbox, SCHWAB, SCHWAB_SUMMARY)
    assert labels(scenario) == ["Open in Gmail", "Not important", "Mark read", "Make it a task"]
    opened = keyboard(scenario)[0]
    gmail_id = scenario.app.db.scalar("SELECT gmail_id FROM emails WHERE id = ?", (email_id,))
    assert opened["url"] == f"https://mail.google.com/mail/u/{ERIN}/#all/{gmail_id}"
    assert "callback_data" not in opened


async def test_not_important_quiets_the_sender_and_undo_puts_it_back(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await alert(scenario, inbox, SCHWAB, SCHWAB_SUMMARY)
    await scenario.tap("Erin", "Not important")
    assert last_edit(scenario).endswith("\n\nMail from Schwab won't alert you again.")
    assert labels(scenario) == ["Open in Gmail", "Mark read", "Make it a task", "Undo"]
    audit = scenario.app.services.get(keys.email_audit)
    account = scenario.app.store.linked_account_by_address("gmail", ERIN)
    assert account is not None
    assert audit.no_rush(account.id, "donotreply@email.schwab.com")

    await scenario.tap("Erin", "Undo")
    assert last_edit(scenario).endswith("Mail from Schwab alerts you as before.")
    assert labels(scenario) == ["Open in Gmail", "Not important", "Mark read", "Make it a task"]
    assert not audit.no_rush(account.id, "donotreply@email.schwab.com")
    assert audit.sender_levels(account.id, "donotreply@email.schwab.com") == (0, 0)

    await scenario.tap("Erin", "Not important")
    before = len(alerts(scenario))
    await alert(scenario, inbox, {**SCHWAB, "subject": "Your December snapshot"}, SCHWAB_SUMMARY)
    assert len(alerts(scenario)) == before  # next month's sends nothing


async def test_mark_read_is_done_and_asks_first_while_its_paused(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """A tap is their own yes (`requested`); a paused (escalated) category still asks."""
    modified = inbox.calls_to("modify")
    await alert(scenario, inbox, CRUNCHYROLL, CRUNCHY_SUMMARY)
    await scenario.tap("Erin", "Mark read")
    assert last_edit(scenario).endswith("\n\nMarked read.")
    assert inbox.calls_to("modify") == modified + 1
    assert "Mark read" not in labels(scenario)

    scenario.app.services.autonomy.escalate("email_mark_read", "a test")
    email_id = await alert(scenario, inbox, SCHWAB, SCHWAB_SUMMARY)
    await scenario.tap("Erin", "Mark read")
    action = scenario.app.db.one(
        "SELECT category, status, executor, payload FROM pending_actions ORDER BY id DESC"
    )
    assert action is not None
    assert (action["category"], action["status"], action["executor"]) == (
        "email_mark_read",
        "pending",
        "gmail.mark_read",
    )
    assert f'"email_id": {email_id}' in action["payload"]
    assert inbox.calls_to("modify") == modified + 1


async def test_make_it_a_task_and_undo(scenario: Scenario, inbox: FakeGmail) -> None:
    await alert(scenario, inbox, CRUNCHYROLL, CRUNCHY_SUMMARY)
    await scenario.tap("Erin", "Make it a task")
    title = "Crunchyroll account accessed from a new device in Mountain View"
    assert last_edit(scenario).endswith(f"\n\nTask added: {title}.")
    board = scenario.app.services.get(keys.taskboard)
    (task,) = [t for t in board.open_for(scenario.member("Erin")) if t.title == title]
    assert task.assignee == scenario.member("Erin").id

    await scenario.tap("Erin", "Undo")
    assert last_edit(scenario).endswith(f"Taken off your tasks: {title}.")
    assert board.get(task.id).status == "cancelled"
    assert "Make it a task" in labels(scenario)


async def test_a_tap_on_someone_elses_inbox_says_so(scenario: Scenario, inbox: FakeGmail) -> None:
    await alert(scenario, inbox, CRUNCHYROLL, CRUNCHY_SUMMARY)
    tapped = next(b for b in keyboard(scenario) if b["text"] == "Make it a task")
    token = scenario.app.db.one(
        "SELECT kind, payload FROM callback_tokens WHERE token = ?", (tapped["callback_data"],)
    )
    assert token is not None
    import json

    husband = scenario.member("Husband")
    press = ButtonPress("Make it a task", token["kind"], json.loads(token["payload"]), None)
    event = InboundEvent("button", husband, husband.id, None, clock.now(), 0, button=press)
    await scenario.app.services.button_handlers["email_task"](event)
    assert scenario.inbox("Husband")[-1] == "That's Erin's inbox, so it's theirs to sort."
    assert not scenario.app.db.scalar("SELECT COUNT(*) FROM tasks WHERE title LIKE 'Crunchy%'")


async def test_the_unusual_amount_alert_has_them_and_keeps_resume(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    from tests.scenarios.test_expected import automatic, pge_mail, sort

    automatic(scenario)
    for amount in ("$100.00", "$104.10", "$98.00", "$106.00", "$460.00"):
        await sort(scenario, await arrive(scenario, inbox, pge_mail(amount)))
    shown = "A confirmation from PG&E"
    assert labels(scenario, shown) == [
        "Open in Gmail", "Not important", "Mark read", "Make it a task", "Resume automatic",
    ]  # fmt: skip
    await scenario.tap("Erin", "Make it a task")
    assert labels(scenario, shown)[-2:] == ["Undo", "Resume automatic"]


# ----- F55b (bug #240): a notice queued before F50c, held, then released ------------------


def queue_old_notice(scenario: Scenario, email_id: int | None, text: str) -> None:
    """A notice as triage queued it before F50c (no buttons), held in the morning's Email
    tray, as outbox 2177 was on the Pi."""
    now = clock.now().isoformat()
    scenario.app.db.execute(
        "INSERT INTO outbox (member_id, text, buttons, priority, kind, dedupe_key, status, "
        "send_after, created_at, tray) VALUES (?, ?, '[]', 'normal', 'email', ?, 'queued', ?, "
        "?, 'email')",
        (
            scenario.member("Erin").id,
            text,
            f"email-urgent:{email_id}" if email_id is not None else None,
            now,
            now,
        ),
    )


async def release_email(scenario: Scenario) -> None:
    await scenario.app.outbox.release(scenario.member("Erin"), "email")


OLD_NOTICE = "An email that looks time-sensitive (money) arrived in your inbox: Schwab snapshot."


async def test_a_held_notice_from_before_the_buttons_gets_them_when_it_goes(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    (email_id,) = await arrive(scenario, inbox, SCHWAB)
    queue_old_notice(scenario, email_id, OLD_NOTICE)
    await release_email(scenario)
    assert labels(scenario, OLD_NOTICE) == [
        "Open in Gmail",
        "Not important",
        "Mark read",
        "Make it a task",
    ]
    await scenario.tap("Erin", "Make it a task")
    assert "Task added:" in last_edit(scenario)


async def test_a_held_notice_whose_email_is_gone_goes_as_it_is(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    queue_old_notice(scenario, 99999, OLD_NOTICE)
    await release_email(scenario)
    assert OLD_NOTICE in scenario.inbox("Erin")
    sent = scenario.app.db.one("SELECT buttons FROM outbox WHERE text = ?", (OLD_NOTICE,))
    assert sent is not None and sent["buttons"] == "[]"


async def test_a_notice_with_buttons_is_unchanged(scenario: Scenario, inbox: FakeGmail) -> None:
    await alert(scenario, inbox, SCHWAB, SCHWAB_SUMMARY)
    row = scenario.app.db.one("SELECT buttons FROM outbox WHERE kind = 'email'")
    assert row is not None
    assert [b["label"] for b in json.loads(row["buttons"])] == [
        "Open in Gmail",
        "Not important",
        "Mark read",
        "Make it a task",
    ]
