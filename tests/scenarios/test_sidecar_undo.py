"""CM1c: "that wasn't a task" takes the sidecar's latest pass back, and a /bug after one
marks it as a miss to look at."""

from __future__ import annotations

import json

from tests.scenarios.harness import Scenario
from tests.scenarios.test_conversation_mode import chat_on
from tests.scenarios.test_sidecar import chat, logged, open_titles
from tests.scenarios.test_twins import TASK
from themi.standard.sidecar import NOTHING_TO_UNDO_TEXT


async def made_a_vet_task(scenario: Scenario) -> None:
    await chat_on(scenario)
    await chat(
        scenario,
        "ugh, I need to call the vet Thursday",
        "Ugh.",
        ("create_task", {"title": "Call the vet", **TASK}),
    )
    assert "Call the vet" in open_titles(scenario)


async def test_that_wasnt_a_task_takes_it_back(scenario: Scenario) -> None:
    await made_a_vet_task(scenario)
    replies = await scenario.say("Erin", "that wasn't a task")
    assert replies == ['Taken back: "Call the vet". Noted as one I got wrong.']
    assert "Call the vet" not in open_titles(scenario)
    assert [r["status"] for r in logged(scenario)] == ["missed"]
    assert all("that wasn't a task" not in str(r.messages) for r in scenario.primary.requests)


async def test_only_within_the_hour(scenario: Scenario) -> None:
    await made_a_vet_task(scenario)
    await scenario.advance(hours=2)
    assert await scenario.say("Erin", "undo that") == [NOTHING_TO_UNDO_TEXT]
    assert "Call the vet" in open_titles(scenario)


async def test_a_task_marked_done_is_opened_again(scenario: Scenario) -> None:
    await made_a_vet_task(scenario)
    [task_id] = [r["id"] for r in scenario.app.db.query("SELECT id FROM tasks WHERE title = ?",
                                                        ("Call the vet",))]  # fmt: skip
    await chat(scenario, "vet's all sorted, phew", "Phew!", ("complete_task", {"task_id": task_id}))
    assert "Call the vet" not in open_titles(scenario)
    replies = await scenario.say("Erin", "no, that's not a task")
    assert 'Taken back: "Call the vet" is open again. Noted as one I got wrong.' in replies
    assert "Call the vet" in open_titles(scenario)


async def test_a_bug_after_a_pass_marks_it(scenario: Scenario) -> None:
    await made_a_vet_task(scenario)
    await scenario.say("Erin", "/bug it made a task out of nothing")
    assert [r["status"] for r in logged(scenario)] == ["missed"]
    assert "Call the vet" in open_titles(scenario)  # a report undoes nothing by itself
    context = json.loads(scenario.app.db.scalar("SELECT context FROM feedback ORDER BY id DESC"))
    assert context["sidecar"][0]["lines"] == ["New task: Call the vet"]


async def test_with_the_mode_off_its_the_usual_agent(scenario: Scenario) -> None:
    scenario.primary.queue_text("Which one?")
    await scenario.say("Erin", "undo that")
    assert scenario.primary.requests[0].tools
