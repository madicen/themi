"""F42b (Erin's bug #204, reply 431): in burnout mode, "that email is not important enough to
notify me" is heard: the sender's mail stops being flagged, and the reply says so, with no
task offered. Time-sensitive email alerts wait out burnout mode; urgent ones still come.
The clock starts on Wednesday 21 October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from tests.fakes.gmail_api import FakeGmail
from tests.scenarios.harness import Scenario
from tests.scenarios.test_burnout import turn_on
from tests.scenarios.test_focus import task
from tests.scenarios.test_sender_levels import tool_result
from tests.scenarios.test_triage import arrive, inbox, verdict
from themi.ai.types import ToolResult

__all__ = ["inbox"]  # the fixture, shared with the triage scenarios

STANFORD = {
    "sender": "Stanford Health Care <donotreply.myhealth@stanfordhealthcare.org>",
    "subject": "New message from your care team",
    "text": "You have a new message.",
}
JOYOUS = {
    "sender": "Joyous Care <care@joyous.team>",
    "subject": "Your monthly health check-in",
    "text": "Time for your monthly check-in.",
}
SAID = (
    "That particular email is not important enough to warrant triggering a notification "
    "during burnout mode"
)


async def alert(
    scenario: Scenario, inbox: FakeGmail, mail: dict[str, str], *, severe: bool = False
) -> None:
    (email,) = await arrive(scenario, inbox, mail)
    scenario.primary.queue_structured(
        {"results": [verdict(email, "urgent", "A reminder", urgent_kind="family", severe=severe)]}
    )
    await scenario.run_periodic("email.triage")
    await scenario.app.outbox.flush()


def alerts(scenario: Scenario) -> list[tuple[str, str]]:
    rows = scenario.app.db.query(
        "SELECT status, text FROM outbox WHERE member_id = ? AND kind = 'email' "
        "AND dedupe_key LIKE 'email-urgent:%' ORDER BY id",
        (scenario.member("Erin").id,),
    )
    return [(r["status"], r["text"]) for r in rows]


def results(scenario: Scenario) -> list[str]:
    return [
        block.content
        for message in scenario.primary.requests[-1].messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


async def test_not_important_enough_is_heard_and_no_task_is_offered(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await task(scenario, "Erin", "Put the laundry away", effort=1)
    await alert(scenario, inbox, STANFORD)
    await alert(scenario, inbox, JOYOUS)
    await turn_on(scenario)
    # Reply 431: a rule about the wrong email, then a task.
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "rule_id": 0,
            "applies_to": "personal",
            "summary": "Do not trigger notifications for that Stanford Health Care message",
            "category": "",
            "text": "Do not trigger notifications for the Stanford Health Care message.",
            "kind": "policy",
        },
    )
    scenario.primary.queue_tool_call("burnout_task", {})
    scenario.primary.queue_tool_call(
        "set_sender_levels", {"sender": "Joyous Care", "urgency": "no_rush", "importance": "not"}
    )
    scenario.primary.queue_text("Done.")
    replies = await scenario.say("Erin", SAID)
    refusal, declined, _ = results(scenario)
    assert "set_sender_levels" in refusal and "keep_email" not in refusal
    assert "Joyous Care" in refusal  # the latest alert, not Stanford's
    assert "answer that" in declined
    assert replies == [
        "Got it: I won't flag email from Joyous Care like that again. Rest is all that's on now."
    ]

    await alert(scenario, inbox, JOYOUS)  # no rush now: no message at all
    assert len([t for _, t in alerts(scenario) if "Joyous" in t]) == 1


async def test_one_email_called_urgent_still_gets_keep_email(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "rule_id": 0,
            "applies_to": "personal",
            "summary": "The Schwab email is urgent",
            "category": "",
            "text": "The Schwab email is urgent.",
            "kind": "policy",
        },
    )
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "The Schwab email is urgent")
    assert "keep_email" in tool_result(scenario)


async def test_in_burnout_time_sensitive_mail_waits_and_urgent_comes(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await turn_on(scenario)
    await alert(scenario, inbox, JOYOUS)
    await alert(scenario, inbox, STANFORD, severe=True)
    assert [(status, text.split(" (")[0]) for status, text in alerts(scenario)] == [
        ("queued", "An email that looks time-sensitive"),
        ("sent", "An email that looks urgent"),
    ]
    scenario.primary.queue_tool_call("end_burnout", {})
    scenario.primary.queue_text("Welcome back.")
    await scenario.say("Erin", "I'm out of burnout mode")
    await scenario.advance(minutes=1)
    assert [status for status, _ in alerts(scenario)] == ["sent", "sent"]


async def test_out_of_burnout_time_sensitive_mail_comes(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    await alert(scenario, inbox, JOYOUS)
    assert [status for status, _ in alerts(scenario)] == ["sent"]


async def test_asked_for_one_thing_burnout_task_still_answers(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Water the plants", effort=1)
    await turn_on(scenario)
    scenario.primary.queue_tool_call("burnout_task", {})
    scenario.primary.queue_text("Or the oven!")
    assert await scenario.say("Erin", "Give me one thing I could do") == [
        "If you'd like one thing: Water the plants. Nothing at all is fine too."
    ]
