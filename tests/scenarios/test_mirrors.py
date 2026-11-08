"""CR21b: displays and apps keeping lists, tasks and routines in step are mirrors. With none,
lists, tasks and routines work as ever; a mirror hears what leaves and says where it is."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.modules.mirrors import Mirror
from themi.standard.lists import MAX_ITEM, Lists, item_limit, too_long
from themi.standard.tasks import TaskBoard

WED = date(2026, 10, 21)
ADDED = "2026-10-21T08:00:00+00:00"
FRIDGE = Mirror("fridge", "on the fridge screen", item_limit=40)


def lists(scenario: Scenario) -> Lists:
    return scenario.app.services.get(keys.lists)


async def test_lists_with_no_mirror(scenario: Scenario) -> None:
    assert scenario.app.services.mirrors.mirrors == {}  # no wall here
    erin = scenario.member("Erin")
    made = lists(scenario).create(erin, "Packing", personal=False)
    assert made.mirror is None and item_limit(made) == MAX_ITEM
    for name in ("Tent", "Hats"):
        lists(scenario).db.execute(
            "INSERT INTO list_items (list_id, name, done, added_at) VALUES (?, ?, 0, ?)",
            (made.id, name, ADDED),
        )
    nl = lists(scenario).get(made.id, erin)
    assert nl is not None
    lists(scenario).tick(nl.items[0], True, erin)
    nl = lists(scenario).get(made.id, erin)
    assert nl is not None
    assert lists(scenario).clear_ticked(nl) == 1
    lists(scenario).remove(nl.items[1])
    lists(scenario).delete(nl)
    assert lists(scenario).get(made.id, erin) is None


async def test_a_mirror_hears_what_leaves_and_says_where_it_is(scenario: Scenario) -> None:
    heard: list[tuple[str, object]] = []
    mirrors = scenario.app.services.mirrors
    erin = scenario.member("Erin")
    made = lists(scenario).create(erin, "Packing", personal=False)
    mirrors.add(FRIDGE)
    mirrors.list_keepers.append(lambda list_id: FRIDGE if list_id == made.id else None)

    def items_leaving(ids: Sequence[int]) -> None:
        heard.append(("items", tuple(ids)))

    mirrors.items_leaving.append(items_leaving)
    mirrors.lists_leaving.append(lambda list_id: heard.append(("list", list_id)))
    item_id = lists(scenario).db.execute(
        "INSERT INTO list_items (list_id, name, done, added_at) VALUES (?, 'Tent', 0, ?)",
        (made.id, ADDED),
    )
    nl = lists(scenario).get(made.id, erin)
    assert nl is not None and nl.mirror == FRIDGE
    assert item_limit(nl) == 40
    assert "the most a list on the fridge screen takes" in too_long(nl)
    lists(scenario).remove(nl.items[0])
    lists(scenario).delete(nl)
    assert heard == [("items", (item_id,)), ("list", made.id)]


async def test_a_tick_on_a_mirror_gets_its_words(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    board = scenario.app.services.get(TaskBoard)
    task = await board.create(erin, "Water the plants", "physical", 1, WED, assignee=erin)
    await board.complete(task.id, erin, ticked_on=FRIDGE.where)
    await scenario.advance(minutes=2)
    assert any(
        t.startswith("Ticked off on the fridge screen: Water the plants.")
        for t in scenario.inbox("Erin")
    )
