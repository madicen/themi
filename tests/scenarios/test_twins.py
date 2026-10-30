"""P6: near-twin tools. Tools the model mixes up go together, one paragraph in the system
prompt tells them apart, and where the person's own words leave no doubt a tool declines
in favour of its twin."""

from __future__ import annotations

from typing import Any

from tests.evals.scoring import load_cases
from tests.scenarios.harness import Scenario
from themi.core.tools import TWINS, Tool, ToolContext, ToolRegistry, tool, twins_text

FOOD = next(t for t in TWINS if t.name == "food and buying")
QUIET = next(t for t in TWINS if t.name == "quiet time")
RULES = next(t for t in TWINS if t.name == "rules or tasks")
TASK = {
    "kind": "errand",
    "effort": 1,
    "due_date": "",
    "due_time": "",
    "from_time": "",
    "assign_to": "me",
    "steps": [],
    "check_in": False,
    "importance": "normal",
}


def sent(scenario: Scenario, index: int = -1) -> set[str]:
    return {t.name for t in scenario.primary.requests[index].tools}


def stub(name: str) -> Tool:
    async def handler(ctx: ToolContext, args: dict[str, Any]) -> str:
        return ""

    return tool(name, name, {})(handler)


def test_a_twin_set_is_sent_whole_when_any_of_it_is() -> None:
    # create_task is core; set_task_schedule is in the schedules group.
    registry = ToolRegistry([stub(n) for n in ("create_task", "set_task_schedule", "drive_time")])
    assert [s.name for s in registry.specs(set())] == ["create_task", "set_task_schedule"]


def test_a_twin_set_only_brings_tools_that_exist() -> None:
    registry = ToolRegistry([stub("start_break")])
    assert [s.name for s in registry.specs({"settings"})] == ["start_break"]
    assert registry.specs(set()) == []


def test_the_paragraph_goes_only_with_its_set() -> None:
    text = twins_text(["create_task", "remember_fact"])
    assert RULES.text in text
    assert FOOD.text not in text and QUIET.text not in text
    assert twins_text(["remember_fact"]) == ""


async def test_every_call_carries_the_paragraphs_for_the_sets_it_sends(
    scenario: Scenario,
) -> None:
    scenario.primary.queue_text("Hi!")
    await scenario.say("Erin", "Good morning")
    system = scenario.primary.last_request.system
    assert set(FOOD.tools) | set(RULES.tools) <= sent(scenario)
    assert FOOD.text in system and RULES.text in system
    assert QUIET.text not in system and "start_break" not in sent(scenario)
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "I'm taking a break")
    assert set(QUIET.tools) <= sent(scenario)
    assert QUIET.text in scenario.primary.last_request.system


async def test_every_twin_tool_is_built(scenario: Scenario) -> None:
    built = {s.name for s in scenario.app.services.tools.specs()}
    for twins in TWINS:
        assert set(twins.tools) <= built, twins.name


async def test_the_twins_cases_load_and_their_tools_exist(scenario: Scenario) -> None:
    cases = [c for c in load_cases() if c.category == "twins"]
    built = {s.name for s in scenario.app.services.tools.specs()}
    for twins in TWINS:
        needing = [c for c in cases if set(c.expect) & set(twins.tools)]
        for name in twins.tools:
            assert sum(name in c.expect for c in needing) >= 2, name
        assert any(set(c.expect_any) & set(twins.tools) for c in cases), twins.name
    for c in cases:
        assert set((*c.expect, *c.expect_any, *c.forbid, *c.allow)) <= built, c.id


# ----- declining in favour of a twin, on the person's own words -----------------------


async def test_a_task_called_a_rule_is_a_rule(scenario: Scenario) -> None:
    # Eval rule-husband-groceries, with every tool sent: "New rule: ..." became a task.
    scenario.primary.queue_tool_call("create_task", {"title": "Grocery order", **TASK})
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "New rule: the grocery order happens on Sundays")
    assert "propose_rule" in str(scenario.primary.last_request.messages[-1])
    assert scenario.app.db.query("SELECT 1 FROM tasks") == []


async def test_a_reminder_called_a_rule_is_still_a_task(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("create_task", {"title": "Bins", **TASK})
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Make it a rule to remind me about the bins")
    assert len(scenario.app.db.query("SELECT 1 FROM tasks")) == 1


async def test_what_the_house_has_isnt_a_grocery_add(scenario: Scenario) -> None:
    # Evals pantry-rice-low, pantry-olive-oil, twin-pantry-*: news about the house.
    for said in ("We're running low on rice", "Finished the last of the peanut butter"):
        scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["rice"]})
        scenario.primary.queue_text("Okay.")
        await scenario.say("Erin", said)
        assert "update_pantry" in str(scenario.primary.last_request.messages[-1]), said
    assert scenario.app.db.query("SELECT 1 FROM pending_actions") == []


async def test_asking_for_the_list_still_adds_to_it(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["rice"]})
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "We're running low on rice, put it on the list")
    assert "update_pantry" not in str(scenario.primary.last_request.messages[-1])


async def test_holding_messages_isnt_a_break(scenario: Scenario) -> None:
    # Evals task-pause and twin-pause-tonight.
    scenario.primary.queue_tool_call("start_break", {"minutes": 120})
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Don't send me anything tonight")
    assert "pause_messages" in str(scenario.primary.last_request.messages[-1])
    assert scenario.app.db.query("SELECT 1 FROM breaks") == []


async def test_a_break_that_also_mutes_is_still_a_break(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("start_break", {"minutes": 30})
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Taking a break, don't send me anything for a bit")
    assert len(scenario.app.db.query("SELECT 1 FROM breaks")) == 1
