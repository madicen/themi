"""F45e (reply 491 and around it): nothing done is never "Done.", a forgotten weight can come
back, and a weight told isn't just "Got it." The clock starts Wednesday 21 October 2026,
9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.weights_guide import WEIGHTS_GUIDE
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home.gram_weights import GramWeights


def tool_results(scenario: Scenario) -> list[str]:
    from themi.ai.types import ToolResult

    return [
        str(b.content)
        for m in scenario.primary.last_request.messages
        for b in getattr(m, "content", [])
        if isinstance(b, ToolResult)
    ]


def said_to_model(scenario: Scenario) -> str:
    return " ".join(str(m) for m in scenario.primary.last_request.messages)


@pytest.fixture
def weights(scenario: Scenario) -> GramWeights:
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    guides.save(scenario.member("Erin"), "Weights of Common Ingredients", WEIGHTS_GUIDE,
                personal=False)  # fmt: skip
    found = scenario.app.services.maybe(GramWeights)
    assert found is not None
    return found


async def laundry_done(scenario: Scenario) -> int:
    board = scenario.app.services.get(keys.taskboard)
    husband = scenario.member("Husband")
    task = await board.create(husband, "Bring the laundry upstairs", "physical", 1,
                              assignee=husband, nudge=False)  # fmt: skip
    await board.complete(task.id, husband)
    return task.id


async def test_reply_495_a_settled_task_is_never_done(scenario: Scenario) -> None:
    """Reply 495: cancel_task on a task done already said "That one's already settled." as a
    success, complete_task was refused, and the reply was "Done."."""
    task_id = await laundry_done(scenario)
    scenario.primary.queue_tool_call("cancel_task", {"task_id": task_id})
    scenario.primary.queue_tool_call("complete_task", {"task_id": task_id})
    scenario.primary.queue_text("Done.")
    replies = await scenario.say("Husband", "The 2 about weighing that I just did")
    assert "Done." not in replies
    results = tool_results(scenario)
    assert any("Bring the laundry upstairs was already done" in r for r in results)


async def test_a_settled_task_isnt_moved_or_put_off_either(scenario: Scenario) -> None:
    task_id = await laundry_done(scenario)
    scenario.primary.queue_tool_call(
        "reschedule_task",
        {"task_id": task_id, "due_date": "2026-10-23", "due_time": "", "from_time": ""},
    )
    scenario.primary.queue_text("Done.")
    replies = await scenario.say("Husband", "Move bringing the laundry upstairs to Friday")
    assert "Done." not in replies


async def test_a_real_completion_still_says_done(scenario: Scenario) -> None:
    board = scenario.app.services.get(keys.taskboard)
    husband = scenario.member("Husband")
    task = await board.create(husband, "Bring the laundry upstairs", "physical", 1,
                              assignee=husband, nudge=False)  # fmt: skip
    scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text("")
    replies = await scenario.say("Husband", "I brought the laundry upstairs")
    assert replies and "Nothing was changed" not in " ".join(replies)
    assert scenario.app.db.scalar("SELECT status FROM tasks WHERE id = ?", (task.id,)) == "done"


async def test_a_forgotten_weight_can_be_put_back(scenario: Scenario, weights: GramWeights) -> None:
    """Reply 491: "Remove the related tasks" forgot miso; "Put it back" couldn't."""
    weights_line = "1 Tbsp Miso: Weight in Grams 18g"
    scenario.primary.queue_tool_call(
        "weighed_gram_weight", {"ingredient": "miso", "amount": 1, "unit": "tbsp", "grams": 18}
    )
    await scenario.say("Husband", "1 tbsp of miso is 18g")
    assert weights.book().grams("miso", 1, "tbsp") == 18
    scenario.primary.queue_tool_call("forget_gram_weight", {"ingredient": "miso"})
    (forgot,) = await scenario.say("Husband", "Stop converting the miso")
    assert weights_line in forgot and "Say undo to put it back." in forgot
    assert scenario.last_buttons("Husband") == ["Undo"]
    assert not weights.book().has("miso")
    scenario.primary.queue_tool_call("undo_gram_weight", {"ingredient": "miso"})
    (back,) = await scenario.say("Husband", "Put it back")
    assert weights_line in back
    assert weights.book().grams("miso", 1, "tbsp") == 18


async def test_the_undo_button_puts_a_forgotten_weight_back(
    scenario: Scenario, weights: GramWeights
) -> None:
    scenario.primary.queue_tool_call(
        "weighed_gram_weight", {"ingredient": "miso", "amount": 1, "unit": "tbsp", "grams": 18}
    )
    await scenario.say("Husband", "1 tbsp of miso is 18g")
    scenario.primary.queue_tool_call("forget_gram_weight", {"ingredient": "miso"})
    await scenario.say("Husband", "Stop converting the miso")
    await scenario.tap("Husband", "Undo")
    assert weights.book().grams("miso", 1, "tbsp") == 18


async def test_reply_487_got_it_with_nothing_kept_tries_again(
    scenario: Scenario, weights: GramWeights
) -> None:
    """Reply 487: "1 tbsp of miso is about 18g" ran look_up_guide, then said "Got it."."""
    scenario.primary.queue_tool_call("look_up_guide", {"topic": "1 tbsp of miso"})
    scenario.primary.queue_text("Got it.")
    scenario.primary.queue_tool_call(
        "weighed_gram_weight", {"ingredient": "miso", "amount": 1, "unit": "tbsp", "grams": 18}
    )
    scenario.primary.queue_text("Saved: 1 Tbsp miso is 18 g.")
    replies = await scenario.say("Husband", "1 tbsp of miso is about 18g")
    assert weights.book().grams("miso", 1, "tbsp") == 18
    assert replies != ["Got it."]
    assert "nothing was kept" in said_to_model(scenario).lower()


async def test_got_it_to_a_question_answered_by_a_lookup_is_fine(
    scenario: Scenario, weights: GramWeights
) -> None:
    scenario.primary.queue_tool_call("look_up_guide", {"topic": "flour"})
    scenario.primary.queue_text("A cup of flour is 120 g.")
    replies = await scenario.say("Husband", "How much does a cup of flour weigh?")
    assert replies == ["A cup of flour is 120 g."]
    assert "nothing was kept" not in said_to_model(scenario).lower()
