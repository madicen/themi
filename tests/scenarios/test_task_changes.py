"""F30a (#163): a refused task change changes nothing, and "the task you just made" is that
one. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date
from typing import Any

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys
from themi.core.tasks import Task, TaskBoard

STEPS = [
    "Call Dr. Scheinbach to check if he's still practicing",
    "If practicing, book Erin's urgent visit and Husband's checkup on separate days",
    "If retired, call Contemporary Dental and book both there",
]


def board(scenario: Scenario) -> TaskBoard:
    found = scenario.app.services.maybe(keys.taskboard)
    assert found is not None
    return found


def tool_results(scenario: Scenario) -> list[str]:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


def update(task_id: int, **changes: Any) -> dict[str, Any]:
    return {"task_id": task_id, "title": "", "steps": [], "clear_steps": False,
            "assign_to": ""} | changes  # fmt: skip


async def mimi_pill(scenario: Scenario) -> Task:
    """Task 60 on the Pi: Erin's medicine chore, every other day, finished."""
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Mimi pill - 1 tab", "physical", 1, date(2026, 10, 21), assignee=erin
    )
    scenario.app.db.execute(
        "UPDATE tasks SET times_per_week = 3.5, medicine = 1, "
        "created_at = '2026-10-02T08:00:00+00:00' WHERE id = ?",  # made weeks ago
        (task.id,),
    )
    return task


async def call_contemporary(scenario: Scenario) -> Task:
    """Task 78: made from Erin's 8:31 pm message, for Michael."""
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    return await board(scenario).create(
        erin, "Call Contemporary Dental", "call", 2, None, assignee=husband
    )


async def test_bug_163_the_task_just_made_is_the_one_changed(scenario: Scenario) -> None:
    pill = await mimi_pill(scenario)
    made = await call_contemporary(scenario)
    scenario.primary.queue_tool_call(
        "update_task",
        update(pill.id, title="Call dentist office", steps=STEPS, assign_to="Husband"),
    )
    scenario.primary.queue_tool_call(
        "update_task", update(made.id, title="Call dentist office", steps=STEPS)
    )
    scenario.primary.queue_text("I've updated the task for Husband.")
    await scenario.say(
        "Erin",
        "Oh, no, I meant he should call Dr. Scheinbach first. Can you update the task you "
        "just made, with all the steps?",
    )
    first, _ = tool_results(scenario)[-2:]
    assert f"They likely mean task {made.id} (Call Contemporary Dental)" in first
    assert "Nothing was changed" in first
    kept = board(scenario).get(pill.id)
    assert (kept.title, kept.steps) == ("Mimi pill - 1 tab", ())  # untouched
    changed = board(scenario).get(made.id)
    assert (changed.title, list(changed.steps)) == ("Call dentist office", STEPS)


async def test_a_refusal_changes_nothing(scenario: Scenario) -> None:
    """Task 60's title was saved before the assignee was refused."""
    pill = await mimi_pill(scenario)
    scenario.primary.queue_tool_call(
        "update_task", update(pill.id, title="Mimi pill - half tab", assign_to="Husband")
    )
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Rename the Mimi pill to half tab and give it to Husband")
    assert "a chore's people are its schedule's" in tool_results(scenario)[-1]
    assert board(scenario).get(pill.id).title == "Mimi pill - 1 tab"


async def test_a_closed_task_isnt_renamed(scenario: Scenario) -> None:
    pill = await mimi_pill(scenario)
    scenario.app.db.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (pill.id,))
    scenario.primary.queue_tool_call("update_task", update(pill.id, title="Mimi pill - half"))
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Rename the mimi pill to half")
    assert f"Task {pill.id} (Mimi pill - 1 tab) is closed" in tool_results(scenario)[-1]
    assert board(scenario).get(pill.id).title == "Mimi pill - 1 tab"


async def test_a_new_task_that_replaces_the_one_just_made_is_refused(scenario: Scenario) -> None:
    made = await call_contemporary(scenario)
    scenario.primary.queue_tool_call(
        "create_task",
        {"title": "Call dentist office", "kind": "call", "effort": 3, "steps": STEPS,
         "assign_to": "Husband", "due_date": "", "due_time": "", "from_time": "",
         "check_in": False, "importance": "normal"},
    )  # fmt: skip
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Update that task: he should call Dr. Scheinbach instead")
    assert f"they asked to change task {made.id}" in tool_results(scenario)[-1]
    open_calls = [t.title for t in board(scenario).open_for(scenario.member("Husband"))]
    assert open_calls == ["Call Contemporary Dental"]


async def test_updated_when_a_new_task_was_made_says_so(scenario: Scenario) -> None:
    """Reply 297: "I've updated the task for Michael" after the update failed and a second
    task was made."""
    scenario.primary.queue_tool_call("update_task", update(999, title="Call dentist office"))
    scenario.primary.queue_tool_call(
        "create_task",
        {"title": "Call dentist office", "kind": "call", "effort": 3, "steps": STEPS,
         "assign_to": "Husband", "due_date": "", "due_time": "", "from_time": "",
         "check_in": False, "importance": "normal"},
    )  # fmt: skip
    scenario.primary.queue_text("I've updated the task for Husband to call Dr. Scheinbach.")
    replies = await scenario.say("Erin", "Have Husband call Dr. Scheinbach about our visits")
    assert replies[-1] == "Made a new task for Husband: Call dentist office."
