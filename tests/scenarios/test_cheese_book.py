"""RC8c: the vegan cheese doc read as it's laid out, as a book of its own: its sections, its
Tools kept off the grocery list and shown while gathering, its recipes to convert labelled and
found only by name. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fixtures.cheese import CHEESE_TITLE, cheese_doc
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cookbook import account_id, choose
from tests.scenarios.test_cookbook import linked as linked  # a fixture
from tests.scenarios.test_recipe_groceries import items
from tests.scenarios.test_recipe_shelves import CHEESE_ID, choose_cheese
from tests.scenarios.test_triage import ERIN
from themi.core import keys
from themi_home.recipes import Recipe, Recipes

RICOTTA = "Rejuvelac Cultured Almond Ricotta"


def recipes(scenario: Scenario) -> Recipes:
    found = scenario.app.services.maybe(keys.recipes)
    assert found is not None
    return found


def named(scenario: Scenario, name: str) -> Recipe:
    return next(r for r in recipes(scenario).all() if r.name == name)


@pytest.fixture
async def cheese(scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient) -> FakeGdocs:
    await choose(scenario, site)
    linked.add_doc(CHEESE_ID, CHEESE_TITLE, cheese_doc(), shared_with=[ERIN])
    await choose_cheese(scenario, site)
    return linked


async def test_its_read_with_its_sections_and_its_special_sections_guessed(
    scenario: Scenario, cheese: FakeGdocs, site: httpx.AsyncClient
) -> None:
    assert scenario.inbox("Erin")[-1] == "I've read 6 recipes from Vegan cheese."
    assert (named(scenario, RICOTTA).section, named(scenario, RICOTTA).subsection) == (
        "Cheeses", "Fresh",
    )  # fmt: skip
    (shelf,) = recipes(scenario).shelves()
    assert (shelf.sub_recipe_sections, shelf.reference_sections) == (("Milks",), ("Appendix",))
    page = (await site.get(f"/accounts/{account_id(scenario)}/cookbook")).text
    assert 'name="sub_recipes" value="Milks"' in page


async def test_its_sections_can_be_changed_on_the_cookbook_page(
    scenario: Scenario, cheese: FakeGdocs, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    (shelf,) = recipes(scenario).shelves()
    await site.post(
        f"/accounts/{account_id(scenario)}/cookbook/books/{shelf.key}",
        data={"csrf": csrf, "action": "sections", "sub_recipes": "Milks, Cultures",
              "references": ""},
    )  # fmt: skip
    (shelf,) = recipes(scenario).shelves()
    assert (shelf.sub_recipe_sections, shelf.reference_sections) == (("Milks", "Cultures"), ())


async def test_its_tools_stay_off_the_grocery_list(
    scenario: Scenario, cheese: FakeGdocs, fake_ourgroceries: FakeOurGroceries
) -> None:
    scenario.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": [RICOTTA], "scale": ""}
    )
    scenario.primary.queue_structured(
        items([("almonds", False), ("rejuvelac", False), ("salt", True)])
    )
    (card,) = await scenario.say("Erin", f"Add the {RICOTTA} to the grocery list")
    asked = repr(scenario.primary.last_request)  # what was sent to be read
    assert "rejuvelac" in asked  # the lines it read
    assert "Cheesecloth" not in asked and "Cheesecloth" not in card
    assert "almonds" in card


async def test_gathering_says_what_youll_need(scenario: Scenario, cheese: FakeGdocs) -> None:
    from tests.unit.test_cook_screen import lines

    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    ricotta = named(scenario, RICOTTA)
    scenario.primary.queue_structured(lines([i.text for i in ricotta.ingredients]))
    session = await cooking.start(scenario.member("Erin"), ricotta)
    scenario.primary.queue_structured({"jobs": []})
    state = cooking.state(scenario.member("Erin"))
    if state["phase"] != "gather":  # past what needs doing first
        await cooking.act_from_page(scenario.member("Erin"), session.id, "next", state["seq"], {})
        state = cooking.state(scenario.member("Erin"))
    assert state["phase"] == "gather"
    assert state["tools"] == ["Cheesecloth", "Two ricotta molds"]
    found = cooking.get(session.id)
    assert found is not None
    text, _ = await cooking.render(found)
    assert "> You'll need: Cheesecloth, Two ricotta molds" in text


async def test_the_card_shows_tools_and_variations_as_notes(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    scenario.primary.queue_tool_call("find_recipe", {"query": RICOTTA, "section": "", "book": ""})
    (card,) = await scenario.say("Erin", f"How do I make the {RICOTTA}?")
    assert "You'll need\n> - Cheesecloth\n> - Two ricotta molds" in card
    assert "> Variations:\n> Add chopped herbs before molding." in card
    assert "Cheesecloth" not in card.split("You'll need")[0]


async def test_one_to_convert_is_found_only_by_its_name_and_labelled(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    book = recipes(scenario)
    assert "Parmesan" not in [m.recipe.name for m in book.find("a parmesan", book="cheese")]
    assert [m.recipe.name for m in book.find("Parmesan", book="cheese")] == ["Parmesan"]
    scenario.primary.queue_tool_call(
        "find_recipe", {"query": "Parmesan", "section": "", "book": "the cheese book"}
    )
    (card,) = await scenario.say("Erin", "Pull up the parmesan from the cheese book")
    assert card.startswith("Parmesan (Vegan cheese · not converted yet)\n")
    assert "Cook this" in scenario.last_buttons("Erin")


async def test_a_milk_is_a_base_recipe_for_its_own_cheeses(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    from themi_home.recipe_groceries import Ingredient

    groceries = scenario.app.services.maybe(keys.recipe_groceries)
    assert groceries is not None
    line = Ingredient("2 Cups Cashew Milk", "cashew milk", "2", "cups", "", False, False)
    sub = groceries._sub_recipe(line, set(), named(scenario, "Colibrie").book)
    assert sub is not None and sub.name == "Cashew Milk"
