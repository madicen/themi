"""F26c (Michael's idea #142): a task's steps split into tasks of their own, which can be
spread out or shared, so someone without the energy for all of it can do part. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tests.fakes.cozyla import FakeCozyla
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.ai.types import ToolResult
from themi.core import keys
from themi.standard.repeat import parse
from themi.standard.task_parts import TaskParts, part_effort, part_title
from themi.standard.tasks import Task, TaskBoard

STEPS = ["Scoop the old litter", "Wash the tray", "Fill with fresh litter"]


def board(scenario: Scenario) -> TaskBoard:
    return scenario.app.services.get(keys.taskboard)


def parts(scenario: Scenario) -> TaskParts:
    return scenario.app.services.get(keys.task_parts)


async def cat_box(scenario: Scenario, *, due: date | None = None) -> Task:
    erin = scenario.member("Erin")
    return await board(scenario).create(
        erin, "Split Merlin's cat box", "physical", 3, due, assignee=erin, steps=STEPS
    )


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def split(scenario: Scenario, name: str, said: str, task: Task, chosen: list[dict]) -> str:
    scenario.primary.queue_tool_call("split_task", {"task_id": task.id, "parts": chosen})
    scenario.primary.queue_text("Done.")
    await scenario.say(name, said)
    return tool_result(scenario)


def titles(tasks: list[Task]) -> list[str]:
    return [t.title for t in tasks]


def part(step: int, who: str, due: str = "") -> dict[str, Any]:
    return {"step": step, "who": who, "due": due}


async def test_split_three_ways_between_erin_and_michael(scenario: Scenario) -> None:
    task = await cat_box(scenario)
    said = await split(
        scenario,
        "Erin",
        "Split the cat box up: I'll scoop, he can wash the tray, and the litter's mine too",
        task,
        [part(1, "me"), part(2, "partner", "2026-10-23")],
    )
    assert said.startswith("Split Split Merlin's cat box into 3 parts")
    made = parts(scenario).parts(task.id)
    assert titles(made) == [part_title(task.title, s) for s in STEPS]
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    assert [p.assignee for p in made] == [erin.id, husband.id, erin.id]  # the rest stays hers
    assert made[1].due_on == date(2026, 10, 23)
    assert all(p.effort == part_effort(3, 3) == 1 for p in made)

    # Each part is on the right list; the parent is on nobody's.
    assert titles(board(scenario).open_for(erin)) == [made[0].title, made[2].title]
    assert titles(board(scenario).open_for(husband)) == [made[1].title]
    items = [i.summary for i in board(scenario).open_items(husband)]
    assert any("Part 2 of 3 of Split Merlin's cat box; 0 of 3 parts done." in i for i in items)

    # The parent is checked off when the last part is.
    await board(scenario).complete(made[0].id, erin)
    await board(scenario).complete(made[1].id, husband)
    assert board(scenario).get(task.id).status == "open"
    assert parts(scenario).progress(task.id) == (2, 3)
    await board(scenario).complete(made[2].id, erin)
    assert board(scenario).get(task.id).status == "done"

    # A part done counts as done in the summary of the day.
    done = board(scenario).done_between(
        husband, clock.now() - timedelta(hours=1), clock.now() + timedelta(minutes=1)
    )
    assert made[1].title in [d.task.title for d in done]


async def test_split_all_keeps_the_assignee_and_due_date(scenario: Scenario) -> None:
    task = await cat_box(scenario, due=date(2026, 10, 24))
    await split(scenario, "Erin", "split the cat box task up", task, [])
    made = parts(scenario).parts(task.id)
    assert len(made) == 3 and {p.due_on for p in made} == {date(2026, 10, 24)}
    assert {p.assignee for p in made} == {scenario.member("Erin").id}


async def test_either_of_you_goes_to_whoever_has_room(scenario: Scenario) -> None:
    task = await cat_box(scenario)
    await split(scenario, "Erin", "anyone can do the last bit", task, [part(3, "either")])
    last = parts(scenario).parts(task.id)[2]
    assert last.assignee in {scenario.member("Erin").id, scenario.member("Husband").id}


async def test_parts_all_taken_off_take_the_task_off_too(scenario: Scenario) -> None:
    task = await cat_box(scenario)
    await split(scenario, "Erin", "split it up", task, [])
    for p in parts(scenario).parts(task.id):
        await board(scenario).cancel(p.id, scenario.member("Erin"))
    assert board(scenario).get(task.id).status == "cancelled"


async def test_a_repeating_chore_is_refused(scenario: Scenario) -> None:
    task = await cat_box(scenario)
    await board(scenario).set_schedule(
        task.id, scenario.member("Erin"), repeat=parse("every Saturday", scenario.today())
    )
    said = await split(scenario, "Erin", "split the cat box up", task, [])
    assert "a repeating chore's steps aren't split" in said
    assert parts(scenario).parts(task.id) == []


async def test_nothing_to_split_or_split_twice_is_refused(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    plain = await board(scenario).create(erin, "Call the vet", "call", 1, assignee=erin)
    assert "nothing to split" in await split(scenario, "Erin", "split the vet call", plain, [])
    task = await cat_box(scenario)
    await split(scenario, "Erin", "split it up", task, [])
    assert "split already" in await split(scenario, "Erin", "split it up again", task, [])
    said = await split(scenario, "Erin", "split it", task, [part(7, "me")])
    assert "split already" in said
    other = await cat_box(scenario)
    assert "no step 7" in await split(scenario, "Erin", "split it", other, [part(7, "me")])
    assert parts(scenario).parts(other.id) == []


async def test_the_parts_go_on_the_wall_and_the_task_comes_off(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    task = await cat_box(scenario)
    await scenario.run_periodic("cozyla.sync")
    assert task.title in fake_cozyla.titles(scenario.cozyla_list)
    await split(scenario, "Erin", "split the cat box up", task, [part(2, "partner")])
    await scenario.run_periodic("cozyla.sync")
    on_wall = fake_cozyla.titles(scenario.cozyla_list)
    assert task.title not in on_wall
    assert {part_title(task.title, s) for s in STEPS} <= set(on_wall)


async def test_the_website_shows_where_each_part_stands(scenario: Scenario) -> None:
    task = await cat_box(scenario)
    await split(scenario, "Erin", "he can wash the tray", task, [part(2, "partner")])
    made = parts(scenario).parts(task.id)
    await board(scenario).complete(made[0].id, scenario.member("Erin"))
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Husband")
        page = (await site.get("/tasks")).text
    assert "Part 2 of 3 of Split Merlin&#39;s cat box; 1 of 3 parts done" in page
    assert "Split Merlin&#39;s cat box: Wash the tray" in page
