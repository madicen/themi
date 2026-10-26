"""C2d: only so many chores on someone's chart at a time (Erin's ideas #16 and #17)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi.accounts import InvalidValue
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

WED = date(2026, 10, 21)  # the scenario clock's first day


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def sync(scenario: Scenario) -> Any:
    return await scenario.run_periodic("cozyla.chores")


def limit(scenario: Scenario, name: str, count: int) -> None:
    member = scenario.member(name)
    scenario.app.store.update_settings(member, member.id, chart_limit=count)


async def chore(scenario: Scenario, title: str, phrase: str, who: str = "Erin", **kw: Any) -> Task:
    member = scenario.member(who)
    task = await board(scenario).create(member, title, "physical", 2, assignee=member)
    return await board(scenario).set_schedule(
        task.id, member, repeat=parse(phrase, board(scenario)._today()), **kw
    )


async def one_off(scenario: Scenario, title: str, due: date, who: str = "Erin") -> Task:
    member = scenario.member(who)
    task = await board(scenario).create(member, title, "physical", 2, due, assignee=member)
    return await board(scenario).put_on_chart(task.id, member)


def on_wall(fake: FakeCozyla) -> dict[str, list[str]]:
    """Each wall chore's name, with whose chart it's on."""
    return {
        c["choreName"]: sorted(r["memberUid"] for r in c["memberRefs"])
        for c in fake.chores.values()
    }


def queued_nudges(scenario: Scenario, name: str) -> list[str]:
    rows = scenario.app.db.query(
        "SELECT text FROM outbox WHERE status = 'queued' AND member_id = ? AND kind = 'task'",
        (scenario.member(name).id,),
    )
    return [r["text"] for r in rows]


async def test_one_at_a_time_most_overdue_first(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    limit(scenario, "Erin", 1)
    cage = await one_off(scenario, "Clean the bird cage", WED - timedelta(days=2))
    kitchen = await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Clean upstairs", "every Thursday")
    pill = await chore(scenario, "Mimi pill", "every day", either=True)
    scenario.app.db.execute("UPDATE tasks SET importance = 'high' WHERE id = ?", (pill.id,))
    await chore(scenario, "Mow the lawn", "every Wednesday", who="Husband")
    await sync(scenario)

    assert on_wall(fake_cozyla) == {
        "Clean the bird cage": ["m-erin"],  # the most overdue
        "Mimi pill": ["m-erin", "m-husband"],  # important: always shows, doesn't count
        "Mow the lawn": ["m-husband"],  # no limit for him
    }
    cage_chore = fake_cozyla.chore_named("Clean the bird cage")
    assert (cage_chore["repeats"], cage_chore["startDay"]) == (False, WED.isoformat())

    fake_cozyla.tick_chore(cage_chore["choreUid"], "m-erin", WED)  # done: the next comes up
    await sync(scenario)
    assert board(scenario).get(cage.id).status == "done"
    up = fake_cozyla.chore_named("Clean the kitchen")
    assert (up["repeats"], up["startDay"]) == (False, WED.isoformat())  # a one-off for today
    assert "Clean upstairs" not in on_wall(fake_cozyla)  # not due until tomorrow

    del fake_cozyla.chores[up["choreUid"]]  # deleted on the wall: done too
    await sync(scenario)
    runs = scenario.app.db.query("SELECT done_by FROM task_runs WHERE task_id = ?", (kitchen.id,))
    assert [r["done_by"] for r in runs] == [scenario.member("Erin").id]
    assert board(scenario).get(kitchen.id).due_on == WED + timedelta(days=7)
    assert set(on_wall(fake_cozyla)) == {"Clean the bird cage", "Mimi pill", "Mow the lawn"}

    await scenario.advance(hours=24)
    await sync(scenario)
    assert on_wall(fake_cozyla)["Clean upstairs"] == ["m-erin"]


async def test_a_chore_that_is_up_stays_up_across_days(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    limit(scenario, "Erin", 1)
    cage = await one_off(scenario, "Clean the bird cage", WED)
    await one_off(scenario, "Change the sheets", WED - timedelta(days=1))
    sheets_first = await sync(scenario)
    assert sheets_first and set(on_wall(fake_cozyla)) == {"Change the sheets"}

    await one_off(scenario, "Vacuum the stairs", WED - timedelta(days=5))  # more overdue now
    await scenario.advance(hours=24)
    await sync(scenario)
    sheets = fake_cozyla.chore_named("Change the sheets")
    assert set(on_wall(fake_cozyla)) == {"Change the sheets"}  # not swapped out
    assert sheets["startDay"] == (WED + timedelta(days=1)).isoformat()  # moved to today
    assert board(scenario).get(cage.id).status == "open"


async def test_either_of_you_counts_for_her_and_stays_for_him(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    limit(scenario, "Erin", 1)
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Bring the bins in", "every Wednesday", either=True)
    await sync(scenario)
    assert on_wall(fake_cozyla) == {
        "Clean the kitchen": ["m-erin"],
        "Bring the bins in": ["m-husband"],  # waiting for her; still his
    }
    bins = fake_cozyla.chore_named("Bring the bins in")
    assert (bins["choreType"], bins["repeats"]) == ("Everyone", True)


async def test_she_can_choose_that_shared_chores_dont_count(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    limit(scenario, "Erin", 1)
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Clean upstairs", "every Wednesday")
    await chore(scenario, "Bring the bins in", "every Wednesday", either=True)
    scenario.primary.queue_tool_call("set_chore_chart_limit", {"limit": -1, "shared_count": "no"})
    scenario.primary.queue_text("Shared chores will always show.")
    await scenario.say("Erin", "Chores either of us can do shouldn't count toward my one")
    erin = scenario.member("Erin")
    assert (erin.chart_limit, erin.chart_counts_shared) == (1, False)  # the limit kept
    await sync(scenario)
    assert on_wall(fake_cozyla) == {
        "Clean the kitchen": ["m-erin"],  # her one
        "Bring the bins in": ["m-erin", "m-husband"],  # always shows, for both
    }
    bins = fake_cozyla.chore_named("Bring the bins in")
    assert (bins["choreType"], bins["repeats"]) == ("AnyOne", True)


async def test_waiting_chores_send_no_nudges(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    await chore(scenario, "Clean the kitchen", "every Wednesday at 6pm")
    await chore(scenario, "Clean upstairs", "every Wednesday at 6pm")
    assert len(queued_nudges(scenario, "Erin")) == 2  # before her limit

    limit(scenario, "Erin", 1)
    await sync(scenario)
    (nudge,) = queued_nudges(scenario, "Erin")
    assert "Clean the kitchen" in nudge  # the one that's up; upstairs waits, quietly

    scenario.app.db.execute(
        "UPDATE tasks SET due_on = ? WHERE title = 'Clean upstairs'",
        ((WED - timedelta(days=3)).isoformat(),),
    )
    scenario.app.db.execute("UPDATE tasks SET missed = 'catch_up' WHERE title = 'Clean upstairs'")
    assert await scenario.run_periodic("tasks.overdue") == 0  # not raised while it waits
    assert not any("upstairs" in t for t in queued_nudges(scenario, "Erin"))


async def test_a_chore_that_comes_up_gets_its_nudge(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    limit(scenario, "Erin", 1)
    kitchen = await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Clean upstairs", "every Wednesday")
    await sync(scenario)
    assert not any(
        "upstairs" in n for n in scenario.inbox("Erin") + queued_nudges(scenario, "Erin")
    )
    await board(scenario).complete(kitchen.id, scenario.member("Erin"))
    await sync(scenario)
    assert any(
        "Clean upstairs" in n for n in scenario.inbox("Erin") + queued_nudges(scenario, "Erin")
    )
    assert set(on_wall(fake_cozyla)) == {"Clean upstairs"}


async def test_a_different_one_or_another_one(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    limit(scenario, "Erin", 1)
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Clean upstairs", "every Wednesday")
    sheets = await one_off(scenario, "Change the sheets", WED + timedelta(days=3))
    await sync(scenario)
    assert set(on_wall(fake_cozyla)) == {"Clean the kitchen"}

    scenario.primary.queue_tool_call("change_chore_chart", {"action": "different", "task_id": 0})
    scenario.primary.queue_text("Upstairs is up instead.")
    await scenario.say("Erin", "Can I have a different chore?")
    result = str(scenario.primary.last_request.messages[-1].content[0])
    assert (
        "Clean upstairs is up now" in result and "Clean the kitchen waits until tomorrow" in result
    )
    await sync(scenario)
    assert set(on_wall(fake_cozyla)) == {"Clean upstairs"}

    scenario.primary.queue_tool_call("change_chore_chart", {"action": "another", "task_id": 0})
    scenario.primary.queue_text("The sheets are up too.")
    await scenario.say("Erin", "I've got energy, give me another one")
    result = str(scenario.primary.last_request.messages[-1].content[0])
    assert "Change the sheets is also up" in result and "not due until Saturday" in result
    await sync(scenario)
    assert set(on_wall(fake_cozyla)) == {"Clean upstairs", "Change the sheets"}

    await board(scenario).complete(sheets.id, scenario.member("Erin"))  # the extra one
    await sync(scenario)
    uid = fake_cozyla.chore_named("Change the sheets")["choreUid"]
    assert fake_cozyla.chore_ticks[(uid, "m-erin", WED.isoformat())] == "completed"
    assert set(on_wall(fake_cozyla)) == {"Clean upstairs", "Change the sheets"}  # nothing new


async def test_asking_for_a_named_chore(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    limit(scenario, "Erin", 1)
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    upstairs = await chore(scenario, "Clean upstairs", "every Friday")
    await sync(scenario)
    scenario.primary.queue_tool_call(
        "change_chore_chart", {"action": "different", "task_id": upstairs.id}
    )
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Can I do upstairs today instead?")
    await sync(scenario)
    assert set(on_wall(fake_cozyla)) == {"Clean upstairs"}


async def test_the_only_chore_waiting_stays_up(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    limit(scenario, "Erin", 1)
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    await sync(scenario)
    queue = scenario.app.services.chart_queue
    assert queue is not None
    erin = scenario.member("Erin")
    assert queue.change(erin, "different", 0) == "That's the only chore waiting, so it stays up."
    await sync(scenario)
    assert set(on_wall(fake_cozyla)) == {"Clean the kitchen"}


async def test_themi_knows_whether_a_chore_is_up_or_waiting(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    limit(scenario, "Erin", 1)
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Clean upstairs", "every Wednesday")
    await sync(scenario)
    items = {
        title: next(
            i.summary
            for i in board(scenario).open_items(scenario.member("Erin"))
            if title in i.summary
        )
        for title in ("Clean the kitchen", "Clean upstairs")
    }
    assert "Up now on Erin's chore chart (1 at a time)." in items["Clean the kitchen"]
    assert (
        "Waiting its turn for Erin's chore chart (1 at a time); not on the wall yet."
        in (items["Clean upstairs"])
    )


async def test_the_limit_is_a_setting(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    await chore(scenario, "Clean the kitchen", "every Wednesday")
    await chore(scenario, "Clean upstairs", "every Wednesday")
    scenario.primary.queue_tool_call("set_chore_chart_limit", {"limit": 1, "shared_count": "keep"})
    scenario.primary.queue_text("Just one at a time from now on.")
    await scenario.say("Erin", "Only show me one chore at a time on the wall")
    assert scenario.member("Erin").chart_limit == 1
    assert not scenario.app.db.query("SELECT 1 FROM rules WHERE status = 'draft'")
    await sync(scenario)
    assert len(on_wall(fake_cozyla)) == 1

    limit(scenario, "Erin", 0)  # back to all of them
    await sync(scenario)
    assert set(on_wall(fake_cozyla)) == {"Clean the kitchen", "Clean upstairs"}
    erin = scenario.member("Erin")
    with pytest.raises(InvalidValue):
        scenario.app.store.update_settings(erin, erin.id, chart_limit=11)
