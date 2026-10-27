"""Anchored chore schedules (F7): fixed days and times, missed rounds, deadlines tied to
another chore, and a read-back built from what was stored."""

from datetime import date

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core.tasks import Task, TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def chore(scenario: Scenario, title: str) -> Task:
    return await board(scenario).create(
        scenario.member("Erin"), title, "physical", 1, assignee=scenario.member("Erin")
    )


async def schedule(
    scenario: Scenario, task: Task, repeat: str, *, missed: str = "roll", before: int = 0
) -> list[str]:
    scenario.primary.queue_tool_call(
        "set_task_schedule",
        {
            "task_id": task.id,
            "repeat": repeat,
            "at_least_every_days": 0,
            "escalate_after_days": 0,
            "escalate_to": "owner",
            "missed": missed,
            "due_before_task": before,
            "either": False,
        },
    )
    scenario.primary.queue_text("All set.")
    return await scenario.say("Erin", f"{task.title}: {repeat}")


def last_tool_result(scenario: Scenario) -> ToolResult:
    return [
        block
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def test_a_weekly_chore_is_due_on_its_day_and_read_back(scenario: Scenario) -> None:
    bins = await chore(scenario, "Take out the bins")
    replies = await schedule(scenario, bins, "every Tuesday at 6pm")
    assert replies[0] == "Saved: Every Tuesday at 6 pm. Next: Tue 27 Oct, 6 pm."
    assert "read back to them already" in last_tool_result(scenario).content
    # Idea #8: anything they asked for that the read-back doesn't show is said, and noted.
    assert "remember_fact" in last_tool_result(scenario).content
    assert board(scenario).get(bins.id).due_on == date(2026, 10, 27)

    await scenario.advance(hours=24 * 6 + 8, minutes=59)  # Tue 17:59
    assert not any("bins" in t for t in scenario.inbox("Erin")[1:])
    await scenario.advance(minutes=2)  # Tue 18:01
    assert any(t.startswith("Due today: Take out the bins.") for t in scenario.inbox("Erin"))

    reply = await board(scenario).complete(bins.id, scenario.member("Erin"))
    assert "Next round: Tue 03 Nov" in reply
    assert board(scenario).get(bins.id).due_on == date(2026, 11, 3)


async def test_done_early_counts_for_this_weeks_round(scenario: Scenario) -> None:
    bins = await chore(scenario, "Take out the bins")
    await schedule(scenario, bins, "every Tuesday")
    await scenario.advance(hours=24 * 5)  # Monday
    await board(scenario).complete(bins.id, scenario.member("Erin"))
    assert board(scenario).get(bins.id).due_on == date(2026, 11, 3)


async def test_a_missed_round_rolls_on_by_default(scenario: Scenario) -> None:
    bins = await chore(scenario, "Take out the bins")
    await schedule(scenario, bins, "every Tuesday")
    await scenario.advance(hours=24 * 7)  # Wednesday after
    await scenario.run_periodic("tasks.schedules")
    assert board(scenario).get(bins.id).due_on == date(2026, 11, 3)
    (run,) = board(scenario).runs(bins.id)
    assert run.missed and not run.on_time and run.done_by is None


async def test_a_missed_round_can_be_caught_up(scenario: Scenario) -> None:
    bins = await chore(scenario, "Take out the bins")
    await schedule(scenario, bins, "every Tuesday", missed="catch_up")
    await scenario.advance(hours=24 * 7)
    await scenario.run_periodic("tasks.schedules")
    assert board(scenario).get(bins.id).due_on == date(2026, 10, 27)  # still owed
    await board(scenario).complete(bins.id, scenario.member("Erin"))
    assert board(scenario).get(bins.id).due_on == date(2026, 11, 3)


async def test_a_deadline_tied_to_another_chore(scenario: Scenario) -> None:
    bins = await chore(scenario, "Take out the bins")
    await schedule(scenario, bins, "every Tuesday")
    cardboard = await chore(scenario, "Process the cardboard")
    replies = await schedule(scenario, cardboard, "", before=bins.id)
    assert replies[0] == (
        "Saved: Due the day before Take out the bins (Every Tuesday). Next: Mon 26 Oct."
    )
    assert board(scenario).get(cardboard.id).due_on == date(2026, 10, 26)

    await scenario.advance(hours=24 * 5)  # Monday
    await board(scenario).complete(cardboard.id, scenario.member("Erin"))
    assert board(scenario).get(cardboard.id).due_on == date(2026, 11, 2)  # next week's bins


async def test_a_date_only_schedule_set_on_its_day_is_due_today(scenario: Scenario) -> None:
    plants = await chore(scenario, "Water the plants")
    await schedule(scenario, plants, "every other Wednesday")
    assert board(scenario).get(plants.id).due_on == date(2026, 10, 21)


async def test_an_unclear_phrase_changes_nothing(scenario: Scenario) -> None:
    bins = await chore(scenario, "Take out the bins")
    replies = await schedule(scenario, bins, "whenever it feels right")
    result = last_tool_result(scenario)
    assert result.is_error and "every Tuesday at 6pm" in result.content
    assert board(scenario).get(bins.id).repeat is None
    assert replies == ["All set."] or replies[0] != "Saved"  # no read-back


async def test_the_tasks_page_shows_the_next_dates(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    bins = await chore(scenario, "Take out the bins")
    await schedule(scenario, bins, "every Tuesday at 6pm")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/tasks")).text
    assert "Every Tuesday at 6 pm" in page
    assert "Next: Tue 27 Oct, Tue 03 Nov, Tue 10 Nov" in page


async def test_a_new_chore_isnt_nudged_before_its_first_day(scenario: Scenario) -> None:
    """Bug #10: running, set up on Sunday for Tuesday afternoons, was asked about on Monday
    morning. The nudge queued when the task was made stayed, since its date didn't move."""
    run = await board(scenario).create(
        scenario.member("Erin"),
        "Go for a run",
        "physical",
        2,
        date(2026, 10, 27),
        interactive=True,
        assignee=scenario.member("Erin"),
    )
    await schedule(scenario, run, "every Tuesday afternoon")
    before = len(scenario.inbox("Erin"))
    await scenario.advance(hours=24 * 6 + 4, minutes=59)  # Tue 13:59
    assert not any("run" in t for t in scenario.inbox("Erin")[before:])
    await scenario.advance(minutes=2)  # Tue 14:01
    assert [t for t in scenario.inbox("Erin")[before:] if "run" in t] == [
        "Due today: Go for a run. Done already, or later?"
    ]


async def test_a_new_floating_chore_waits_for_its_due_day(scenario: Scenario) -> None:
    cage = await board(scenario).create(
        scenario.member("Erin"),
        "Clean the bird cage",
        "physical",
        2,
        date(2026, 10, 23),
        interactive=True,
        assignee=scenario.member("Erin"),
    )
    await schedule(scenario, cage, "twice a week")
    before = len(scenario.inbox("Erin"))
    for _ in range(24 + 14):  # hour by hour, to Thu 23:00
        await scenario.advance(hours=1)
    assert not any("bird cage" in t for t in scenario.inbox("Erin")[before:])
    for _ in range(10):  # Fri 09:00
        await scenario.advance(hours=1)
    assert any(
        t.startswith("Due today: Clean the bird cage") for t in scenario.inbox("Erin")[before:]
    )


async def test_a_course_ends_after_its_last_round(scenario: Scenario) -> None:
    """C2a: "Mimi pill every 2 days until 25 Oct". The clock starts on Wednesday 21 October."""
    pill = await chore(scenario, "Mimi pill")
    replies = await schedule(scenario, pill, "every 2 days until 25 Oct")
    assert "Saved: Every other day, until Sun 25 Oct. Next: Wed 21 Oct." in replies
    erin = scenario.member("Erin")
    for day in (21, 23):
        assert board(scenario).get(pill.id).due_on == date(2026, 10, day)
        await board(scenario).complete(pill.id, erin)
        await scenario.advance(hours=48)
    assert board(scenario).get(pill.id).due_on == date(2026, 10, 25)
    reply = await board(scenario).complete(pill.id, erin)
    assert "That was the last one." in reply
    assert board(scenario).get(pill.id).status == "done"


async def test_a_course_whose_last_round_passes_is_over(scenario: Scenario) -> None:
    pill = await chore(scenario, "Mimi pill")
    await schedule(scenario, pill, "every 2 days until 23 Oct")
    await board(scenario).complete(pill.id, scenario.member("Erin"))  # the 21st
    await scenario.advance(hours=24 * 3)  # the 23rd goes by undone
    await scenario.run_periodic("tasks.schedules")
    assert board(scenario).get(pill.id).status == "done"
