"""DC10: a recipe as a picture to keep: from chat ("a picture of the pancakes recipe") and
from its page on the website. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_day_card import golden
from themi.core import keys
from themi_home.recipe_card import (
    COLORS,
    CONTENT,
    LABEL,
    MORE_TEXT,
    STEPS_HEADING,
    card_svg,
    label,
    spaced,
    split_amount,
    view,
)
from themi_home.recipes import Line, Recipe


def pancakes(scenario: Scenario) -> Recipe:
    load(scenario.app.services)
    found = scenario.app.services.get(keys.recipes).find("pancakes")
    return found[0].recipe


async def test_the_card_matches_its_golden_file(scenario: Scenario) -> None:
    recipe = pancakes(scenario)
    svg = card_svg(recipe)
    golden("recipe", svg)
    assert recipe.name in svg and "Ingredients" in svg and STEPS_HEADING in svg
    for line in recipe.ingredients:
        assert line.text.split()[-1] in svg


async def test_dark_mode_has_its_own_golden_file(scenario: Scenario) -> None:
    recipe = pancakes(scenario)
    svg = card_svg(recipe, "dark")
    golden("recipe_dark", svg)
    assert COLORS["dark"]["bg"] in svg and COLORS["light"]["bg"] not in svg


def test_an_amount_is_split_from_its_ingredient() -> None:
    assert split_amount("2 Tbsp (28 g) Olive oil") == ("2 Tbsp (28 g)", "Olive oil")
    assert split_amount("5 Spring onions") == ("5", "Spring onions")
    assert split_amount("Salt & pepper") == ("", "Salt & pepper")
    assert split_amount("3-ingredient dough") == ("", "3-ingredient dough")


async def test_unmeasured_lines_are_also_needed_and_steps_have_titles(
    scenario: Scenario,
) -> None:
    recipe = replace(
        pancakes(scenario),
        ingredients=(Line("200 g Orzo"), Line("Salt & pepper")),
        steps=(Line("Add the orzo to the pan, then stir."), Line("Serve.")),
    )
    svg = card_svg(recipe)
    assert '<tspan font-weight="700"' in svg and ">200 g</tspan> Orzo" in svg
    assert "Also needed: Salt &amp; pepper" in svg
    assert ">01<" in svg and ">Add the orzo<" in svg  # first words without kept titles
    assert ">Fry it up<" in card_svg(recipe, titles=["Fry it up", "Serve"])
    assert "2 STEPS" in svg


async def test_recipe_words_stay_words(scenario: Scenario) -> None:
    recipe = replace(
        pancakes(scenario),
        name="Pancakes <script>alert(1)</script>",
        steps=(Line('<image href="file:///etc/passwd"/> Mix & stir'),),
    )
    svg = card_svg(recipe)
    assert "<script>" not in svg and 'href="file:' not in svg
    assert "Mix &amp; stir" in svg


async def test_a_very_long_recipe_says_the_rest_is_in_the_cookbook(scenario: Scenario) -> None:
    long = replace(
        pancakes(scenario), steps=tuple(Line(f"Step {i}: stir well") for i in range(200))
    )
    shown = view(long)
    assert shown["more"] == MORE_TEXT and shown["height"] <= 2400


async def test_asking_in_chat_sends_the_picture(scenario: Scenario) -> None:
    pancakes(scenario)
    scenario.primary.queue_tool_call("recipe_card", {"name": "pancakes"})
    scenario.primary.queue_text("Here you go.")
    replies = await scenario.say("Erin", "Send me a picture of the pancakes recipe to print")
    assert "Pancakes" in replies
    assert len(scenario.pictures("Erin")) == 1


@pytest.mark.usefixtures("scenario")
async def test_the_recipe_page_links_its_picture(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    pancakes(scenario)
    await sign_in(scenario, site, "Erin")
    recipe_id = int(scenario.app.db.scalar("SELECT id FROM recipes WHERE name = 'Pancakes'"))
    page = (await site.get(f"/recipes/{recipe_id}")).text
    assert f'href="/recipes/{recipe_id}/card.png"' in page
    picture = await site.get(f"/recipes/{recipe_id}/card.png")
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/png"
    assert picture.content[:4] == b"\x89PNG"


def test_the_label_names_the_family_and_stays_whole() -> None:
    assert label("") == LABEL == "MADICEN FAMILY RECIPE"
    assert label("Entrees") == "ENTREES / MADICEN FAMILY RECIPE"
    long = label("Holiday baking for the whole extended family · Cookies and bars")
    assert long.endswith(" / MADICEN FAMILY RECIPE") and "…" in long
    assert spaced(long, 11) <= CONTENT


async def test_a_third_of_a_cup_draws_its_fraction(scenario: Scenario) -> None:
    """F54 (bug #238): "⅓ Cup" drew an empty box where the ⅓ goes."""
    from themi.drawing.render import to_png

    def card(amount: str) -> bytes:
        recipe = replace(pancakes(scenario), ingredients=(Line(f"{amount} Cup (80 g) milk"),))
        return to_png(card_svg(recipe, "dark"))

    assert card("⅓") != card("ก")  # ก: in no bundled font, an empty box
    assert card("⅓") != card("⅔")
