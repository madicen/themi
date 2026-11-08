"""F31d (idea #168, "allow email forwarding"): Michael had heard about an urgent email and
asked "Can you forward that email to Erin?"; Themi couldn't. Here Erin's inbox is the one
linked, and she forwards to Husband. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, inbox, verdict
from themi.ai.types import ToolResult
from themi.autonomy import ExecutionContext
from themi_google.connectors.gmail.executors import FORWARDED, MAX_ATTACHMENTS

__all__ = ["inbox"]

HUSBAND = "husband@example.com"
ROOF = {
    "sender": "The Sugarmill Community Corporation <notifications@frontsteps.example>",
    "subject": "Notice of upcoming roofing inspection",
    "text": "Roofers will be on site on 11/12/2026. Please move cars from the carports.",
    "html": "<p>Roofers will be on site on <b>11/12/2026</b>.</p>",
    "attachments": (("schedule.pdf", "application/pdf", 2048),),
}


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def noticed(scenario: Scenario, gmail: FakeGmail, **mail: object) -> int:
    """The roofing email arrives and Erin hears it looks urgent."""
    scenario.app.db.execute("UPDATE members SET email = ? WHERE name = 'Husband'", (HUSBAND,))
    (email,) = await arrive(scenario, gmail, {**ROOF, **mail})
    scenario.primary.queue_structured(
        {
            "results": [
                verdict(email, "urgent", "Roofing inspection on 11/12", urgent_kind="property")
            ]
        }
    )
    await scenario.run_periodic("email.triage")
    await scenario.app.outbox.flush()
    assert any(t.startswith("An email that looks") for t in scenario.inbox("Erin"))
    return email


async def forward(scenario: Scenario, said: str, **args: str) -> list[str]:
    scenario.primary.queue_tool_call("forward_email", {"email": "", "to": "Husband", **args})
    scenario.primary.queue_text("I'll forward that to Husband once you say go.")
    return await scenario.say("Erin", said)


async def test_idea_168_that_email_forwarded_to_the_partner(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await noticed(scenario, inbox)
    replies = await forward(scenario, "Can you forward that email to Husband?")
    assert replies == [
        f'Forwarding to Husband ({HUSBAND}): "Notice of upcoming roofing inspection" from '
        "The Sugarmill Community Corporation <notifications@frontsteps.example>\n"
        "Go ahead, or not now?"
    ]  # the card is the whole answer
    assert inbox.mailbox(ERIN).sent == []  # nothing until she says yes
    await scenario.tap("Erin", "Go ahead")
    (sent,) = inbox.mailbox(ERIN).sent
    assert sent["headers"]["To"] == HUSBAND
    assert sent["headers"]["From"] == ERIN
    assert sent["headers"]["Subject"] == "Fwd: Notice of upcoming roofing inspection"
    assert sent["threadId"] is None  # a new message, not in the original's thread
    assert sent["body"].startswith(FORWARDED)
    assert "From: The Sugarmill Community Corporation" in sent["body"]
    assert "Please move cars from the carports." in sent["body"]
    assert "<b>11/12/2026</b>" in sent["html"]
    assert sent["attachments"] == [("schedule.pdf", "application/pdf", 2048)]
    assert scenario.edits("Erin")[-1]["text"].endswith(
        "Forwarded to Husband: Notice of upcoming roofing inspection."
    )


async def test_the_note_goes_on_top(scenario: Scenario, inbox: FakeGmail) -> None:
    await noticed(scenario, inbox)
    await forward(
        scenario, "Forward that to Husband and say we need to move the car", note="Move the car!"
    )
    await scenario.tap("Erin", "Go ahead")
    (sent,) = inbox.mailbox(ERIN).sent
    assert sent["body"].startswith(f"Move the car!\n\n{FORWARDED}")


async def test_it_always_asks(scenario: Scenario, inbox: FakeGmail) -> None:
    await noticed(scenario, inbox)
    await forward(scenario, "Forward that email to Husband")
    row = scenario.app.db.one("SELECT * FROM action_categories WHERE name = 'email_forward'")
    assert row is not None and row["max_tier"] == 1
    assert (
        scenario.app.db.scalar(
            "SELECT status FROM pending_actions WHERE category = 'email_forward'"
        )
        == "pending"
    )


async def test_an_email_named_by_its_sender(scenario: Scenario, inbox: FakeGmail) -> None:
    await noticed(scenario, inbox)
    await arrive(
        scenario,
        inbox,
        {"sender": "Bob <bob@example.com>", "subject": "Lunch?", "text": "Thursday?"},
    )
    replies = await forward(scenario, "Forward the Sugarmill email to Husband", email="Sugarmill")
    assert "roofing inspection" in replies[0]


async def test_an_unclear_email_is_asked_about(scenario: Scenario, inbox: FakeGmail) -> None:
    scenario.primary.queue_tool_call("forward_email", {"email": "", "to": "Husband"})
    scenario.primary.queue_text("Which email do you mean?")
    await scenario.say("Erin", "Forward that to Husband")
    assert tool_result(scenario).startswith("Not staged: it isn't clear which email.")


async def test_an_address_from_memory_is_refused(scenario: Scenario, inbox: FakeGmail) -> None:
    await noticed(scenario, inbox)
    await forward(scenario, "Forward that to the landlord", to="landlord@example.com")
    assert "that address isn't in their message" in tool_result(scenario)
    await forward(scenario, "Forward that to landlord@example.com", to="landlord@example.com")
    assert (
        scenario.app.db.scalar(
            "SELECT COUNT(*) FROM pending_actions WHERE category = 'email_forward'"
        )
        == 1
    )


async def test_a_retry_never_sends_twice(scenario: Scenario, inbox: FakeGmail) -> None:
    await noticed(scenario, inbox)
    await forward(scenario, "Forward that email to Husband")
    await scenario.tap("Erin", "Go ahead")
    action = scenario.app.db.one("SELECT * FROM pending_actions WHERE category = 'email_forward'")
    assert action is not None
    run = scenario.app.services.autonomy.executors.get("gmail.forward")
    assert run is not None
    key = scenario.app.db.scalar("SELECT idempotency_key FROM email_sends")
    ctx = ExecutionContext(action["id"], scenario.member("Erin"), key)
    said = await run(json.loads(action["payload"]), ctx)  # run again, as after a crash
    assert said == "Forwarded to Husband: Notice of upcoming roofing inspection."
    assert len(inbox.mailbox(ERIN).sent) == 1


async def test_a_too_big_attachment_is_left_out(scenario: Scenario, inbox: FakeGmail) -> None:
    await noticed(
        scenario,
        inbox,
        attachments=(
            ("schedule.pdf", "application/pdf", 2048),
            ("drone-video.mp4", "video/mp4", MAX_ATTACHMENTS + 1),
        ),
    )
    await forward(scenario, "Forward that email to Husband")
    await scenario.tap("Erin", "Go ahead")
    (sent,) = inbox.mailbox(ERIN).sent
    assert sent["attachments"] == [("schedule.pdf", "application/pdf", 2048)]
    assert "Left out, too big to send: drone-video.mp4." in scenario.edits("Erin")[-1]["text"]
