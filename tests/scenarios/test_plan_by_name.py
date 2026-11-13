"""F42f (Michael's bug #206, reply 446): "Can you show me a picture of Erin's run summary?"
finds Erin's step-up plan by its words, and the first turn offers the tool."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from tests.scenarios.test_plan_card import a_run
from tests.scenarios.test_sender_levels import tool_result
from themi.core import keys
from themi.standard.progression import parse_plan


async def test_his_ask_for_her_run_sends_her_plan(scenario: Scenario) -> None:
    await a_run(scenario)
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": 0, "task": "Erin's run"})
    scenario.primary.queue_text("Here it is.")
    replies = await scenario.say("Husband", "Can you show me a picture of Erin's run summary?")
    assert len(scenario.pictures("Husband")) == 1
    assert "Erin's plan, week by week." in replies
    assert "show_step_plan" in {t.name for t in scenario.primary.requests[0].tools}


async def test_my_run_from_her_finds_the_same_one(scenario: Scenario) -> None:
    await a_run(scenario)
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": 0, "task": "my run"})
    scenario.primary.queue_text("There.")
    replies = await scenario.say("Erin", "Show me my run plan")
    assert "Your plan, week by week." in replies


async def test_no_plan_by_that_name(scenario: Scenario) -> None:
    await a_run(scenario)
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": 0, "task": "push-ups"})
    scenario.primary.queue_text("No plan for that.")
    await scenario.say("Erin", "Show my push-ups plan")
    assert tool_result(scenario).startswith("There's no step-up plan for push-ups")
    assert scenario.pictures("Erin") == []


async def test_two_plans_that_match_ask_which(scenario: Scenario) -> None:
    await a_run(scenario)
    board = scenario.app.services.get(keys.taskboard)
    erin = scenario.member("Erin")
    task = await board.create(erin, "Long run", "physical", 2, assignee=erin, nudge=False)
    board.set_progression(
        task.id, erin, parse_plan("3 miles, then up 0.5 a week", scenario.today())
    )
    scenario.primary.queue_tool_call("show_step_plan", {"task_id": 0, "task": "run"})
    scenario.primary.queue_text("Which one?")
    await scenario.say("Erin", "Show my run plan")
    result = tool_result(scenario)
    assert "Go for a run" in result and "Long run" in result and "which" in result.lower()
