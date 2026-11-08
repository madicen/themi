"""P8a: each refusal from a naming check is counted by kind, and what follows settles it:
the same task done within ten minutes (the refusal was wrong) or another task (right)."""

from datetime import timedelta

from tests.scenarios.harness import Scenario
from themi import clock
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.naming import NamingRefusals, report
from themi.standard.tasks import Task, TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


def refusals(scenario: Scenario) -> list[dict]:
    return scenario.app.services.store.db.query(
        "SELECT tool, kind, task_id, outcome FROM naming_refusals ORDER BY id"
    )


async def task(scenario: Scenario, title: str) -> Task:
    erin = scenario.member("Erin")
    return await board(scenario).create(erin, title, "physical", 1, assignee=erin)


async def something_else_said(scenario: Scenario) -> None:
    await scenario.app.services.outbox.send(
        scenario.member("Erin"), "Reminder set for tomorrow at 9 am.", priority=Priority.REPLY
    )


async def done(scenario: Scenario, task: Task, said: str) -> None:
    scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", said)


async def test_a_refusal_then_the_same_task_done_counts_as_wrong(scenario: Scenario) -> None:
    run = await task(scenario, "Go for a run")
    await something_else_said(scenario)
    await done(scenario, run, "Got my 5k in")
    assert board(scenario).get(run.id).status == "open"
    assert refusals(scenario) == [
        {"tool": "complete_task", "kind": "not_named", "task_id": run.id, "outcome": None}
    ]

    await scenario.advance(minutes=3)
    await done(scenario, run, "Yes, the run")
    assert refusals(scenario)[0]["outcome"] == "wrong"


async def test_named_another_then_that_one_done_counts_as_right(scenario: Scenario) -> None:
    bins = await task(scenario, "Bring bins in")
    parents = await task(scenario, "Contact Sam's parents about babysitting")
    await done(scenario, bins, "We contacted Sam's parents")
    assert refusals(scenario) == [
        {"tool": "complete_task", "kind": "names_other", "task_id": bins.id, "outcome": None}
    ]

    await done(scenario, parents, "We contacted Sam's parents")
    assert board(scenario).get(parents.id).status == "done"
    assert refusals(scenario)[0]["outcome"] == "right"


async def test_a_done_after_ten_minutes_settles_nothing(scenario: Scenario) -> None:
    run = await task(scenario, "Go for a run")
    await something_else_said(scenario)
    await done(scenario, run, "jogged this morning")
    await scenario.advance(minutes=11)
    await done(scenario, run, "The run, I mean")
    assert board(scenario).get(run.id).status == "done"
    assert refusals(scenario)[0]["outcome"] is None


async def test_a_follow_up_refusal_is_counted(scenario: Scenario) -> None:
    cage = await task(scenario, "Clean the bird cage")
    scenario.primary.queue_tool_call(
        "add_follow_up", {"after_task_id": cage.id, "title": "Refill the water", "steps": []}
    )
    scenario.primary.queue_text("Saved.")
    await scenario.say("Erin", "After that, remind me to refill the water")
    assert refusals(scenario) == [
        {"tool": "add_follow_up", "kind": "not_named", "task_id": cage.id, "outcome": None}
    ]


async def test_feedback_shows_the_weeks_counts(scenario: Scenario) -> None:
    run = await task(scenario, "Go for a run")
    bins = await task(scenario, "Bring bins in")
    await something_else_said(scenario)
    await done(scenario, run, "Got my 5k in")
    await done(scenario, bins, "Bins are in")  # another task: the refusal was right
    clock.advance(timedelta(weeks=1, minutes=1))
    await something_else_said(scenario)
    await done(scenario, run, "Hit the pavement")

    weeks = NamingRefusals(scenario.app.services.store.db).weeks()
    assert [(w.refused, w.wrong, w.right) for w in weeks[:2]] == [(1, 0, 0), (1, 0, 1)]
    assert report(weeks, "America/Los_Angeles").splitlines()[-2:] == [
        "- Week to Wed 28 Oct: 1 refused (1 not named, 0 named another); 0 wrong, 0 right, "
        "1 with nothing after.",
        "- Week to Wed 21 Oct: 1 refused (1 not named, 0 named another); 0 wrong, 1 right, "
        "0 with nothing after.",
    ]
    assert report(NamingRefusals(scenario.app.services.store.db).weeks(0), "UTC") == ""
