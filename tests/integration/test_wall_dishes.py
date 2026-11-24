"""WL9b: the small lists at the foot of the wall are cards with a count and an Open link, and
Things to cook opens a view of its dishes, numbered, each unfolding in place to its
ingredients and Start cooking. The scenario's day is Wednesday 21 October 2026, 9 am,
Los Angeles."""

from __future__ import annotations

import re

from tests.integration.test_wall_card import foot, kicker
from tests.integration.test_wall_list_views import get, post, soup
from tests.integration.test_wall_screen import screen, wall, words
from tests.scenarios.harness import Scenario
from themi.core import keys

__all__ = ["wall"]  # the fixture


def smalls(page: str) -> str:
    return page[page.index('id="wall-smalls"') : page.index('id="wall-stale"')]


def cards(page: str) -> list[str]:
    return re.findall(
        r'<(?:button|section)[^>]*class="wall-card wall-small[^"]*".*?</(?:button|section)>',
        smalls(page),
        re.S,
    )


def numbered(view: str) -> list[str]:
    return [
        f"{n} {name}"
        for n, name in re.findall(
            r'<span class="dish-num">(\d+)</span>'
            r'<span class="wall-words"><span class="wall-title">([^<]+)</span>',
            view,
        )
    ]


# ----- the cards ----------------------------------------------------------------------


async def test_groceries_and_things_to_cook_are_cards_with_a_count(wall: Scenario) -> None:
    soup(wall)
    wall.app.services.get(keys.groceries).add(["grapes"], by=wall.member("Erin"))
    groceries, cook = cards(await screen(wall))
    assert groceries.startswith('<button type="button" class="wall-card wall-small')
    assert 'hx-get="/wall/view/list/groceries"' in groceries
    assert words(groceries) == "Groceries Grapes 1 item Open list"
    assert cook.startswith('<button type="button" class="wall-card wall-small')
    assert 'hx-get="/wall/view/dishes"' in cook
    assert words(cook) == "Things to cook Bean soup Creami prep 2 ideas Open ideas"
    assert "/wall/view/dish/" not in cook  # one tap for the whole card


async def test_nothing_on_groceries_says_so(wall: Scenario) -> None:
    [groceries] = cards(await screen(wall))
    assert words(groceries) == "Groceries Nothing needed Open list"


async def test_another_household_list_is_a_card_with_its_count_that_opens_it(
    wall: Scenario,
) -> None:
    # F59e (idea #254) changed this: the card opens its List view (it had no link in WL9b).
    lists = wall.app.services.get(keys.lists)
    erin = wall.member("Erin")
    store = lists.create(erin, "Hardware store", personal=False)
    lists.add(store, ["Hinges", "Glue", "Sandpaper", "Bulbs", "Screws"], erin)
    _, hardware = cards(await screen(wall))
    assert hardware.startswith('<button type="button" class="wall-card wall-small')
    assert words(hardware) == "Hardware store Hinges Glue Sandpaper Bulbs +1 more 5 items Open list"
    assert f'hx-get="/wall/view/list/list/{store.id}"' in hardware


# ----- the Things to cook view ----------------------------------------------------------


async def test_open_ideas_lists_the_dishes_numbered(wall: Scenario) -> None:
    item = soup(wall)
    view = (await get(wall, "/wall/view/dishes")).text
    assert kicker(view) == "Household"
    assert numbered(view) == ["01 Bean soup", "02 Creami prep"]
    assert foot(view) == ["2 ideas saved"]
    assert f'hx-get="/wall/view/dish/{item}"' in view
    assert 'name="have"' not in view  # nothing unfolded yet


async def test_a_dish_unfolds_in_place_and_folds_again(wall: Scenario) -> None:
    item = soup(wall)
    view = (await get(wall, f"/wall/view/dish/{item}")).text
    assert numbered(view) == ["01 Bean soup", "02 Creami prep"]  # still the whole list
    names = re.findall(r'name="have" value="([^"]+)"', view)
    assert names == ["white beans", "broth", "onion"]
    assert "Husband is cooking" in view and "Erin is cooking" in view
    opened = view[view.index('class="sheet-row sheet-dish open"') :]
    assert opened.index('hx-get="/wall/view/dishes"') < opened.index('name="have"')


async def test_a_dish_without_a_recipe_unfolds_to_say_so(wall: Scenario) -> None:
    soup(wall)
    lists = wall.app.services.get(keys.lists)
    [nl] = [n for n in lists.visible(wall.member("Erin")) if n.name == "Things to cook"]
    creami = next(i for i in nl.open_items if i.name == "Creami prep")
    view = (await get(wall, f"/wall/view/dish/{creami.id}")).text
    assert "no recipe for this" in view and "is cooking" not in view
    assert numbered(view) == ["01 Bean soup", "02 Creami prep"]


async def test_add_the_rest_stays_on_that_dish(wall: Scenario) -> None:
    item = soup(wall)
    view = (await post(wall, f"/wall/view/dish/{item}/add", have=["onion", "broth"])).text
    row = wall.app.db.one("SELECT payload FROM pending_actions WHERE category = 'grocery_list_add'")
    assert row is not None and '"items": ["white beans"]' in row["payload"]
    assert 'class="sheet-row sheet-dish open"' in view and 'name="have"' in view
    assert 'role="status"' in view
