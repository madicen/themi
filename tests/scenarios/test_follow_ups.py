"""F17b, Erin's bug #70: "Immediately after I indicate that I cleaned the bird cage, remind me
to refill the water and replace the food bowls" became a task due the next day."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

REFILL = "Refill water and food bowls"


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


def nudges(scenario: Scenario, title: str) -> list[str]:
    rows = scenario.app.db.query("SELECT text FROM outbox WHERE kind = 'task' ORDER BY id")
    return [r["text"] for r in rows if title in r["text"]]


def open_titles(scenario: Scenario) -> list[str]:
    return [t.title for t in board(scenario).open_for(scenario.member("Erin"))]


async def bird_cage(scenario: Scenario, *, repeats: bool = True) -> Task:
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Clean the bird cage", "physical", 2, assignee=erin, nudge=False
    )
    if repeats:
        await board(scenario).set_schedule(
            task.id, erin, repeat=parse("twice a week", scenario.today())
        )
    scenario.primary.queue_tool_call(
        "add_follow_up",
        {
            "after_task_id": task.id,
            "title": REFILL,
            "steps": ["Refill the water", "Replace the food bowls"],
        },
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say(
        "Erin",
        "Immediately after I indicate that I cleaned the bird cage, remind me to refill the "
        "water and replace the food bowls",
    )
    return task


async def test_it_waits_then_comes_straight_after(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    assert REFILL not in open_titles(scenario)  # no date, no task, no nudge yet
    assert nudges(scenario, REFILL) == []
    turn = scenario.primary.requests[-2].messages[0].text
    assert "Follow-up" not in turn  # added this turn: the next turn shows it
    scenario.primary.queue_text("It's waiting on the bird cage.")
    await scenario.say("Erin", "When will that reminder occur?")
    turn = scenario.primary.last_request.messages[0].text
    assert (
        'Follow-up: "Refill water and food bowls" comes up as soon as "Clean the bird cage" is '
        "done, every time (no date of its own)."
    ) in turn

    scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text("Nice work.")
    replies = await scenario.say("Erin", "I cleaned the bird cage")
    assert any(r.startswith(f"Due today: {REFILL}.") for r in replies)  # at once, in the chat
    assert REFILL in open_titles(scenario)


async def test_every_round_but_never_two_at_once(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    erin = scenario.member("Erin")
    await board(scenario).complete(task.id, erin)
    await board(scenario).complete(task.id, erin)  # the refill from before is still open
    assert open_titles(scenario).count(REFILL) == 1
    (refill,) = [t for t in board(scenario).open_for(erin) if t.title == REFILL]
    await board(scenario).complete(refill.id, erin)
    await board(scenario).complete(task.id, erin)
    assert open_titles(scenario).count(REFILL) == 1  # the next round's


async def test_a_wall_tick_counts_and_it_stays_off_the_wall(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    await board(scenario).complete(task.id, scenario.member("Erin"))  # as the wall's sync does
    await scenario.app.outbox.flush()
    (refill,) = [t for t in board(scenario).open_for(scenario.member("Erin")) if t.title == REFILL]
    assert refill.off_wall and refill.steps == ("Refill the water", "Replace the food bowls")
    assert nudges(scenario, REFILL)


async def test_a_one_off_goes_once_and_a_cancelled_one_takes_it(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await bird_cage(scenario, repeats=False)
    await board(scenario).complete(task.id, erin)
    assert scenario.app.db.query("SELECT 1 FROM task_follow_ups") == []
    other = await bird_cage(scenario, repeats=False)
    await board(scenario).cancel(other.id, erin)
    assert scenario.app.db.query("SELECT 1 FROM task_follow_ups") == []


async def test_removed_from_chat(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    scenario.primary.queue_tool_call("remove_follow_up", {"after_task_id": task.id})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Never mind the refill reminder")
    await board(scenario).complete(task.id, scenario.member("Erin"))
    assert REFILL not in open_titles(scenario)


# F20d, Erin's bug #113: the follow-up went on "Assemble grocery order", an open task that
# had nothing to do with the laundry, because Michael had no laundry task yet.
LAUNDRY = "After Michael brings the laundry upstairs, remind me to put it away"


def results(scenario: Scenario) -> list[str]:
    """What the tools answered, last turn."""
    return [
        block.content
        for message in [r for r in scenario.primary.requests if r.op == "chat"][-1].messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


async def test_follow_up_after_a_job_that_isnt_a_task_yet(scenario: Scenario) -> None:
    erin, michael = scenario.member("Erin"), scenario.member("Husband")
    groceries = await board(scenario).create(
        erin, "Assemble grocery order", "errand", 1, assignee=erin, nudge=False
    )
    scenario.primary.queue_tool_call(
        "add_follow_up",
        {"after_task_id": groceries.id, "title": "Put the laundry away", "steps": []},
    )
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "Bring the laundry upstairs",
            "kind": "physical",
            "effort": 2,
            "due_date": "",
            "due_time": "",
            "from_time": "",
            "assign_to": "Husband",
            "steps": [],
            "check_in": False,
            "importance": "normal",
        },
    )
    scenario.primary.queue_tool_call(  # the task create_task makes next
        "add_follow_up",
        {"after_task_id": groceries.id + 1, "title": "Put the laundry away", "steps": []},
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", LAUNDRY)
    refused, created, saved = results(scenario)
    assert "Assemble grocery order" in refused and "create_task" in refused
    assert "assigned to Husband" in created
    assert saved.startswith("Saved.") and "Bring the laundry upstairs" in saved
    (laundry,) = [t for t in board(scenario).open_for(michael) if "laundry" in t.title]
    assert laundry.id == groceries.id + 1
    assert "Put the laundry away" not in open_titles(scenario)

    await board(scenario).complete(laundry.id, michael)
    await scenario.app.outbox.flush()
    assert "Put the laundry away" in open_titles(scenario)
    assert nudges(scenario, "Put the laundry away")


async def test_the_task_it_follows_is_the_one_they_named(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    run = await board(scenario).create(erin, "Go for a run", "physical", 2, assignee=erin)
    for message in (
        "After my run, remind me to stretch",
        "Once I've run, remind me to stretch",  # "run" said another way: still a word of it
        f"After task {run.id} remind me to stretch",
    ):
        scenario.primary.queue_tool_call(
            "add_follow_up", {"after_task_id": run.id, "title": "Stretch", "steps": []}
        )
        scenario.primary.queue_text("Saved.")
        await scenario.say("Erin", message)
        assert results(scenario)[-1].startswith("Saved."), message
        scenario.app.db.execute("DELETE FROM task_follow_ups")
    scenario.primary.queue_tool_call(
        "add_follow_up", {"after_task_id": run.id, "title": "Stretch", "steps": []}
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", "After I stretch, remind me to stretch again")  # its own words
    assert not results(scenario)[-1].startswith("Saved.")
