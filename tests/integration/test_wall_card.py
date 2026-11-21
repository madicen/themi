"""WL9a: every view on the wall is a centred card: a kicker, a title, a kind line, the view,
a foot line, and a full-width "Back to the wall" in the view's colour. The scenario's day is
Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import html as html_lib
import re

from tests.integration.test_wall_list_views import bins, get, soup
from tests.integration.test_wall_screen import task, wall, words
from tests.scenarios.harness import Scenario
from themi.core import keys

__all__ = ["wall"]  # the fixture


def card(html: str) -> str:
    """The view's card, without the backdrop."""
    found = re.search(r'<section class="wall-sheet[^"]*"[^>]*>.*</section>', html, re.S)
    assert found, html
    return found[0]


def kicker(html: str) -> str:
    found = re.search(r'<p class="sheet-kicker">([^<]*)</p>', html)
    return found[1] if found else ""


def lead(html: str) -> str:
    found = re.search(r'<p class="sheet-lead">([^<]*)</p>', html)
    return html_lib.unescape(found[1]) if found else ""


def foot(html: str) -> list[str]:
    found = re.search(r'<div class="sheet-foot">(.*?)</div>', html, re.S)
    return re.findall(r"<p[^>]*>([^<]*)</p>", found[1]) if found else []


def assert_a_card(html: str, tone: str) -> None:
    shown = card(html)
    assert f'class="wall-sheet tone-{tone}"' in shown
    assert "wall-grip" not in shown
    back = re.search(r'<button type="button" class="sheet-back" data-close>([^<]*)</button>', shown)
    assert back and back[1] == "Back to the wall"
    assert re.search(r'<button type="button" class="sheet-x" data-close aria-label="Close">', shown)
    assert 'data-close-after="120"' in shown


async def test_the_grocery_view_is_a_household_card_with_its_count(wall: Scenario) -> None:
    groceries = wall.app.services.get(keys.groceries)
    groceries.add(["dried mango", "grapes"], by=wall.member("Erin"))
    view = (await get(wall, "/wall/view/list/groceries")).text
    assert_a_card(view, "family")
    assert kicker(view) == "Household"
    assert lead(view) == "A short list for your next shop."
    assert foot(view) == ["2 items to pick up", "Shared with Erin and Husband"]  # the wall's order
    assert 'class="tone-family sheet-list sheet-groceries"' in view


async def test_one_grocery_is_one_item(wall: Scenario) -> None:
    wall.app.services.get(keys.groceries).add(["grapes"], by=wall.member("Erin"))
    view = (await get(wall, "/wall/view/list/groceries")).text
    assert foot(view)[0] == "1 item to pick up"


async def test_an_empty_grocery_list_says_so_at_its_foot(wall: Scenario) -> None:
    view = (await get(wall, "/wall/view/list/groceries")).text
    assert foot(view)[0] == "Nothing to pick up"


async def test_a_to_do_list_counts_whats_open(wall: Scenario) -> None:
    for title in ("Vet", "Mail", "Gate"):
        await task(wall, "Erin", title)
    erin = wall.member("Erin")
    view = (await get(wall, f"/wall/view/list/todo/{erin.id}")).text
    tone = re.search(r'class="tone-(\w+) sheet-list"', view)
    assert tone and tone[1] != "family"
    assert_a_card(view, tone[1])
    assert kicker(view) == "To-do"
    assert lead(view) == "In Themi's order. Tap the words for more."
    assert foot(view) == ["3 open"]
    assert "sheet-note" not in view  # the kind line took its place


async def test_the_family_list_is_in_the_family_colour(wall: Scenario) -> None:
    await task(wall, "Erin", "Fix the gate", both="either")
    view = (await get(wall, "/wall/view/list/todo/family")).text
    assert_a_card(view, "family")
    assert foot(view) == ["1 open"]


async def test_a_dish_is_a_household_card(wall: Scenario) -> None:
    item = soup(wall)
    view = (await get(wall, f"/wall/view/dish/{item}")).text
    assert_a_card(view, "family")
    assert kicker(view) == "Household"  # WL9b: the dish unfolds in Things to cook


async def test_the_note_is_from_themi(wall: Scenario) -> None:
    await bins(wall)
    view = (await get(wall, "/wall/view/note")).text
    assert kicker(view) == "From Themi"
    assert "Back to the wall" in words(view)
