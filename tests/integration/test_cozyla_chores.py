"""C2b: Themi's chores on the wall's chore chart, Themi in charge."""

from __future__ import annotations

from datetime import date
from typing import Any

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

WED = date(2026, 10, 21)  # the scenario clock's first day


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def sync(scenario: Scenario) -> Any:
    return await scenario.run_periodic("cozyla.chores")


async def chore(scenario: Scenario, title: str, phrase: str, who: str = "Erin", **kw: Any) -> Task:
    member = scenario.member(who)
    task = await board(scenario).create(member, title, "physical", 2, assignee=member)
    return await board(scenario).set_schedule(
        task.id, member, repeat=parse(phrase, board(scenario)._today()), **kw
    )


def open_chores(scenario: Scenario) -> dict[str, Task]:
    rows = scenario.app.db.query("SELECT id FROM tasks WHERE status = 'open' ORDER BY id")
    tasks = [board(scenario).get(r["id"]) for r in rows]
    return {t.title: t for t in tasks if t.repeats}


async def test_themis_chores_go_on_the_chart(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    await chore(scenario, "Take out the bins", "every Tuesday at 6pm")
    await chore(scenario, "Clean the bird cage", "twice a week")
    await sync(scenario)
    bins = fake_cozyla.chore_named("Take out the bins")
    assert (bins["repeats"], bins["repeatsEvery"], bins["repeatsIn"]) == (True, "Weekly", "Tuesday")
    assert (bins["dueTime"], bins["reminder"], bins["choreType"]) == ("18:00", -1, "Everyone")
    assert [r["memberUid"] for r in bins["memberRefs"]] == ["m-erin"]
    cage = fake_cozyla.chore_named("Clean the bird cage")  # the wall can't say "twice a week"
    due = open_chores(scenario)["Clean the bird cage"].due_on or WED  # due whenever: today
    assert (cage["repeats"], cage["startDay"], cage["endDay"]) == (
        False,
        due.isoformat(),
        due.isoformat(),
    )

    calls = len(fake_cozyla.calls)
    assert await sync(scenario) == 0  # nothing to change
    assert not any(
        "chores/update" in p or "chores/create" in p for p in fake_cozyla.paths()[calls:]
    )


async def test_edits_on_the_wall_are_put_back(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    await chore(scenario, "Take out the bins", "every Tuesday")
    await sync(scenario)
    bins = fake_cozyla.chore_named("Take out the bins")
    bins.update(choreName="Bins!!", repeatsIn="Monday")
    await sync(scenario)
    bins = fake_cozyla.chore_named("Take out the bins")
    assert bins["repeatsIn"] == "Tuesday"
    del fake_cozyla.chores[bins["choreUid"]]
    await sync(scenario)
    assert fake_cozyla.chore_named("Take out the bins")["repeatsIn"] == "Tuesday"


async def test_chores_only_on_the_wall_come_in_and_matching_ones_link(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    fake_cozyla.add_chore("Clean kitchen", ["m-erin"], days="Wednesday", start=date(2026, 7, 8))
    fake_cozyla.add_chore("Bring bins in", ["m-erin", "m-husband"], kind="AnyOne", days="Wednesday")
    fake_cozyla.add_chore(
        "Mimi pill",
        ["m-husband", "m-erin"],
        kind="AnyOne",
        every="Daily",
        count=2,
        start=WED,
        end=date(2026, 10, 30),
        forever=False,
    )
    fake_cozyla.add_chore(  # an old course, over
        "Tube Time",
        ["m-erin"],
        every="Daily",
        start=date(2026, 7, 11),
        end=date(2026, 8, 10),
        forever=False,
    )
    cage_uid = fake_cozyla.add_chore(  # Themi has it too, with its own schedule
        "Clean bird cage", ["m-husband"], days="Tuesday,Saturday", start=date(2026, 7, 10)
    )
    await chore(scenario, "Clean the bird cage", "twice a week")
    await sync(scenario)

    chores = open_chores(scenario)
    assert set(chores) == {"Clean the bird cage", "Clean kitchen", "Bring bins in", "Mimi pill"}
    kitchen = chores["Clean kitchen"]
    assert kitchen.assignee == scenario.member("Erin").id and not kitchen.either
    assert kitchen.created_by is None
    assert board(scenario).summary(kitchen) == "Every Wednesday"
    bins = chores["Bring bins in"]
    assert bins.either and bins.shared
    assert chores["Mimi pill"].importance == "high" and kitchen.importance == "normal"  # C2c
    assert board(scenario).summary(chores["Mimi pill"]) == (
        "Every other day, until Fri 30 Oct; either of you"
    )
    cage = fake_cozyla.chores[cage_uid]  # linked, and Themi's name, schedule and person won
    assert cage["choreName"] == "Clean the bird cage" and cage["repeats"] is False
    assert [r["memberUid"] for r in cage["memberRefs"]] == ["m-erin"]
    assert fake_cozyla.chore_named("Tube Time")["endDay"] == "2026-08-10"  # left alone


async def test_ticks_go_both_ways_once(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    kitchen = await chore(scenario, "Clean the kitchen", "every Wednesday")
    await sync(scenario)
    uid = fake_cozyla.chore_named("Clean the kitchen")["choreUid"]
    fake_cozyla.tick_chore(uid, "m-erin", WED)
    await sync(scenario)
    after = board(scenario).get(kitchen.id)
    assert after.due_on == date(2026, 10, 28)  # the round closed, as Erin
    runs = scenario.app.db.query("SELECT done_by FROM task_runs WHERE task_id = ?", (kitchen.id,))
    assert [r["done_by"] for r in runs] == [scenario.member("Erin").id]
    await sync(scenario)
    assert (
        scenario.app.db.scalar("SELECT COUNT(*) FROM task_runs WHERE task_id = ?", (kitchen.id,))
        == 1
    )  # not twice

    await scenario.advance(hours=24 * 7)  # the next Wednesday
    await board(scenario).complete(kitchen.id, scenario.member("Erin"))
    await sync(scenario)
    assert fake_cozyla.chore_ticks[(uid, "m-erin", "2026-10-28")] == "completed"
    assert board(scenario).get(kitchen.id).due_on == date(2026, 11, 4)


async def test_either_of_you_and_stopping(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    bins = await chore(scenario, "Bring the bins in", "every Wednesday", either=True)
    await sync(scenario)
    on_wall = fake_cozyla.chore_named("Bring the bins in")
    assert on_wall["choreType"] == "AnyOne"
    assert {r["memberUid"] for r in on_wall["memberRefs"]} == {"m-erin", "m-husband"}
    uid = on_wall["choreUid"]
    fake_cozyla.tick_chore(uid, "m-husband", WED)
    await sync(scenario)
    runs = scenario.app.db.query("SELECT done_by FROM task_runs WHERE task_id = ?", (bins.id,))
    assert [r["done_by"] for r in runs] == [scenario.member("Husband").id]
    assert board(scenario).get(bins.id).shared  # still on both lists next round

    await board(scenario).cancel(bins.id, scenario.member("Erin"))
    await sync(scenario)
    assert uid not in fake_cozyla.chores


async def test_a_one_off_task_can_go_on_the_chore_chart(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #15: "Vacuum upstairs bedroom is on the to-do list in Cozyla. Can you move it to
    chores?" Themi looked for a list called Chores."""
    erin = scenario.member("Erin")
    vacuum = await board(scenario).create(
        erin, "Vacuum upstairs bedroom", "physical", 2, WED, assignee=erin
    )
    await scenario.run_periodic("cozyla.sync")
    assert any(t["todoTitle"] == "Vacuum upstairs bedroom" for t in fake_cozyla.todos.values())

    scenario.primary.queue_tool_call("put_task_on_chore_chart", {"task_id": vacuum.id})
    scenario.primary.queue_text("It's on the chore chart now.")
    await scenario.say("Erin", "Can you move vacuum upstairs bedroom to chores in Cozyla?")
    await scenario.run_periodic("cozyla.sync")
    await sync(scenario)
    assert not any(t["todoTitle"] == "Vacuum upstairs bedroom" for t in fake_cozyla.todos.values())
    chore = fake_cozyla.chore_named("Vacuum upstairs bedroom")
    assert (chore["repeats"], chore["startDay"]) == (False, WED.isoformat())
    assert [r["memberUid"] for r in chore["memberRefs"]] == ["m-erin"]

    fake_cozyla.tick_chore(chore["choreUid"], "m-erin", WED)
    await sync(scenario)
    assert board(scenario).get(vacuum.id).status == "done"


async def test_a_one_off_on_the_chart_done_in_themi_is_ticked_there(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    sheets = await board(scenario).create(
        erin, "Change the sheets", "physical", 2, WED, assignee=erin
    )
    await board(scenario).put_on_chart(sheets.id, erin)
    await sync(scenario)
    uid = fake_cozyla.chore_named("Change the sheets")["choreUid"]
    await board(scenario).complete(sheets.id, erin)
    await sync(scenario)
    assert fake_cozyla.chore_ticks[(uid, "m-erin", WED.isoformat())] == "completed"


async def test_themi_knows_which_day_a_task_shows_on_the_chart(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Erin moved "Vacuum upstairs bedroom" to chores and asked when it would show. Themi
    said the chore integration "isn't active"; the answer she wanted was "Sunday"."""
    from datetime import timedelta

    erin = scenario.member("Erin")
    sunday = WED + timedelta(days=4)
    vacuum = await board(scenario).create(
        erin, "Vacuum upstairs bedroom", "physical", 2, sunday, assignee=erin
    )
    scenario.primary.queue_tool_call("put_task_on_chore_chart", {"task_id": vacuum.id})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "move vacuum upstairs bedroom to chores")
    result = str(scenario.primary.last_request.messages[-1].content[0])
    assert "Sunday 25 Oct" in result

    def item() -> str:
        (found,) = [i.summary for i in board(scenario).open_items(erin) if "Vacuum" in i.summary]
        return found

    assert "Shows on the wall's chore chart on Sunday 25 Oct (being added now)" in item()
    await sync(scenario)
    assert "Shows on the wall's chore chart on Sunday 25 Oct." in item()
    bins = await chore(scenario, "Bring the bins in", "every Wednesday")
    await sync(scenario)
    (bins_item,) = [i.summary for i in board(scenario).open_items(erin) if "bins" in i.summary]
    assert "Shows on the wall's chore chart on Wednesday 21 Oct." in bins_item
    assert bins.id
