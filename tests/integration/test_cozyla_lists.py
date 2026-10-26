"""C1c: every list on the wall, reassigning there, the family member, and naming a list."""

from __future__ import annotations

from typing import Any

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi.core.tasks import Task, TaskBoard

FAMILY_UID = "m-madicen family"


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def sync(scenario: Scenario) -> Any:
    return await scenario.run_periodic("cozyla.sync")


def tasks(scenario: Scenario, status: str = "open") -> dict[str, Task]:
    rows = scenario.app.db.query("SELECT id FROM tasks WHERE status = ? ORDER BY id", (status,))
    return {(t := board(scenario).get(r["id"])).title: t for r in rows}


def on(fake: FakeCozyla, list_id: int) -> dict[str, dict[str, Any]]:
    return {t["todoTitle"]: t for t in fake.in_list(list_id)}


def nudges(scenario: Scenario, title: str) -> list[tuple[str, str]]:
    """(who, priority) for each task nudge about `title`, sent or waiting."""
    names = {m.id: m.name for m in scenario.app.store.list_members()}
    return [
        (names[r["member_id"]], r["priority"])
        for r in scenario.app.db.query("SELECT * FROM outbox WHERE kind = 'task' ORDER BY id")
        if title in r["text"]
    ]


async def test_items_assigned_on_any_list_are_tasks_and_unassigned_ones_are_left(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    fake_cozyla.add_todo(cook, "Lasagna")  # the family's list, nobody's job
    fake_cozyla.add_todo(cook, "Make the pie crust", assignee="m-erin")
    await sync(scenario)
    assert set(tasks(scenario)) == {"Make the pie crust"}
    assert nudges(scenario, "Make the pie crust") == [("Erin", "low")]  # an existing list

    fake_cozyla.add_todo(cook, "Prep the stock", assignee="m-husband")  # new since
    lasagna = on(fake_cozyla, cook)["Lasagna"]["todoId"]
    fake_cozyla.edit(lasagna, assignMemberUid="m-erin")  # now it's someone's
    await sync(scenario)
    assert set(tasks(scenario)) == {"Make the pie crust", "Prep the stock", "Lasagna"}
    assert tasks(scenario)["Prep the stock"].assignee == scenario.member("Husband").id
    assert nudges(scenario, "Prep the stock") == [("Husband", "normal")]
    assert nudges(scenario, "Lasagna") == [("Erin", "normal")]

    fake_cozyla.tick(on(fake_cozyla, cook)["Make the pie crust"]["todoId"])
    await sync(scenario)
    assert "Make the pie crust" in tasks(scenario, "done")


async def test_reassigning_and_reopening_on_the_wall_follow_through(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    todo = fake_cozyla.add_todo(scenario.cozyla_list, "Fix the gate", assignee="m-erin")
    await sync(scenario)
    gate = tasks(scenario)["Fix the gate"]

    fake_cozyla.edit(todo, assignMemberUid="m-husband")
    await sync(scenario)
    assert board(scenario).get(gate.id).assignee == scenario.member("Husband").id
    assert ("Husband", "normal") in nudges(scenario, "Fix the gate")
    assert fake_cozyla.todos[todo]["assignMemberUid"] == "m-husband"  # nothing sent back

    fake_cozyla.tick(todo)
    await sync(scenario)
    assert board(scenario).get(gate.id).status == "done"
    fake_cozyla.tick(todo, done=False)
    await sync(scenario)
    assert board(scenario).get(gate.id).status == "open"


async def test_the_family_member_means_both_of_you(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    fake_cozyla.add_member("Madicen Family")
    await sync(scenario)
    fake_cozyla.add_todo(scenario.cozyla_list, "Clean out the garage", assignee=FAMILY_UID)
    await sync(scenario)
    garage = tasks(scenario)["Clean out the garage"]
    assert garage.shared
    assert sorted(who for who, _ in nudges(scenario, "Clean out the garage")) == [
        "Erin",
        "Husband",
    ]
    assert garage.id in {t.id for t in board(scenario).open_for(scenario.member("Husband"))}

    mine = await board(scenario).create(
        scenario.member("Erin"), "Book the movers", "call", 2, assignee=scenario.member("Erin")
    )
    await board(scenario).reassign(mine.id, None, shared=True)
    await sync(scenario)
    assert on(fake_cozyla, scenario.cozyla_list)["Book the movers"]["assignMemberUid"] == (
        FAMILY_UID
    )


async def test_a_to_do_moved_on_the_wall_stays_where_it_went(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    todo = fake_cozyla.add_todo(scenario.cozyla_list, "Bake bread", assignee="m-erin")
    await sync(scenario)
    bread = tasks(scenario)["Bake bread"]
    fake_cozyla.edit(todo, todoListId=cook)
    await sync(scenario)
    assert board(scenario).get(bread.id).status == "open"

    await board(scenario).update(bread.id, scenario.member("Erin"), title="Bake sourdough")
    await sync(scenario)
    assert "Bake sourdough" in on(fake_cozyla, cook)
    assert "Bake sourdough" not in on(fake_cozyla, scenario.cozyla_list)


async def test_a_task_can_be_put_on_a_named_list(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    await sync(scenario)
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "Make lasagna",
            "kind": "physical",
            "effort": 3,
            "due_date": "",
            "assign_to": "me",
            "steps": [],
            "check_in": False,
            "due_time": "",
        },
    )
    scenario.primary.queue_tool_call(
        "put_task_on_wall_list", {"task_id": 1, "list": "things to cook"}
    )
    scenario.primary.queue_text("It's on Things to Cook.")
    await scenario.say("Erin", "I'll make lasagna, put it on things to cook")
    await sync(scenario)
    assert on(fake_cozyla, cook)["Make lasagna"]["assignMemberUid"] == "m-erin"
    assert "Make lasagna" not in on(fake_cozyla, scenario.cozyla_list)

    scenario.primary.queue_tool_call("put_task_on_wall_list", {"task_id": 1, "list": "Garden"})
    scenario.primary.queue_text("There's no Garden list.")
    await scenario.say("Erin", "actually move it to the garden list")
    result = str(scenario.primary.last_request.messages[-1].content[0])
    assert "no list called 'Garden'" in result and "Things to Cook" in result


async def test_items_that_arent_anyones_job_go_straight_on_the_list(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    await sync(scenario)
    scenario.primary.queue_tool_call(
        "add_to_wall_list", {"list": "Things to Cook", "items": ["Lasagna", "Pho"]}
    )
    scenario.primary.queue_text("Added.")
    await scenario.say("Erin", "add lasagna and pho to things to cook")
    added = on(fake_cozyla, cook)
    assert set(added) == {"Lasagna", "Pho"}
    assert all(t["assignMemberUid"] is None for t in added.values())
    await sync(scenario)
    assert tasks(scenario) == {}  # a list, not jobs

    scenario.primary.queue_tool_call(
        "add_to_wall_list", {"list": "Things to Cook", "items": ["Tacos"]}
    )
    scenario.primary.queue_text("Want tacos on there?")
    await scenario.say("Erin", "what should we cook this week?")  # not asked for
    assert "Tacos" not in on(fake_cozyla, cook)
    assert any(
        "Tacos for Things to Cook" in i.summary
        for i in scenario.app.services.awaiting(scenario.member("Erin"))
    )

    scenario.primary.queue_tool_call(
        "add_to_wall_list", {"list": "Family", "items": ["Mow the lawn"]}
    )
    scenario.primary.queue_text("That's a task.")
    await scenario.say("Erin", "add mow the lawn to the family list")
    assert "use create_task" in str(scenario.primary.last_request.messages[-1].content[0])
