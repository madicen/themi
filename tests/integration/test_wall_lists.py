"""L1b: Themi's lists and the wall's, kept in step. The wall's own lists come in as the
household's; a list goes on the wall only when someone asks."""

from __future__ import annotations

from typing import Any

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi.core.lists import Lists, NamedList


def lists(scenario: Scenario) -> Lists:
    assert scenario.app.services.lists is not None
    return scenario.app.services.lists


def named(scenario: Scenario, name: str, who: str = "Erin") -> NamedList:
    return lists(scenario).find(scenario.member(who), name)


def items(scenario: Scenario, name: str) -> list[tuple[str, bool]]:
    return [(i.name, i.done) for i in named(scenario, name).items]


def on(fake: FakeCozyla, list_id: int) -> dict[str, bool]:
    """A wall list's to-dos: title -> ticked."""
    return {t["todoTitle"]: bool(t["completeStatus"]) for t in fake.in_list(list_id)}


def todo_id(fake: FakeCozyla, list_id: int, title: str) -> int:
    (found,) = [t["todoId"] for t in fake.in_list(list_id) if t["todoTitle"] == title]
    return found


async def sync(scenario: Scenario) -> Any:
    return await scenario.run_periodic("cozyla.sync")


async def say(scenario: Scenario, said: str, tool: str, args: dict[str, Any]) -> list[str]:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Done.")
    return await scenario.say("Erin", said)


