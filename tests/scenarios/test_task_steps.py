"""Steps on tasks (F6a, feedback bug #5): a chore's steps live on the task, not in a rule."""

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult

BIRD_CAGE = [
    "Remove everything from the top tray; throw out dirty or destroyed cardboard",
    "Shake out the top tray",
    "Refill the water dispenser",
]


def new_task(title: str, steps: list[str], assign_to: str = "me") -> dict:
    return {
        "title": title,
        "kind": "physical",
        "effort": 2,
        "due_date": "",
        "assign_to": assign_to,
        "steps": steps,
    }


def results(scenario: Scenario) -> list[ToolResult]:
    return [
        block
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]


async def test_a_chore_keeps_its_steps(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("create_task", new_task("Clean the bird cage", BIRD_CAGE))
    scenario.primary.queue_text("Added, with the steps.")
    await scenario.say("Erin", "add the bird cage, here's what cleaning it involves...")

    board = scenario.app.services.taskboard
    assert board is not None
    (task,) = board.open_for(scenario.member("Erin"))
    assert task.steps == tuple(BIRD_CAGE)
    assert scenario.app.rulebook.drafts(scenario.member("Erin")) == []  # not a rule

    items = [i.summary for i in scenario.app.services.open_items(scenario.member("Erin"))]
    (item,) = [i for i in items if i.startswith("Task") and "bird cage" in i]
    assert "Steps: Remove everything from the top tray" in item and "Refill the water" in item

    await scenario.advance(hours=4, minutes=1)
    (nudge,) = [t for t in scenario.inbox("Erin") if "bird cage" in t]
    assert "\n- Shake out the top tray\n" in nudge
    assert nudge.endswith("Done already, or later?")


async def test_steps_can_be_edited_and_the_title_tidied(scenario: Scenario) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    task = await board.create(
        erin, "Clean the kitchen (declutter, dishes)", "physical", 2, steps=["Declutter"]
    )
    scenario.primary.queue_tool_call(
        "update_task",
        {
            "task_id": task.id,
            "title": "Clean the kitchen",
            "steps": ["Declutter counters and table", "(Optional/Bonus) Spray with rescue"],
            "clear_steps": False,
        },
    )
    scenario.primary.queue_text("Updated.")
    await scenario.say("Erin", "make the last one optional and tidy the name")
    updated = board.get(task.id)
    assert updated.title == "Clean the kitchen"
    assert updated.steps == ("Declutter counters and table", "(Optional/Bonus) Spray with rescue")

    scenario.primary.queue_tool_call(
        "update_task", {"task_id": task.id, "title": "", "steps": [], "clear_steps": False}
    )
    scenario.primary.queue_text("Nothing to change.")
    await scenario.say("Erin", "leave it")
    assert board.get(task.id).steps == updated.steps  # empty means keep

    scenario.primary.queue_tool_call(
        "update_task", {"task_id": task.id, "title": "", "steps": [], "clear_steps": True}
    )
    scenario.primary.queue_text("Cleared.")
    await scenario.say("Erin", "drop the steps")
    assert board.get(task.id).steps == ()


async def test_only_the_people_involved_can_edit_a_task(scenario: Scenario) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    task = await board.create(
        scenario.member("Erin"), "Book the dentist", "errand", 1, assignee=scenario.member("Erin")
    )
    scenario.primary.queue_tool_call(
        "update_task", {"task_id": task.id, "title": "Hijacked", "steps": [], "clear_steps": False}
    )
    scenario.primary.queue_text("Can't do that.")
    await scenario.say("Husband", "rename Erin's dentist task")
    assert board.get(task.id).title == "Book the dentist"
    (result,) = results(scenario)
    assert result.is_error


async def test_the_tasks_page_shows_and_edits_steps(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    task = await board.create(
        scenario.member("Erin"), "Clean the bird cage", "physical", 2, steps=BIRD_CAGE
    )
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/tasks")).text
    assert "Clean the bird cage" in page and "Shake out the top tray" in page

    form = {
        "csrf": csrf,
        "title": "Clean the bird cage",
        "steps": "Shake out the top tray\n\n Refill water \n",
    }
    response = await site.post(f"/tasks/{task.id}/edit", data=form)
    assert response.status_code == 303
    assert board.get(task.id).steps == ("Shake out the top tray", "Refill water")
