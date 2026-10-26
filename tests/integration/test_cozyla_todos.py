"""C1b: Themi's one-off tasks and a Cozyla to-do list, kept in step both ways."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

LA = ZoneInfo("America/Los_Angeles")


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def sync(scenario: Scenario) -> Any:
    return await scenario.run_periodic("cozyla.sync")


def tasks(scenario: Scenario, status: str = "open") -> dict[str, Task]:
    rows = scenario.app.db.query("SELECT id FROM tasks WHERE status = ? ORDER BY id", (status,))
    return {(t := board(scenario).get(r["id"])).title: t for r in rows}


def wall(fake: FakeCozyla, scenario: Scenario) -> dict[str, dict[str, Any]]:
    return {t["todoTitle"]: t for t in fake.in_list(scenario.cozyla_list)}


def writes_since(fake: FakeCozyla, start: int) -> list[str]:
    """The changing calls Themi made to Cozyla since call number `start`."""
    changing = {"create", "update", "checkTodo", "delete"}
    return [p for p in fake.paths()[start:] if p.rsplit("/", 1)[-1] in changing]


async def add_task(scenario: Scenario, title: str, who: str = "Erin", **kw: Any) -> Task:
    member = scenario.member(who)
    return await board(scenario).create(member, title, "errand", 2, assignee=member, **kw)


async def test_first_sync_links_matches_brings_in_the_rest_and_sends_themis(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    family = scenario.cozyla_list
    fake_cozyla.add_todo(family, "Call the vet")  # also open in Themi
    fake_cozyla.add_todo(family, "Fix the gate", assignee="m-husband")
    fake_cozyla.add_todo(family, "Sort the photos")  # nobody's yet
    fake_cozyla.add_todo(family, "Wrap presents", done=True)  # history
    await add_task(scenario, "call the vet")
    await add_task(scenario, "Buy stamps", due_on=date(2026, 10, 27))

    await sync(scenario)
    assert set(tasks(scenario)) == {"call the vet", "Fix the gate", "Sort the photos", "Buy stamps"}
    gate = tasks(scenario)["Fix the gate"]
    assert gate.assignee == scenario.member("Husband").id and gate.created_by is None
    assert "Wrap presents" not in tasks(scenario, "done")  # left alone
    on_wall = wall(fake_cozyla, scenario)
    assert set(on_wall) == {
        "Call the vet",
        "Fix the gate",
        "Sort the photos",
        "Wrap presents",
        "Buy stamps",
    }
    stamps = on_wall["Buy stamps"]
    assert stamps["assignMemberUid"] == "m-erin"
    due = datetime.fromtimestamp(stamps["dueDateTime"] / 1000, LA)
    assert (due.date(), due.hour) == (date(2026, 10, 27), 0)  # the start of that day, locally
    # His to-do is nudged, gently (low priority, so a long list trickles out); the
    # unassigned one comes in quietly.
    nudges = scenario.app.db.query(
        "SELECT member_id, priority, text FROM outbox WHERE kind = 'task'"
    )
    gate_nudges = [n for n in nudges if "Fix the gate" in n["text"]]
    assert [(n["member_id"], n["priority"]) for n in gate_nudges] == [
        (scenario.member("Husband").id, "low")
    ]
    assert not any("Sort the photos" in n["text"] for n in nudges)

    calls = len(fake_cozyla.calls)
    await sync(scenario)
    assert writes_since(fake_cozyla, calls) == []
    assert len(tasks(scenario)) == 4  # nothing doubled


async def test_a_new_to_do_on_the_wall_becomes_a_task_and_is_nudged(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await sync(scenario)
    fake_cozyla.add_todo(scenario.cozyla_list, "Book the dentist", assignee="m-erin")
    await sync(scenario)
    dentist = tasks(scenario)["Book the dentist"]
    assert dentist.assignee == scenario.member("Erin").id and dentist.created_by is None
    await scenario.advance(hours=12)
    (nudge,) = [t for t in scenario.inbox("Erin") if "Book the dentist" in t]
    assert nudge.startswith("To do: Book the dentist, whenever")  # nobody named as adding it


async def test_ticking_off_deleting_and_editing_on_the_wall_reach_themi(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    vet = await add_task(scenario, "Call the vet")
    gate = await add_task(scenario, "Fix the gate")
    stamps = await add_task(scenario, "Buy stamps")
    await sync(scenario)
    ids = {t["todoTitle"]: t["todoId"] for t in fake_cozyla.in_list(scenario.cozyla_list)}

    fake_cozyla.tick(ids["Call the vet"])
    fake_cozyla.delete(ids["Fix the gate"])
    new_due = datetime(2026, 10, 30, tzinfo=LA)
    fake_cozyla.edit(
        ids["Buy stamps"],
        todoTitle="Buy stamps and envelopes",
        dueDateTime=int(new_due.timestamp() * 1000),
    )
    await sync(scenario)

    assert board(scenario).get(vet.id).status == "done"
    assert board(scenario).get(gate.id).status == "cancelled"
    changed = board(scenario).get(stamps.id)
    assert changed.title == "Buy stamps and envelopes" and changed.due_on == date(2026, 10, 30)
    calls = len(fake_cozyla.calls)
    await sync(scenario)
    assert writes_since(fake_cozyla, calls) == []  # nothing echoed back


async def test_themis_changes_go_to_the_wall(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    vet = await add_task(scenario, "Call the vet")
    gate = await add_task(scenario, "Fix the gate")
    stamps = await add_task(scenario, "Buy stamps")
    await sync(scenario)
    await board(scenario).complete(vet.id, scenario.member("Erin"))
    await board(scenario).cancel(gate.id, scenario.member("Erin"))
    await board(scenario).reschedule(stamps.id, date(2026, 11, 2))
    await board(scenario).update(stamps.id, scenario.member("Erin"), title="Buy forever stamps")
    await sync(scenario)

    on_wall = wall(fake_cozyla, scenario)
    assert on_wall["Call the vet"]["completeStatus"] == 1
    assert "Fix the gate" not in on_wall
    due = datetime.fromtimestamp(on_wall["Buy forever stamps"]["dueDateTime"] / 1000, LA)
    assert due.date() == date(2026, 11, 2)


async def test_repeating_chores_stay_off_the_list(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    chore = await add_task(scenario, "Vacuum upstairs")
    weekly = parse("every saturday", scenario.today())
    await board(scenario).set_schedule(chore.id, scenario.member("Erin"), repeat=weekly)
    stamps = await add_task(scenario, "Buy stamps")
    await sync(scenario)
    assert set(wall(fake_cozyla, scenario)) == {"Buy stamps"}

    # Already on the wall, then made a repeating chore: it comes off.
    await board(scenario).set_schedule(stamps.id, scenario.member("Erin"), repeat=weekly)
    await sync(scenario)
    assert wall(fake_cozyla, scenario) == {}
    assert scenario.app.db.query("SELECT * FROM cozyla_links") == []


async def test_when_both_sides_changed_a_task_themis_change_wins(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    vet = await add_task(scenario, "Call the vet")
    gate = await add_task(scenario, "Fix the gate")
    await sync(scenario)
    ids = {t["todoTitle"]: t["todoId"] for t in fake_cozyla.in_list(scenario.cozyla_list)}

    await board(scenario).reschedule(vet.id, date(2026, 11, 1))  # Themi: a new date
    fake_cozyla.tick(ids["Call the vet"])  # the wall: done
    await board(scenario).update(gate.id, scenario.member("Erin"), title="Fix the side gate")
    fake_cozyla.delete(ids["Fix the gate"])  # the wall: deleted
    await sync(scenario)

    assert board(scenario).get(vet.id).status == "open"
    assert wall(fake_cozyla, scenario)["Call the vet"]["completeStatus"] == 0  # reopened
    assert board(scenario).get(gate.id).status == "open"
    assert "Fix the side gate" in wall(fake_cozyla, scenario)  # put back


async def test_an_outage_changes_nothing_and_the_next_sync_catches_up(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    vet = await add_task(scenario, "Call the vet")
    await sync(scenario)
    (todo,) = fake_cozyla.in_list(scenario.cozyla_list)
    fake_cozyla.tick(todo["todoId"])
    fake_cozyla.fail("todosInfo/list", code=500)
    await sync(scenario)
    assert board(scenario).get(vet.id).status == "open"

    calls = len(fake_cozyla.calls)
    await sync(scenario)  # backing off: not asked yet
    assert len(fake_cozyla.calls) == calls
    clock.advance(timedelta(minutes=1))
    await sync(scenario)
    assert board(scenario).get(vet.id).status == "done"


async def test_a_failed_write_is_retried_later(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    fake_cozyla.fail("todosInfo/create", code=500)
    await sync(scenario)
    await add_task(scenario, "Call the vet")
    await sync(scenario)
    assert wall(fake_cozyla, scenario) == {}
    clock.advance(timedelta(minutes=1))
    await sync(scenario)
    assert set(wall(fake_cozyla, scenario)) == {"Call the vet"}


async def test_a_missing_list_waits_and_says_why(
    scenario: Scenario, fake_cozyla: FakeCozyla, caplog: Any
) -> None:
    fake_cozyla.lists.clear()
    await add_task(scenario, "Call the vet")
    await sync(scenario)
    assert "no to-do list called 'Family'" in caplog.text
    assert fake_cozyla.todos == {}
