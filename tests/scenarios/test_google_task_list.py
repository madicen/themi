"""GT1b: Themi's tasks on a "Themi" list in each person's Google Tasks, kept apart from the
inbox. Done in either place is done in both; anything else on that list is a new item. The
clock starts on Wednesday 21 October 2026, 09:00 (Los Angeles)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gtasks_api import FakeGtasks
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

FRI = date(2026, 10, 23)


@pytest.fixture
async def tasks_linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gtasks: FakeGtasks, site: httpx.AsyncClient
) -> FakeGtasks:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gtasks


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def run(scenario: Scenario) -> object:
    handled = await scenario.run_periodic("google_tasks.inbox")
    await scenario.app.outbox.flush()
    return handled


async def task(scenario: Scenario, title: str, who: str = "Erin", **kw: object) -> Task:
    member = scenario.member(who)
    return await board(scenario).create(
        member,
        title,
        "errand",
        2,
        assignee=member,
        nudge=False,
        **kw,  # type: ignore[arg-type]
    )


async def test_their_open_tasks_go_on_a_themi_list(
    scenario: Scenario, tasks_linked: FakeGtasks
) -> None:
    await task(scenario, "Call the vet", due_on=FRI)
    await task(scenario, "Buy stamps")
    chore = await task(scenario, "Water the plants")
    await board(scenario).set_schedule(
        chore.id, scenario.member("Erin"), repeat=parse("every Tuesday", FRI)
    )
    await task(scenario, "Fix the gate", who="Husband")  # his, and he has no account linked
    await run(scenario)
    assert tasks_linked.has_list(ERIN, "Themi")
    assert sorted(tasks_linked.titles(ERIN, "Themi")) == ["Buy stamps", "Call the vet"]
    assert tasks_linked.task(ERIN, "Themi", "Call the vet")["due"] == "2026-10-23T00:00:00.000Z"
    assert tasks_linked.titles(ERIN) == []  # never on My Tasks
    assert scenario.primary.requests == []  # Themi's own aren't new items

    await run(scenario)
    assert sorted(tasks_linked.titles(ERIN, "Themi")) == ["Buy stamps", "Call the vet"]  # once


async def test_an_existing_themi_list_is_used(scenario: Scenario, tasks_linked: FakeGtasks) -> None:
    tasks_linked.add(ERIN, "Old note", list_title="Themi", done=True)  # the list is there
    await task(scenario, "Call the vet")
    await run(scenario)
    lists = [x for x in tasks_linked.accounts[ERIN].values() if x["title"] == "Themi"]
    assert len(lists) == 1 and "Call the vet" in tasks_linked.titles(ERIN, "Themi")


async def test_done_in_google_is_done_in_themi(
    scenario: Scenario, tasks_linked: FakeGtasks
) -> None:
    vet = await task(scenario, "Call the vet")
    await run(scenario)
    tasks_linked.complete(ERIN, "Themi", "Call the vet")  # "Hey Google, mark ... done"
    await run(scenario)
    assert board(scenario).get(vet.id).status == "done"
    assert tasks_linked.titles(ERIN, "Themi") == []
    assert scenario.primary.requests == []  # not taken as a new item


async def test_done_cancelled_and_changed_in_themi(
    scenario: Scenario, tasks_linked: FakeGtasks
) -> None:
    vet = await task(scenario, "Call the vet")
    stamps = await task(scenario, "Buy stamps")
    gate = await task(scenario, "Fix the gate")
    await run(scenario)
    erin = scenario.member("Erin")
    await board(scenario).complete(vet.id, erin)
    await board(scenario).cancel(stamps.id, erin)
    await board(scenario).update(gate.id, erin, title="Fix the side gate")
    await board(scenario).reschedule(gate.id, FRI)
    await run(scenario)
    assert tasks_linked.titles(ERIN, "Themi", done=True) == ["Call the vet"]
    assert tasks_linked.titles(ERIN, "Themi") == ["Fix the side gate"]
    assert tasks_linked.task(ERIN, "Themi", "Fix the side gate")["due"].startswith("2026-10-23")

    await board(scenario).reassign(gate.id, scenario.member("Husband"))  # not hers any more
    await run(scenario)
    assert tasks_linked.titles(ERIN, "Themi") == []


async def test_deleted_in_google_stays_off(scenario: Scenario, tasks_linked: FakeGtasks) -> None:
    await task(scenario, "Call the vet")
    await run(scenario)
    themi = next(x for x in tasks_linked.accounts[ERIN].values() if x["title"] == "Themi")
    themi["tasks"].clear()
    await run(scenario)
    assert tasks_linked.titles(ERIN, "Themi") == []


async def test_something_else_on_the_themi_list_is_a_new_item(
    scenario: Scenario, tasks_linked: FakeGtasks
) -> None:
    await task(scenario, "Call the vet")
    await run(scenario)
    tasks_linked.add(ERIN, "Book the dentist", list_title="Themi")  # added there by hand
    scenario.primary.queue_text("Noted the dentist.")
    assert await run(scenario) == 1
    assert 'add "Book the dentist" to Google Tasks' in scenario.primary.requests[0].messages[0].text
    assert tasks_linked.titles(ERIN, "Themi") == ["Call the vet"]  # handled, and removed
