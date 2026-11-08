"""F29f: "Add X to the list" adds X (bug #151), and "which of Erin's tasks could I take?" is
a hand-over, not a routine (bug #147). The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def erins_tasks(scenario: Scenario) -> dict[str, int]:
    board = scenario.app.services.maybe(keys.taskboard)
    assert board is not None
    erin = scenario.member("Erin")
    made = {}
    for title in ("Put the laundry away", "Clean the bird cage"):
        task = await board.create(erin, title, "physical", 2, date(2026, 10, 21), assignee=erin)
        made[title] = task.id
    meds = await board.create(erin, "Take meds", "errand", 1, date(2026, 10, 21), assignee=erin)
    scenario.app.db.execute("UPDATE tasks SET medicine = 1 WHERE id = ?", (meds.id,))
    return made


async def test_bug_147_what_could_i_take_offers_her_tasks(scenario: Scenario) -> None:
    made = await erins_tasks(scenario)
    scenario.primary.queue_tool_call("tasks_i_could_take", {})
    replies = await scenario.say(
        "Husband", "What tasks from Erin could I take to make her day easier?"
    )
    assert replies == [
        "Erin's open tasks you could take:\n- Put the laundry away\n- Clean the bird cage\n"
        "Tap one to take it."
    ]
    assert scenario.last_buttons("Husband") == [
        "Take: Put the laundry away",
        "Take: Clean the bird cage",
    ]
    replies = await scenario.tap("Husband", "Take: Put the laundry away")
    assert "Put the laundry away is yours now. Thanks for taking it." in replies
    board = scenario.app.services.maybe(keys.taskboard)
    assert board is not None
    husband = scenario.member("Husband")
    assert board.get(made["Put the laundry away"]).assignee == husband.id
    told = scenario.app.db.query("SELECT text, member_id FROM outbox WHERE kind = 'task_taken'")
    assert [(r["text"], r["member_id"]) for r in told] == [
        ("Husband took Put the laundry away off your list.", scenario.member("Erin").id)
    ]
    await scenario.tap("Husband", "Take: Put the laundry away")  # again: it's his already
    assert board.get(made["Put the laundry away"]).assignee == husband.id
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM outbox WHERE kind = 'task_taken'") == 1


async def test_a_routine_for_her_tasks_is_refused(scenario: Scenario, fake_cozyla: object) -> None:
    """Reply 249: add_to_wall_routine "Erin's tasks", Morning, every day, task 0."""
    assert scenario.app.services.maybe(keys.wall_routines) is not None
    scenario.primary.queue_tool_call(
        "add_to_wall_routine",
        {"repeat": "", "title": "Erin's tasks", "part": "Morning", "position": "end",
         "task_id": 0},
    )  # fmt: skip
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "What tasks from Erin could I take to make her day easier?")
    result = tool_result(scenario)
    assert "tasks_i_could_take" in result and "Nothing was changed" in result


async def test_bug_151_the_verb_isnt_part_of_the_item(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "create_list", {"name": "Service dog tasks", "personal": False}
    )
    scenario.primary.queue_text("Created.")
    await scenario.say("Erin", "Create a list called Service dog tasks")
    scenario.primary.queue_tool_call(
        "add_to_list",
        {"list": "Service dog tasks", "items": ["Add body double, move from room to room"]},
    )
    await scenario.say("Erin", "Add body double, move from room to room to service dog tasks")
    items = scenario.app.db.query("SELECT name FROM list_items")
    assert [r["name"] for r in items] == ["body double, move from room to room"]


async def test_an_item_that_starts_with_add_in_their_words_is_kept(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("create_list", {"name": "Cooking", "personal": False})
    scenario.primary.queue_text("Created.")
    await scenario.say("Erin", "Create a list called Cooking")
    scenario.primary.queue_tool_call("add_to_list", {"list": "Cooking", "items": ["Add salt"]})
    await scenario.say("Erin", 'Put "Add salt" on the cooking list')
    items = scenario.app.db.query("SELECT name FROM list_items")
    assert [r["name"] for r in items] == ["Add salt"]
