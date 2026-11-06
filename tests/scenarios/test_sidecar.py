"""CM1b: conversation mode's sidecar picks out tasks, events and modes after a chat reply,
through Themi's own tools. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json
from typing import Any

from tests.fakes.gcal_api import FakeGcal
from tests.scenarios.harness import Scenario
from tests.scenarios.test_calendar_events import dentist, linked, on_primary
from tests.scenarios.test_conversation_mode import chat_on
from tests.scenarios.test_twins import TASK
from themi.core.sidecar import REACTION

__all__ = ["linked"]  # the fixture, used by name


def reactions(scenario: Scenario) -> list[str]:
    found = []
    for call in scenario.telegram.calls("setMessageReaction"):
        raw = call["reaction"]
        found += [r["emoji"] for r in (json.loads(raw) if isinstance(raw, str) else raw)]
    return found


def open_titles(scenario: Scenario) -> list[str]:
    rows = scenario.app.db.query("SELECT title FROM tasks WHERE status = 'open' ORDER BY id")
    return [r["title"] for r in rows]


def logged(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query("SELECT * FROM sidecar_log ORDER BY id")


def sidecar_requests(scenario: Scenario) -> list:
    return [r for r in scenario.primary.requests if "quietly read one turn" in r.system]


async def chat(scenario: Scenario, said: str, reply: str, *calls: tuple[str, dict]) -> list[str]:
    """`said` gets the chat reply `reply`; then the sidecar makes `calls` (or none)."""
    scenario.primary.queue_text(reply)
    if calls:
        scenario.primary.queue_tool_calls([(n, a, None) for n, a in calls], text="Noted it.")
    else:
        scenario.primary.queue_text("nothing")
    return await scenario.say("Erin", said)


async def test_a_task_said_in_passing_is_picked_out(scenario: Scenario) -> None:
    await chat_on(scenario)
    vet = {"title": "Call the vet", **TASK, "due_date": "2026-10-22"}
    replies = await chat(
        scenario,
        "ugh, I need to call the vet Thursday",
        "Ugh, vet calls. Is it the cat again?",
        ("create_task", vet),
    )
    assert replies == ["Ugh, vet calls. Is it the cat again?"]  # nothing more said
    assert "Call the vet" in open_titles(scenario)
    assert reactions(scenario) == [REACTION]
    [row] = logged(scenario)
    [item] = json.loads(row["items"])
    assert item["tool"] == "create_task" and item["outcome"] == "ok"
    assert row["note"] == "Noted it." and row["telegram_message_id"]
    request = sidecar_requests(scenario)[0]
    assert {t.name for t in request.tools} <= {
        "create_task", "complete_task", "cancel_task", "add_calendar_event", "remember_fact",
        "start_burnout", "end_burnout", "pause_messages", "resume_messages",
    }  # fmt: skip
    turn = request.messages[0].text
    assert "<data>" in turn and "Erin: ugh, I need to call the vet Thursday" in turn
    assert "Themi: Ugh, vet calls." in turn


async def test_someday_makes_nothing(scenario: Scenario) -> None:
    await chat_on(scenario)
    before = open_titles(scenario)
    await chat(scenario, "I should really clean the garage someday", "Garages: endless.")
    assert open_titles(scenario) == before
    assert reactions(scenario) == [] and logged(scenario) == []


async def test_only_a_task_it_was_shown_can_be_ticked(scenario: Scenario) -> None:
    await chat_on(scenario)
    await chat(scenario, "ugh, the bins", "Bins!", ("create_task", {"title": "Bins", **TASK}))
    [task_id] = [
        r["id"] for r in scenario.app.db.query("SELECT id FROM tasks WHERE title = 'Bins'")
    ]
    await chat(
        scenario, "finally sorted the bins out", "Nice.", ("complete_task", {"task_id": 999})
    )
    assert f"Task {task_id} " in sidecar_requests(scenario)[1].messages[0].text  # shown by number
    assert "Bins" in open_titles(scenario) and len(logged(scenario)) == 1  # 999 dropped
    await chat(
        scenario, "bins are sorted, honestly", "Nice.", ("complete_task", {"task_id": task_id})
    )
    assert "Bins" not in open_titles(scenario)
    assert len(logged(scenario)) == 2


async def test_burnout_mode_from_a_partners_words_is_refused(scenario: Scenario) -> None:
    await chat_on(scenario)
    await chat(
        scenario,
        "Husband is so burnt out lately, he could use burnout mode",
        "That's hard to watch.",
        ("start_burnout", {}),
    )
    assert scenario.app.services.burnout is not None
    assert scenario.app.services.burnout.current(scenario.member("Erin")) is None
    assert reactions(scenario) == [] and logged(scenario) == []


async def test_their_own_burnout_mode_is_turned_on_and_said(scenario: Scenario) -> None:
    await chat_on(scenario)
    replies = await chat(
        scenario,
        "honestly I'm burnt out, I want burnout mode",
        "I hear you.",
        ("start_burnout", {}),
    )
    assert scenario.app.services.burnout is not None
    assert scenario.app.services.burnout.current(scenario.member("Erin")) is not None
    assert replies[0] == "I hear you." and len(replies) == 2  # and burnout's own few words
    assert reactions(scenario) == [REACTION]


async def test_two_quick_turns_make_one_task(scenario: Scenario) -> None:
    """The second pass waits for the first, so it sees the task already made."""
    await chat_on(scenario)
    sidecar = scenario.app.services.conversation.sidecar  # type: ignore[union-attr]
    erin = scenario.member("Erin")
    for _ in range(2):
        scenario.primary.queue_tool_calls(
            [("create_task", {"title": "Call the vet", **TASK}, None)]
        )
    sidecar.schedule(erin, "need to call the vet", "Ugh.", None, [])
    sidecar.schedule(erin, "seriously, the vet", "Yes.", None, [])
    await sidecar.drain()
    assert open_titles(scenario).count("Call the vet") == 1
    second = sidecar_requests(scenario)[1].messages[0].text
    assert "Call the vet" in second  # among the open items it was shown


async def test_an_event_mentioned_waits_on_a_card_and_claims_nothing(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await chat_on(scenario)
    plumber = dentist(title="Plumber", date="2026-10-22", start="09:00", location="")
    replies = await chat(
        scenario,
        "the plumber's coming Thursday morning, finally",
        "Finally! Fingers crossed it's quick.",
        ("add_calendar_event", plumber),
    )
    assert replies[0] == "Finally! Fingers crossed it's quick."
    assert replies[1] == "Plumber, Thu 22 Oct, 9-10 am, for your calendar\nGo ahead, or not now?"
    assert "Plumber" not in on_primary(linked)
    assert reactions(scenario) == [REACTION]


async def test_a_sidecar_failure_says_nothing(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.queue_text("What a week.")
    scenario.primary.fail(3, status=400)  # the sidecar's call, not retried
    scenario.fallback.fail(3, status=400)
    replies = await scenario.say("Erin", "what a week")
    assert replies == ["What a week."]
    assert reactions(scenario) == [] and logged(scenario) == []


async def test_what_was_picked_out_is_on_my_settings(scenario: Scenario, site) -> None:
    from tests.fixtures.web import sign_in

    await chat_on(scenario)
    await chat(
        scenario,
        "ugh, I need to call the vet Thursday",
        "Ugh.",
        ("create_task", {"title": "Call the vet", **TASK}),
    )
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert "Picked out lately" in page and "Call the vet" in page


async def test_a_tool_that_isnt_set_up_doesnt_borrow_the_last_outcome(
    scenario: Scenario,
) -> None:
    """No Google here, so add_calendar_event isn't registered: it's not counted as done."""
    await chat_on(scenario)
    await chat(
        scenario,
        "ugh, need to call the vet, and dinner at Sam's Saturday at 7",
        "Busy week!",
        ("create_task", {"title": "Call the vet", **TASK}),
        ("add_calendar_event", dentist(title="Dinner at Sam's", date="2026-10-24", start="19:00")),
    )
    [row] = logged(scenario)
    outcomes = {i["tool"]: i["outcome"] for i in json.loads(row["items"])}
    assert outcomes == {"create_task": "ok", "add_calendar_event": "failed"}
