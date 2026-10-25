"""Plan scenario 1: a draining note sends the next task to the partner with more room."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult


async def test_erins_draining_note_routes_the_next_task_to_her_husband(
    scenario: Scenario,
) -> None:
    scenario.primary.queue_tool_calls(
        [
            ("log_energy_note", {"effect": -3, "note": "the call with the bank drained her"}, None),
            (
                "create_task",
                {"title": "text the plumber back", "kind": "text", "effort": 2, "due_date": ""},
                None,
            ),
        ]
    )
    scenario.primary.queue_text(
        "That sounds like a lot. Husband has a bit more room today, so the plumber is his."
    )
    replies = await scenario.say(
        "Erin", "That call with the bank wiped me out. Can someone text the plumber back?"
    )

    assert replies == [
        "That sounds like a lot. Husband has a bit more room today, so the plumber is his."
    ]
    assert not any(ch.isdigit() for reply in replies for ch in reply)  # no score, ever

    # The model was told who and why, in words.
    tool_results = [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]
    assert any("assigned to Husband" in r and "more room" in r for r in tool_results)

    task = scenario.app.db.one("SELECT * FROM tasks")
    assert task is not None
    assert task["assignee"] == scenario.member("Husband").id
    assert task["default_owner"] == scenario.member("Erin").id
    assert "Husband seems to have more room" in task["assign_reason"]

    # He gets a two-option nudge at a good moment; Erin gets nothing about it.
    await scenario.advance(hours=10)
    nudge = [t for t in scenario.inbox("Husband") if "text the plumber back" in t]
    assert len(nudge) == 1
    assert scenario.last_buttons("Husband") == ["Done", "Later"]
    assert not any("Done already" in t for t in scenario.inbox("Erin"))

    await scenario.tap("Husband", "Done")
    task = scenario.app.db.one("SELECT status FROM tasks")
    assert task == {"status": "done"}
    assert "Marked done" in scenario.edits("Husband")[-1]["text"]


async def test_later_brings_a_task_back(scenario: Scenario) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    task = await board.create(erin, "Book the dentist", "errand", 1)
    await scenario.advance(hours=10)
    assert any("Book the dentist" in t for t in scenario.inbox("Erin"))

    await scenario.tap("Erin", "Later")
    assert board.get(task.id).status == "snoozed"
    sent_before = len(scenario.inbox("Erin"))

    await scenario.advance(hours=4, minutes=1)
    assert await scenario.run_periodic("tasks.resurface") == 1
    await scenario.advance(hours=10)
    assert board.get(task.id).status == "open"
    assert any("Book the dentist" in t for t in scenario.inbox("Erin")[sent_before:])
