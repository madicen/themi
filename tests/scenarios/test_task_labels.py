"""Every task nudge opens with a label saying when it's due, or that it's a check-in
(bug #9: Erin's "Due today:" and "Check-in:" rules, built in)."""

from datetime import date

from tests.scenarios.harness import Scenario
from themi.core.tasks import Task, TaskBoard, _label


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def nudge_for(scenario: Scenario, title: str, due: date | None = None, **kw) -> str:
    """The nudge for a new task, sent now (a new task itself waits until it's due)."""
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        kw.pop("by", erin), title, "physical", 1, due, assignee=erin, nudge=False, **kw
    )
    await board(scenario).prompt(task)
    return scenario.inbox("Erin")[-1]


async def test_a_task_without_a_date_is_a_to_do(scenario: Scenario) -> None:
    assert await nudge_for(scenario, "Water the plants") == (
        "To do: Water the plants, whenever it suits. Done already, or later?"
    )


async def test_the_label_says_when_its_due(scenario: Scenario) -> None:
    # The clock starts on Wednesday 21 October. A nudge only goes out once a task is due
    # (bug #14), so it says "Due today:" or, once past, "Was due ...".
    assert (await nudge_for(scenario, "Book the dentist", date(2026, 10, 21))).startswith(
        "Due today: Book the dentist."
    )
    assert (await nudge_for(scenario, "Return the books", date(2026, 10, 20))).startswith(
        "Was due yesterday: Return the books."
    )
    assert (await nudge_for(scenario, "Renew the passport", date(2026, 10, 8))).startswith(
        "Was due 8 Oct: Renew the passport."
    )
    wed = date(2026, 10, 21)
    for due, label in [
        (date(2026, 10, 22), "Due tomorrow"),
        (date(2026, 10, 25), "Due Sunday"),
        (date(2026, 11, 8), "Due 8 Nov"),
        (date(2026, 10, 17), "Was due Saturday"),
    ]:
        task = Task(1, "x", "errand", 1, None, None, "", "open", due)
        assert _label(task, wed) == label


async def test_a_task_from_someone_else_says_who_after_the_label(scenario: Scenario) -> None:
    text = await nudge_for(
        scenario, "Call the plumber", date(2026, 10, 21), by=scenario.member("Husband")
    )
    assert text == (
        "Due today: Call the plumber (Husband added this for you). Done already, or later?"
    )
    undated = await nudge_for(scenario, "Fix the gate", by=scenario.member("Husband"))
    assert undated == (
        "To do: Fix the gate (Husband added this for you), whenever it suits. "
        "Done already, or later?"
    )


async def test_a_check_in_is_labelled_as_one(scenario: Scenario) -> None:
    text = await nudge_for(scenario, "Go for a run", date(2026, 10, 21), check_in=True)
    assert text == "Check-in: Go for a run. Done already, or later?"


async def test_the_model_can_ask_for_a_check_in(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "Go for a run",
            "kind": "physical",
            "effort": 2,
            "due_date": "",
            "assign_to": "me",
            "steps": [],
            "check_in": True,
            "due_time": "",
        },
    )
    scenario.primary.queue_text("I'll check in on it.")
    await scenario.say("Erin", "Check in with me about running")
    (task,) = [t for t in board(scenario).open_for(scenario.member("Erin")) if "run" in t.title]
    assert task.check_in
