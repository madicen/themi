"""Rx1, Erin's idea #48 (CRITICAL, 2026-10-28): "It is better to miss a dose of Wegovy than
to take it twice." Asked "I don't remember if I took the Wegovy", Themi said "Take it if
you aren't sure". Agreed with Michael (2026-10-28): Themi never advises on doses; unsure
means don't take another until it's checked, and ask the doctor or pharmacist; "not sure"
never becomes done; general information ends with "check with your doctor or pharmacist";
medicine tasks are marked from the title or when said."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core.prompts import build_system
from themi.core.tasks import NOT_SURE_TEXT, TaskBoard, is_medicine


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


def test_medicine_is_known_from_the_title() -> None:
    for title in ("Take Wegovy", "Mimi pill - 1 tab", "Britney flea meds", "Evening medication",
                  "Insulin before dinner", "Refill the inhaler prescription"):  # fmt: skip
        assert is_medicine(title), title
    for title in ("Clean the bird cage", "Go for a run", "Tabletop game night", "Bring bins in"):
        assert not is_medicine(title), title


async def test_a_medicine_nudge_asks_taken_or_not_sure(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Take Wegovy", "physical", 1, check_in=True)
    assert task.medicine
    await scenario.advance(hours=10)
    nudge = next(t for t in scenario.inbox("Erin") if "Take Wegovy" in t)
    assert nudge.endswith("Taken already, or later?")
    assert scenario.last_buttons("Erin") == ["Taken", "Not sure", "Later"]

    await scenario.tap("Erin", "Not sure")
    assert board(scenario).get(task.id).status == "open"  # never done on a "not sure"
    assert scenario.edits("Erin")[-1]["text"] == NOT_SURE_TEXT
    assert "doctor or pharmacist" in NOT_SURE_TEXT


async def test_i_dont_remember_never_marks_it_done(scenario: Scenario) -> None:
    # #48's own words.
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Take Wegovy", "physical", 1, check_in=True)
    scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text("Let's leave it open until you've checked.")
    await scenario.say("Erin", "I don't remember if I took the wegovy or just thought about it")
    assert board(scenario).get(task.id).status == "open"
    result = tool_result(scenario)
    assert result.startswith("Not marked done: they aren't sure they took it.")
    assert "doctor or pharmacist" in result

    scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text("Marked done.")
    await scenario.say("Erin", "Found the pen, I took it this morning")
    assert board(scenario).get(task.id).status == "done"


async def test_marking_a_task_as_medicine_when_said(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Morning routine item 3", "physical", 1)
    assert not task.medicine
    scenario.primary.queue_tool_call("set_task_medicine", {"task_id": task.id, "medicine": True})
    scenario.primary.queue_text("Noted.")
    await scenario.say("Erin", "Routine item 3 is my thyroid medicine")
    assert board(scenario).get(task.id).medicine
    assert any(
        "medicine" in i.summary for i in board(scenario).open_items(erin) if "item 3" in i.summary
    )


def test_the_model_is_told_never_to_advise_on_doses() -> None:
    system = build_system()
    assert "Never tell anyone to take a dose" in system
    assert "check with your doctor or pharmacist" in system


def test_the_medicine_texts_pass_the_strictest_pda_check() -> None:
    from themi.channels.pda import find_demands
    from themi.core.tasks import MEDICINE_ASK

    for text in (NOT_SURE_TEXT, f"Due today: Take Wegovy. {MEDICINE_ASK}"):
        assert find_demands(text, 3) == [], text