async def test_the_walls_lists_come_in(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    fake_cozyla.add_todo(cook, "Lasagna")
    fake_cozyla.add_todo(cook, "Old soup", done=True)  # history: left behind
    fake_cozyla.add_todo(cook, "Make the pie crust", assignee="m-erin")  # a task (C1c)
    await sync(scenario)
    await sync(scenario)  # the history stays behind on later syncs too (seen live)
    cooking = named(scenario, "things to cook", who="Husband")  # the household's
    assert cooking.wall_id == str(cook) and not cooking.personal
    assert items(scenario, "things to cook") == [("Lasagna", False)]
    assert [nl.name for nl in lists(scenario).visible(scenario.member("Erin"))] == [
        "Things to Cook"
    ]  # the to-do list holds tasks: not one of these
    (line,) = [
        i.summary
        for i in scenario.app.services.open_items(scenario.member("Erin"))
        if i.summary.startswith("Lists:")
    ]
    assert line == 'Lists: "Things to Cook" (on the wall): 1 to go'


async def test_changes_go_both_ways(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    fake_cozyla.add_todo(cook, "Lasagna")
    fake_cozyla.add_todo(cook, "Tacos")
    await sync(scenario)

    await say(
        scenario,
        "add pho to things to cook",
        "add_to_list",
        {"list": "things to cook", "items": ["pho"]},
    )
    await sync(scenario)
    assert on(fake_cozyla, cook) == {"Lasagna": False, "Tacos": False, "pho": False}
    assert fake_cozyla.todos[todo_id(fake_cozyla, cook, "pho")]["assignMemberUid"] is None

    fake_cozyla.tick(todo_id(fake_cozyla, cook, "Lasagna"))  # on the wall
    fake_cozyla.edit(todo_id(fake_cozyla, cook, "Tacos"), todoTitle="Fish tacos")
    await sync(scenario)
    assert items(scenario, "cook") == [("Lasagna", True), ("Fish tacos", False), ("pho", False)]

    nl = named(scenario, "cook")
    pho = next(i for i in nl.items if i.name == "pho")
    lists(scenario).tick(pho, True, scenario.member("Erin"))  # in Themi
    await sync(scenario)
    assert on(fake_cozyla, cook)["pho"] is True

    lists(scenario).clear_ticked(named(scenario, "cook"))  # Lasagna and pho
    fake_cozyla.delete(todo_id(fake_cozyla, cook, "Fish tacos"))  # gone on the wall
    await sync(scenario)
    assert on(fake_cozyla, cook) == {}
    assert items(scenario, "cook") == []


async def test_themis_change_wins_and_someones_job_leaves_the_list(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    fake_cozyla.add_todo(cook, "Lasagna")
    fake_cozyla.add_todo(cook, "Bread")
    await sync(scenario)
    lasagna = next(i for i in named(scenario, "cook").items if i.name == "Lasagna")
    lists(scenario).tick(lasagna, True, scenario.member("Erin"))
    fake_cozyla.edit(todo_id(fake_cozyla, cook, "Lasagna"), todoTitle="Veggie lasagna")
    fake_cozyla.edit(todo_id(fake_cozyla, cook, "Bread"), assignMemberUid="m-husband")
    await sync(scenario)
    assert on(fake_cozyla, cook) == {"Lasagna": True, "Bread": False}  # Themi's wording back
    assert items(scenario, "cook") == [("Lasagna", True)]  # the bread is his job now
    tasks = scenario.app.db.query("SELECT title, assignee FROM tasks")
    assert [(t["title"], t["assignee"]) for t in tasks] == [
        ("Bread", scenario.member("Husband").id)
    ]


async def test_a_list_goes_on_the_wall_when_asked(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await sync(scenario)
    erin = scenario.member("Erin")
    packing = lists(scenario).create(erin, "Packing for the trip", personal=False)
    lists(scenario).add(packing, ["sunscreen", "hats"], erin)
    hats = next(i for i in named(scenario, "packing").items if i.name == "hats")
    lists(scenario).tick(hats, True, erin)
    await sync(scenario)
    assert len(fake_cozyla.lists) == 1  # only the to-do list: not on the wall unless asked

    replies = await say(scenario, "it's fine", "put_list_on_wall", {"list": "packing"})
    assert replies[0] == "Packing for the trip on the wall\nGo ahead, or not now?"
    await say(scenario, "Put the packing list on the wall", "put_list_on_wall", {"list": "packing"})
    await sync(scenario)
    (wall_id,) = [
        i for i, w in fake_cozyla.lists.items() if w["todoListTitle"] == "Packing for the trip"
    ]
    assert on(fake_cozyla, wall_id) == {"sunscreen": False, "hats": True}


async def test_a_list_that_matches_by_name_is_linked_not_doubled(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    cooking = lists(scenario).create(erin, "Things to Cook", personal=False)
    lists(scenario).add(cooking, ["Lasagna", "Curry"], erin)
    cook = fake_cozyla.add_list("Things to cook")
    fake_cozyla.add_todo(cook, "lasagna")
    await sync(scenario)
    assert [nl.name for nl in lists(scenario).visible(erin)] == ["Things to cook"]
    assert items(scenario, "cook") == [("Lasagna", False), ("Curry", False)]
    assert on(fake_cozyla, cook) == {"Lasagna": False, "Curry": False}


async def test_deleting_renaming_and_lists_gone_from_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    cook = fake_cozyla.add_list("Things to Cook")
    fake_cozyla.add_todo(cook, "Lasagna")
    shop = fake_cozyla.add_list("Shopping List")
    fake_cozyla.add_todo(shop, "Light bulbs")
    await sync(scenario)

    fake_cozyla.lists[cook]["todoListTitle"] = "Dinners"  # renamed on the wall
    del fake_cozyla.lists[shop]  # deleted on the wall: kept in Themi, unlinked
    await sync(scenario)
    assert named(scenario, "dinners").wall_id == str(cook)
    kept = named(scenario, "shopping")
    assert kept.wall_id is None and [i.name for i in kept.items] == ["Light bulbs"]

    replies = await say(scenario, "we don't need that one", "delete_list", {"list": "dinners"})
    assert replies[0] == "Deleting the list Dinners, on the wall too\nGo ahead, or not now?"
    await say(scenario, "delete the dinners list", "delete_list", {"list": "dinners"})
    await sync(scenario)
    assert cook not in fake_cozyla.lists
    assert [nl.name for nl in lists(scenario).visible(scenario.member("Erin"))] == ["Shopping List"]


async def test_renamed_in_themi_renamed_on_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """L2a: the family's Shopping List becomes Things to Buy."""
    shop = fake_cozyla.add_list("Shopping List")
    fake_cozyla.lists[shop]["todoListColor"] = "#123456"
    await sync(scenario)
    erin = scenario.member("Erin")
    lists(scenario).rename(named(scenario, "shopping"), erin, "Things to Buy")
    await sync(scenario)
    assert fake_cozyla.lists[shop]["todoListTitle"] == "Things to Buy"
    assert fake_cozyla.lists[shop]["todoListColor"] == "#123456"  # sent back as it was
    await sync(scenario)  # settled: no rename back and forth
    assert named(scenario, "things to buy").name == "Things to Buy"
    renames = [p for p in fake_cozyla.paths() if p.endswith("todosList/update")]
    assert len(renames) == 1
