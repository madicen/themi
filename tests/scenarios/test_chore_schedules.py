"""Repeating chores (F6b, feedback bug #5): a schedule, overdue nudges, escalation to both
partners, and an offer to step up after a steady stretch."""

import httpx

from tests.scenarios.harness import Scenario
from themi.core.tasks import Task, TaskBoard

BIRD_CAGE = ["Shake out the top tray", "Refill the water dispenser"]


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def bird_cage(scenario: Scenario, escalate_to: str = "both") -> Task:
    """Erin's plan: twice a week, at least once a week, over two weeks goes to both lists."""
    task = await board(scenario).create(
        scenario.member("Erin"), "Clean the bird cage", "physical", 2, steps=BIRD_CAGE,
        assignee=scenario.member("Erin"),
    )  # fmt: skip
    scenario.primary.queue_tool_call(
        "set_task_schedule",
        {
            "task_id": task.id,
            "repeat": "2 times a week",
            "at_least_every_days": 7,
            "escalate_after_days": 14,
            "escalate_to": escalate_to,
            "missed": "roll",
            "due_before_task": 0,
            "either": False,
        },
    )
    scenario.primary.queue_text("Set up.")
    await scenario.say("Erin", "twice a week, at least weekly, over two weeks it's for both of us")
    return board(scenario).get(task.id)


