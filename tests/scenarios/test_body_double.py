"""BD1a: Themi keeps someone company while they work: quietly (Silent Anchor) or in sprints
(Sprint Partner). The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date

from tests.scenarios.harness import Scenario
from themi.core.tasks import Task, TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def session_row(scenario: Scenario) -> dict:
    row = scenario.app.db.one("SELECT * FROM body_double_sessions ORDER BY id DESC LIMIT 1")
    assert row is not None
    return row


async def taxes(scenario: Scenario) -> Task:
    return await board(scenario).create(scenario.member("Erin"), "Do the taxes", "text", 4)


async def start(scenario: Scenario, text: str, **args: object) -> list[str]:
    call = {"mode": "", "minutes": 0, "task_id": 0, "what": "", **args}
    scenario.primary.queue_tool_call("start_body_double", call)  # its message ends the turn
    return await scenario.say("Erin", text)


async def test_a_quiet_hour_ends_with_done_and_the_task_closed(scenario: Scenario) -> None:
    task = await taxes(scenario)
    replies = await start(scenario, "Sit with me for an hour while I do the taxes",
                          mode="quiet", minutes=60, task_id=task.id)  # fmt: skip
    assert replies == ["I'm here. Going quiet until 10 am."]
    assert session_row(scenario)["energy_level"] in ("low", "medium", "high", None)
    await scenario.advance(minutes=30)
    assert await scenario.run_jobs() == []  # nothing until the hour is up
    await scenario.advance(minutes=30)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's the hour. How did it go?"
    assert scenario.last_buttons("Erin") == ["Done", "Not finished", "A bit longer"]
    await scenario.tap("Erin", "Done")
    assert scenario.edits("Erin")[-1]["text"].startswith("Marked done: Do the taxes.")
    assert board(scenario).get(task.id).status == "done"
    row = session_row(scenario)
    assert row["outcome"] == "finished" and row["mode"] == "silent"
    assert scenario.app.services.outbox.pauses.active(scenario.member("Erin")) == []


async def test_a_sprint_of_two_blocks_with_a_break(scenario: Scenario) -> None:
    replies = await scenario.say("Erin", "/bodydouble sprint")
    assert replies == ["Sprint on: 25 minutes, then a 5-minute break. I'll say when."]
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's 25 minutes. Break for 5?"
    assert scenario.last_buttons("Erin") == ["Break", "Keep going", "Stop here"]
    await scenario.tap("Erin", "Break")
    assert scenario.edits("Erin")[-1]["text"] == "Break on, back at 9:30 am."
    await scenario.advance(minutes=5)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "Break's done whenever you are."
    assert scenario.last_buttons("Erin") == ["Carry on", "A bit longer", "Stop here"]
    await scenario.tap("Erin", "Carry on")
    assert scenario.edits("Erin")[-1]["text"] == "Another 25 minutes, then. I'll say when."
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Stop here")
    assert scenario.edits("Erin")[-1]["text"] == "Stopping there."
    row = session_row(scenario)
    assert (row["outcome"], row["blocks_done"]) == ("stopped", 2)


async def test_a_sprint_left_unanswered_ends_quietly(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble sprint")
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    before = len(scenario.inbox("Erin"))
    await scenario.advance(minutes=30)
    await scenario.run_jobs()
    assert session_row(scenario)["ended_at"] is None  # still waiting, still paused
    await scenario.advance(minutes=31)
    await scenario.run_jobs()
    assert session_row(scenario)["outcome"] == "left"
    assert len(scenario.inbox("Erin")) == before  # quietly: nothing said
    assert scenario.edits("Erin")[-1]["text"] == "That's 25 minutes. Break for 5?"
    assert "reply_markup" not in scenario.edits("Erin")[-1] or not (
        scenario.edits("Erin")[-1]["reply_markup"] or {}
    ).get("inline_keyboard")


async def test_a_nudge_waits_for_the_session_then_comes(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble quiet 30")
    erin = scenario.member("Erin")
    await board(scenario).create(erin, "Book the dentist", "errand", 1, date(2026, 10, 21))
    await scenario.advance(minutes=20)
    assert not any("Book the dentist" in t for t in scenario.inbox("Erin"))
    await scenario.advance(minutes=10)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Not finished")
    assert scenario.edits("Erin")[-1]["text"] == "That's fine. It'll keep for another time."
    await scenario.advance(minutes=1)
    assert any("Book the dentist" in t for t in scenario.inbox("Erin"))


async def test_a_bigger_tasks_nudge_offers_a_body_double(scenario: Scenario) -> None:
    task = await taxes(scenario)
    await board(scenario).prompt(task)
    await scenario.advance(minutes=1)
    assert scenario.last_buttons("Erin") == ["Done", "Later", "Body double"]
    await scenario.tap("Erin", "Body double")
    assert scenario.edits("Erin")[-1]["text"] == "I'm here. Going quiet until you say you're done."
    assert session_row(scenario)["task_id"] == task.id


async def test_a_break_ends_the_session(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble")
    await scenario.say("Erin", "/break 10")
    assert session_row(scenario)["outcome"] == "stopped"


async def test_im_done_ends_it_and_marks_the_task(scenario: Scenario) -> None:
    task = await taxes(scenario)
    await start(scenario, "pomodoro the taxes", mode="sprint", task_id=task.id)
    scenario.primary.queue_tool_call("end_body_double", {"finished": True})
    scenario.primary.queue_text("Well done.")  # the done line opens the reply
    replies = await scenario.say("Erin", "I'm done!")
    assert replies[0].startswith("Marked done: Do the taxes.")
    assert board(scenario).get(task.id).status == "done"
    assert session_row(scenario)["outcome"] == "finished"


async def test_stop_here_then_its_done_after_all(scenario: Scenario) -> None:
    task = await taxes(scenario)
    await start(scenario, "pomodoro the taxes", mode="sprint", task_id=task.id)
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Stop here")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Stopping there. If Do the taxes is done, tap below."
    )
    await scenario.tap("Erin", "It's done")
    assert board(scenario).get(task.id).status == "done"
    assert session_row(scenario)["outcome"] == "finished"


async def test_the_sprint_lengths_are_theirs(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, sprint_work_minutes=50,
                                       sprint_break_minutes=10)  # fmt: skip
    replies = await scenario.say("Erin", "/bodydouble pomodoro")
    assert replies == ["Sprint on: 50 minutes, then a 10-minute break. I'll say when."]
