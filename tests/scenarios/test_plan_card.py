"""DC11: "show my run plan" sends the plan's weeks as a picture; a task with no plan is
said plainly."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.standard.progression import parse_plan


async def a_run(scenario: Scenario) -> int:
    board = scenario.app.services.get(keys.taskboard)
    erin = scenario.member("Erin")
    task = await board.create(erin, "Go for a run", "physical", 2, assignee=erin, nudge=False)
    plan = parse_plan("1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays", scenario.today())
    board.set_progression(task.id, erin, plan)
    return task.id


async def test_asking_sends_the_plan_as_a_picture(scenario: Scenario) -> None:
    task_id = await a_run(scenario)
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": task_id, "task": ""})
    scenario.primary.queue_text("Here's how it goes.")
    replies = await scenario.say("Erin", "Show me my run plan")
    assert "Your plan, week by week." in replies
    assert len(scenario.pictures("Erin")) == 1


async def test_without_pictures_the_plan_is_read_back(scenario: Scenario) -> None:
    def broken(svg: str, width: int | None) -> bytes:
        raise ValueError("no fonts here")

    scenario.app.services.get(keys.drawings).renderer.convert = broken
    task_id = await a_run(scenario)
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": task_id, "task": ""})
    scenario.primary.queue_text("There.")
    replies = await scenario.say("Erin", "Show me my run plan")
    assert any("1.3 miles from" in r for r in replies), replies
    assert scenario.pictures("Erin") == []


async def test_a_task_without_a_plan_isnt_drawn(scenario: Scenario) -> None:
    board = scenario.app.services.get(keys.taskboard)
    erin = scenario.member("Erin")
    task = await board.create(erin, "Water the plants", "physical", 1, assignee=erin, nudge=False)
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": task.id, "task": ""})
    scenario.primary.queue_text("That one has no plan.")
    assert await scenario.say("Erin", "Show the plan for watering") == ["That one has no plan."]
    assert scenario.pictures("Erin") == []