async def test_a_schedule_is_kept_and_described(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    assert (task.times_per_week, task.minimum_days, task.escalate_days, task.escalate_to) == (
        2,
        7,
        14,
        "both",
    )
    (item,) = [
        i.summary
        for i in scenario.app.services.open_items(scenario.member("Erin"))
        if i.summary.startswith("Task")
    ]
    assert (
        "Twice a week, counted from the last time it was done; overdue after 7 days; "
        "after 14 days it goes to both of you" in item
    )


async def test_done_starts_the_next_round(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    reply = await board(scenario).complete(task.id, scenario.member("Erin"))
    after = board(scenario).get(task.id)
    assert after.status == "open"
    assert after.due_on is not None and (after.due_on - scenario.today()).days == 4  # 3.5, rounded
    assert "Next round: Sun 25 Oct" in reply
    runs = board(scenario).runs(task.id)
    assert [(r.done_by, r.on_time) for r in runs] == [(scenario.member("Erin").id, True)]
    # The next nudge waits for the due date, not straight after "done".
    await scenario.advance(hours=24)
    assert not any("bird cage" in t for t in scenario.inbox("Erin")[-1:])


async def test_overdue_then_escalated_to_both_and_shared(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    await board(scenario).complete(task.id, erin)

    await scenario.advance(hours=24 * 7 + 1)  # past the weekly minimum
    await scenario.run_periodic("tasks.schedules")
    await scenario.run_periodic("tasks.schedules")  # once only
    await scenario.advance(minutes=1)
    overdue = [t for t in scenario.inbox("Erin") if t.startswith("Overdue: Clean the bird cage")]
    assert len(overdue) == 1 and "last done 7 days ago" in overdue[0]
    assert not any("bird cage" in t for t in scenario.inbox("Husband"))

    await scenario.advance(hours=24 * 7)  # past two weeks
    await scenario.run_periodic("tasks.schedules")
    await scenario.advance(minutes=1)
    assert board(scenario).get(task.id).shared
    for name in ("Erin", "Husband"):
        assert any(
            t.startswith("Overdue for both of you: Clean the bird cage")
            for t in scenario.inbox(name)
        )
    # Top of his list too, and he can mark it done.
    first = board(scenario).open_for(husband)[0]
    assert first.id == task.id
    await board(scenario).complete(task.id, husband)
    after = board(scenario).get(task.id)
    assert not after.shared and after.assignee == erin.id  # back to its owner
    assert after.status == "open" and after.due_on is not None
    assert board(scenario).runs(task.id)[-1].done_by == husband.id


async def test_escalation_to_the_owner_keeps_it_theirs(scenario: Scenario) -> None:
    task = await bird_cage(scenario, escalate_to="owner")
    await board(scenario).complete(task.id, scenario.member("Erin"))
    await scenario.advance(hours=24 * 15)
    await scenario.run_periodic("tasks.schedules")
    await scenario.advance(minutes=1)
    assert not board(scenario).get(task.id).shared
    assert not any("bird cage" in t for t in scenario.inbox("Husband"))
    assert any(t.startswith("Overdue: Clean the bird cage") for t in scenario.inbox("Erin"))


async def test_a_steady_stretch_brings_an_offer_to_step_up(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    erin = scenario.member("Erin")
    for _ in range(6):
        await board(scenario).complete(task.id, erin)  # always on time
        await scenario.advance(hours=24 * 3)
    offer = "Step up: Clean the bird cage, 3 times a week instead of 2\nGo ahead, or not now?"
    assert offer in scenario.inbox("Erin")
    assert board(scenario).get(task.id).times_per_week == 2  # nothing changes without a yes

    await scenario.tap("Erin", "Go ahead")
    assert board(scenario).get(task.id).times_per_week == 3


async def test_a_late_run_restarts_the_stretch(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    erin = scenario.member("Erin")
    for _ in range(3):
        await board(scenario).complete(task.id, erin)
        await scenario.advance(hours=24 * 3)
    await scenario.advance(hours=24 * 5)  # late this time
    for _ in range(3):
        await board(scenario).complete(task.id, erin)
        await scenario.advance(hours=24 * 3)
    assert not any("3 times a week instead of 2" in t for t in scenario.inbox("Erin"))


async def test_stopping_a_schedule_and_bad_values(scenario: Scenario) -> None:
    task = await bird_cage(scenario)
    scenario.primary.queue_tool_call(
        "set_task_schedule",
        {"task_id": task.id, "repeat": "", "at_least_every_days": 0,
         "escalate_after_days": 0, "escalate_to": "owner", "missed": "roll",
         "due_before_task": 0, "either": False},
    )  # fmt: skip
    scenario.primary.queue_text("It won't repeat.")
    await scenario.say("Erin", "stop repeating it")
    assert board(scenario).get(task.id).times_per_week is None

    scenario.primary.queue_tool_call(
        "set_task_schedule",
        {"task_id": task.id, "repeat": "2 times a week", "at_least_every_days": 14,
         "escalate_after_days": 7, "escalate_to": "both", "missed": "roll",
         "due_before_task": 0, "either": False},
    )  # fmt: skip
    scenario.primary.queue_text("Hmm.")
    await scenario.say("Erin", "escalate after a week but at least every two")
    assert board(scenario).get(task.id).times_per_week is None  # refused: nothing changed


async def test_the_tasks_page_shows_the_schedule_and_recent_runs(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    from tests.fixtures.web import sign_in

    task = await bird_cage(scenario)
    await board(scenario).complete(task.id, scenario.member("Erin"))
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/tasks")).text
    assert "Twice a week, counted from the last time it was done; overdue after 7 days" in page
    assert "Last done: Wed 21 Oct by Erin" in page


async def test_a_chore_for_either_of_you_isnt_called_overdue(scenario) -> None:  # type: ignore[no-untyped-def]
    """From the reports of 2026-10-26: "Bring bins in", due Wednesday, was listed to the
    model as "shared, overdue" on Monday."""
    from datetime import date

    from themi.core.repeat import parse

    board = scenario.app.services.taskboard
    erin = scenario.member("Erin")
    bins = await board.create(erin, "Bring bins in", "physical", 1, assignee=erin)
    await board.set_schedule(
        bins.id, erin, repeat=parse("every Wednesday", date(2026, 10, 22)), either=True
    )
    (item,) = [i.summary for i in board.open_items(erin) if "Bring bins in" in i.summary]
    assert "overdue" not in item and "either of you" in item
