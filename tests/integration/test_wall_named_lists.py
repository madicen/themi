"""F59e (Michael's idea #254): any household list's card on the wall opens it, all of it, to
tick things off, put a tick back, or add to it. The scenario's day is Wednesday 21 October
2026, 9 am, Los Angeles."""

from __future__ import annotations

import re

from tests.integration.test_wall_list_views import get, post
from tests.integration.test_wall_screen import wall, words
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi.standard.lists import NamedList

__all__ = ["wall"]  # the fixture

THINGS = ["pillow", "pajamas", "toiletries bag", "flip flops", "underwear", "blanket", "razor"]


def bring(s: Scenario) -> NamedList:
    """The Pi's list, as it was on 23 November."""
    lists = s.app.services.get(keys.lists)
    erin = s.member("Erin")
    nl = lists.create(erin, "Things to bring Erin", personal=False)
    lists.add(nl, THINGS, s.member("Husband"))
    return lists.reload(nl)


def rows(view: str) -> list[str]:
    return re.findall(r'<span class="wall-title">([^<]+)</span>', view)


def item_id(nl: NamedList, name: str) -> str:
    return str(next(i.id for i in nl.items if i.name == name))


async def test_the_list_opens_with_every_item(wall: Scenario) -> None:
    nl = bring(wall)
    view = (await get(wall, f"/wall/view/list/list/{nl.id}")).text
    assert rows(view) == THINGS
    assert "Tap one to tick it off." in words(view)
    assert "7 open" in words(view)


async def test_a_tick_takes_it_off_and_a_tap_in_ticked_lately_puts_it_back(
    wall: Scenario,
) -> None:
    nl = bring(wall)
    path = f"/wall/view/list/list/{nl.id}"
    ticked = (await post(wall, path, op="tick", id=item_id(nl, "pillow"))).text
    assert "Ticked pillow off Things to bring Erin." in ticked
    assert "pillow" not in rows(ticked)[:6] and "Ticked off lately (1)" in ticked
    lists = wall.app.services.get(keys.lists)
    assert [i.name for i in lists.reload(nl).open_items] == THINGS[1:]
    back = (await post(wall, path, op="untick", id=item_id(nl, "pillow"))).text
    assert "pillow is back on Things to bring Erin." in back
    assert "Ticked off lately" not in back
    assert len(lists.reload(nl).open_items) == 7


async def test_add_puts_it_on_the_list(wall: Scenario) -> None:
    nl = bring(wall)
    added = (await post(wall, f"/wall/view/list/list/{nl.id}", op="add", text="slippers")).text
    assert "Added slippers to Things to bring Erin." in added
    assert "slippers" in rows(added)


async def test_a_personal_list_or_things_to_buy_doesnt_open(wall: Scenario) -> None:
    lists = wall.app.services.get(keys.lists)
    mine = lists.create(wall.member("Erin"), "Erin's secret list", personal=True)
    lists.add(mine, ["a gift"], wall.member("Erin"))
    assert (await get(wall, f"/wall/view/list/list/{mine.id}")).text == ""
    assert (await get(wall, "/wall/view/list/list/9999")).text == ""
    assert (await post(wall, f"/wall/view/list/list/{mine.id}", op="add", text="x")).text == ""
    assert [i.name for i in lists.reload(mine).items] == ["a gift"]


async def test_what_the_wall_ticked_is_what_show_lists_shows(wall: Scenario) -> None:
    nl = bring(wall)
    path = f"/wall/view/list/list/{nl.id}"
    await post(wall, path, op="tick", id=item_id(nl, "pillow"))
    await post(wall, path, op="tick", id=item_id(nl, "pajamas"))
    wall.primary.queue_tool_call("show_lists", {"list": "Things to bring Erin"})
    wall.primary.queue_text("Here's what's left.")
    await wall.say("Husband", "What's left on the list of things to bring Erin?")
    from tests.scenarios.test_travel import tool_result

    shown = tool_result(wall)
    assert shown == (
        "Things to bring Erin: toiletries bag, flip flops, underwear, blanket and razor "
        "(ticked: pillow and pajamas)."
    )
