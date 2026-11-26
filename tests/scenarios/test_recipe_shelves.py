"""RC8b: a recipe book of its own (Michael's vegan cheese recipes), read like the cookbook but
kept out of the way: not in meal ideas, found only when named, no new save buttons. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fixtures.cookbook import CHANA, recipe
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cookbook import account_id, choose
from tests.scenarios.test_cookbook import linked as linked  # a fixture
from tests.scenarios.test_cookbook_save import URL, show
from tests.scenarios.test_recipe_ideas import CHANA_PANTRY
from tests.scenarios.test_recipes_to_try import cook_and_finish
from tests.scenarios.test_triage import ERIN
from themi.ai.types import ToolResult
from themi.core import keys
from themi_home.recipes import Recipe, Recipes

CHEESE_ID = "1CheeseDocForVeganCheeseRecipesXyz"
CHEESE_LINK = f"https://docs.google.com/document/d/{CHEESE_ID}/edit"
COLIBRIE = recipe(
    "Colibrie",
    ["2 Cups Cashew Milk", "1 Cup cashews", "1 tsp salt"],
    ["Warm the Cashew Milk to 90°F.", "Culture it overnight.", "Form, salt and age."],
)
CHICKPEA_TOFU = [("H4", "Chickpea Tofu"), *CHANA[1:]]  # what the pantry covers, as Chana's
CASHEW_MILK = recipe("Cashew Milk", ["1 Cup cashews", "4 Cups water"], ["Blend.", "Strain."])
CHEESE_DOC = [
    ("T", "Madicen Family Cheese Recipes"),
    ("H1", "Cheeses"),
    *COLIBRIE,
    *CHICKPEA_TOFU,
    ("H1", "Milks"),
    *CASHEW_MILK,
]


def recipes(scenario: Scenario) -> Recipes:
    found = scenario.app.services.maybe(keys.recipes)
    assert found is not None
    return found


def named(scenario: Scenario, name: str, book: str = "") -> Recipe:
    return next(
        r for r in recipes(scenario).all() if r.name == name and (not book or r.book == book)
    )


async def choose_cheese(scenario: Scenario, site: httpx.AsyncClient) -> httpx.Response:
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post(
        f"/accounts/{account_id(scenario)}/cookbook",
        data={"csrf": csrf, "doc": CHEESE_LINK, "book": "new", "name": "Vegan cheese"},
    )
    assert response.status_code == 303
    return await site.get(response.headers["location"])


@pytest.fixture
async def cheese(scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient) -> FakeGdocs:
    """The cookbook chosen, and the vegan cheese recipes as a book of their own."""
    await choose(scenario, site)
    linked.add_doc(CHEESE_ID, "Madicen Family Cheese Recipes", CHEESE_DOC, shared_with=[ERIN])
    await choose_cheese(scenario, site)
    return linked


def key(scenario: Scenario) -> str:
    (shelf,) = recipes(scenario).shelves()
    return shelf.key


async def test_the_book_is_made_and_read_from_the_cookbook_page(
    scenario: Scenario, cheese: FakeGdocs, site: httpx.AsyncClient
) -> None:
    assert scenario.inbox("Erin")[-1] == "I've read 3 recipes from Vegan cheese."
    (shelf,) = recipes(scenario).shelves()
    assert (shelf.name, shelf.doc_id, shelf.role) == ("Vegan cheese", CHEESE_ID, "shelf")
    assert not (shelf.in_meal_ideas or shelf.found_unasked or shelf.save_button)
    colibrie = named(scenario, "Colibrie")
    assert colibrie.book == shelf.key and colibrie.key.startswith(f"{shelf.key}:")
    page = (await site.get(f"/accounts/{account_id(scenario)}/cookbook")).text
    assert "Vegan cheese: <strong>Madicen Family Cheese Recipes</strong>" in page
    assert '<option value="new">A new recipe book…</option>' in page


async def test_its_count_is_said_apart_from_the_cookbooks(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    items = [i.summary for i in recipes(scenario).open_items(scenario.member("Erin"))]
    assert items[0] == "The family cookbook has 16 recipes and charts (find_recipe)."
    assert items[1] == (
        "Vegan cheese (a separate recipe book, not the cookbook) has 3 recipes "
        "(find_recipe with book 'Vegan cheese')."
    )


async def test_a_name_thats_taken_or_a_doc_thats_another_book_is_refused(
    scenario: Scenario, cheese: FakeGdocs, site: httpx.AsyncClient
) -> None:
    page = (await choose_cheese(scenario, site)).text
    assert "There&#39;s a recipe book called Vegan cheese already." in page
    assert len(recipes(scenario).books()) == 3


async def test_meal_ideas_leave_it_out_unless_switched_on(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    pantry = scenario.app.services.maybe(keys.pantry)
    assert pantry is not None
    for item in CHANA_PANTRY:
        pantry.set_status(item, "plenty", source="said")
    ideas = scenario.app.services.maybe(keys.recipe_ideas)
    assert ideas is not None
    erin = scenario.member("Erin")
    picked = [i.recipe.name for i in ideas.pick(erin, limit=5)]
    assert "Chana Masala" in picked and "Chickpea Tofu" not in picked
    recipes(scenario).set_switches(key(scenario), meal_ideas=True, found_unasked=False,
                                   save_button=False)  # fmt: skip
    assert "Chickpea Tofu" in [i.recipe.name for i in ideas.pick(erin, limit=5)]


async def test_its_found_only_when_its_named(scenario: Scenario, cheese: FakeGdocs) -> None:
    book = recipes(scenario)

    def found(query: str, shelf: str = "") -> list[str]:
        return [m.recipe.name for m in book.find(query, charts=False, book=shelf)]

    unasked = found("something with cashews")
    assert "Alfredo Sauce" in unasked
    assert "Colibrie" not in unasked and "Cashew Milk" not in unasked
    assert "Cashew Milk" in found("a cheese recipe with cashews")  # "cheese" names the book
    assert found("Colibrie") == ["Colibrie"]  # its name, said exactly
    assert found("cashews", "Vegan cheese") == ["Cashew Milk"]  # only its own recipes
    assert found("salt", "the cheese book") == ["Colibrie"]
    assert "Alfredo Sauce" not in found("salt", "Vegan cheese")


async def test_naming_it_doesnt_narrow_to_its_sections(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    """ "Milks" is the cheese book's section, but "oat milk pancakes" is the cookbook's."""
    names = [m.recipe.name for m in recipes(scenario).find("pancakes", charts=False)]
    assert names[0] == "Pancakes"


async def test_a_web_recipes_card_keeps_its_two_save_buttons(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
    from tests.scenarios.test_cookbook_save import BROWNIES

    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    await show(scenario)
    buttons = scenario.last_buttons("Erin")
    assert "Save to cookbook" in buttons and not any("cheese" in b for b in buttons)
    recipes(scenario).set_switches(key(scenario), meal_ideas=False, found_unasked=False,
                                   save_button=True)  # fmt: skip
    await show(scenario)
    assert "Save to Vegan cheese" in scenario.last_buttons("Erin")


async def test_save_it_to_the_cheese_book_in_chat(scenario: Scenario, cheese: FakeGdocs) -> None:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page

    fake = FakeRecipeSite()
    fake.page(URL, recipe_page({
        "name": "Cashew Oat Milk",
        "recipeIngredient": ["1 cup cashews", "1 cup oats", "4 cups water"],
        "recipeInstructions": ["Blend everything.", "Strain."],
    }))  # fmt: skip
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    await show(scenario)
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "", "section": "", "where": "cheese"}
    )
    replies = await scenario.say("Erin", "Save that to the cheese book")
    assert replies[0].startswith("Here's how it would go in Vegan cheese:")
    assert 'Add "Cashew Oat Milk" to Vegan cheese under Milks' in scenario.inbox("Erin")[-1]
    await scenario.tap("Erin", "Go ahead")
    headings = [t for t, style in cheese.paragraphs(CHEESE_ID) if style == "HEADING_4"]
    assert headings[-1] == "Cashew Oat Milk"  # under Milks, the doc's last section
    from tests.fixtures.cookbook import COOKBOOK_ID

    assert ("Cashew Oat Milk", "HEADING_4") not in cheese.paragraphs(COOKBOOK_ID)
    saved = named(scenario, "Cashew Oat Milk")
    assert (saved.source, saved.book) == ("doc", key(scenario))


async def test_an_unknown_book_names_the_books_there_are(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
    from tests.scenarios.test_cookbook_save import BROWNIES

    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    await show(scenario)
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "", "section": "", "where": "bread book"}
    )
    scenario.primary.queue_text("Which book?")
    await scenario.say("Erin", "Save that to the bread book")
    result = [
        b.content
        for m in scenario.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ][-1]
    assert 'no recipe book "bread book"' in result
    assert "the cookbook" in result and "Vegan cheese" in result


async def test_a_step_names_its_own_books_cashew_milk(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    from tests.fixtures.cookbook import load

    milk = recipe("Cashew Milk", ["1 cup cashews"], ["Blend."])
    load(scenario.app.services, [("T", "Cookbook"), ("H1", "Ingredients"), *milk])
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    colibrie = named(scenario, "Colibrie")
    (linked_to,) = cooking.named_recipes(colibrie, "Warm the Cashew Milk to 90°F.")
    assert linked_to.book == key(scenario)


async def test_no_keeper_offer_after_cooking_one(scenario: Scenario, cheese: FakeGdocs) -> None:
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    await cook_and_finish(scenario, "Colibrie")
    wrap = cooking.state(scenario.member("Erin"))["wrap"]
    assert wrap is None or wrap["kind"] != "keep"


async def test_the_recipes_page_lists_it_under_its_own_chip(
    scenario: Scenario, cheese: FakeGdocs, site: httpx.AsyncClient
) -> None:
    main = (await site.get("/recipes")).text
    assert "Alfredo Sauce" in main and "Colibrie" not in main
    assert f'href="/recipes?book={key(scenario)}"' in main
    shelf = (await site.get(f"/recipes?book={key(scenario)}")).text
    assert "<h2>Vegan cheese</h2>" in shelf
    assert "Colibrie" in shelf and "Alfredo Sauce" not in shelf


async def test_its_switches_name_and_stopping_reading_it(
    scenario: Scenario, cheese: FakeGdocs, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    base = f"/accounts/{account_id(scenario)}/cookbook/books/{key(scenario)}"
    await site.post(base, data={"csrf": csrf, "found_unasked": "on"})
    (shelf,) = recipes(scenario).shelves()
    assert (shelf.found_unasked, shelf.in_meal_ideas, shelf.save_button) == (True, False, False)
    await site.post(base, data={"csrf": csrf, "action": "rename", "name": "Cheeses"})
    assert recipes(scenario).shelves()[0].name == "Cheeses"
    await site.post(base, data={"csrf": csrf, "action": "remove"})
    assert recipes(scenario).shelves() == []
    assert "Colibrie" not in [r.name for r in recipes(scenario).all()]
    assert recipes(scenario).doc_id is not None  # the cookbook is as it was


async def test_michael_asks_for_the_colibrie_and_cooks_it(
    scenario: Scenario, cheese: FakeGdocs
) -> None:
    """The prompt's scenario: "how do I make the Colibrie?" finds it, labelled, ready to
    cook; "what can we make for dinner?" offers nothing from it."""
    scenario.primary.queue_tool_call(
        "find_recipe", {"query": "Colibrie", "section": "", "book": ""}
    )
    (card,) = await scenario.say("Erin", "How do I make the Colibrie?")
    assert card.startswith("Colibrie (Vegan cheese · Cheeses)\n")
    assert f"In Vegan cheese: https://docs.google.com/document/d/{CHEESE_ID}/edit" in card
    assert "Cook this" in scenario.last_buttons("Erin")
    ideas = scenario.app.services.maybe(keys.recipe_ideas)
    assert ideas is not None
    picked = ideas.pick(scenario.member("Erin"), limit=5)
    assert all(not i.recipe.on_shelf for i in picked)
