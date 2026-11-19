"""F49h (Michael's idea #224): recipes they want to try, kept in their own Google Doc,
"Recipes to try", read like the cookbook. Found, shown and cooked like any recipe, labelled
"to try", and not counted as the cookbook's. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fixtures.cookbook import COOKBOOK_ID, recipe
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cookbook import account_id, choose
from tests.scenarios.test_cookbook import linked as linked  # a fixture
from tests.scenarios.test_cookbook_save import URL, show
from tests.scenarios.test_triage import ERIN
from themi.ai.types import ToolResult
from themi.core import keys
from themi_home.recipes import NO_TRY_DOC_TEXT, Recipes

TRY_ID = "1TryDocForRecipesWeWantToTryXyz"
TRY_LINK = f"https://docs.google.com/document/d/{TRY_ID}/edit"
SNOWY = recipe(
    "Snowy Earthquake Cookie",
    ["¾ (150g) Cup sugar", "⅓ (70g) Cup canola oil", "1 Cup powdered sugar"],
    ["Mix everything.", "Bake at 350°F for 12 minutes."],
)
PANCAKES_TOO = recipe("Pancakes", ["1 cup flour", "1 cup oat milk"], ["Mix.", "Fry."])


def recipes(scenario: Scenario) -> Recipes:
    found = scenario.app.services.maybe(keys.recipes)
    assert found is not None
    return found


async def choose_try(
    scenario: Scenario, site: httpx.AsyncClient, doc: str = TRY_LINK
) -> httpx.Response:
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post(
        f"/accounts/{account_id(scenario)}/cookbook",
        data={"csrf": csrf, "doc": doc, "book": "to_try"},
    )
    assert response.status_code == 303
    return await site.get(response.headers["location"])


@pytest.fixture
async def both(scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient) -> FakeGdocs:
    """The cookbook chosen, and Recipes to try beside it (shared through Erin's account)."""
    await choose(scenario, site)
    linked.add_doc(
        TRY_ID, "Recipes to try", [("T", "Recipes to try"), *SNOWY, *PANCAKES_TOO],
        shared_with=[ERIN],
    )  # fmt: skip
    await choose_try(scenario, site)
    return linked


async def test_the_try_doc_is_chosen_and_read(
    scenario: Scenario, both: FakeGdocs, site: httpx.AsyncClient
) -> None:
    assert scenario.inbox("Erin")[-1] == "I've read 2 recipes from Recipes to try."
    trying = [r for r in recipes(scenario).all() if r.to_try]
    assert [r.name for r in trying] == ["Snowy Earthquake Cookie", "Pancakes"]
    assert all(r.key.startswith("try:") for r in trying)
    assert recipes(scenario).settings("to_try")["doc_id"] == TRY_ID
    assert recipes(scenario).doc_id == COOKBOOK_ID  # the cookbook is as it was
    page = (await site.get(f"/accounts/{account_id(scenario)}/cookbook")).text
    assert "Recipes to try: <strong>Recipes to try</strong>" in page


async def test_the_cookbooks_count_leaves_them_out(scenario: Scenario, both: FakeGdocs) -> None:
    items = [i.summary for i in recipes(scenario).open_items(scenario.member("Erin"))]
    assert items[0] == "The family cookbook has 16 recipes and charts (find_recipe)."
    assert items[1].startswith("Recipes to try (a separate doc, not the cookbook) has 2")


async def test_one_is_found_shown_and_labelled_to_try(scenario: Scenario, both: FakeGdocs) -> None:
    scenario.primary.queue_tool_call("find_recipe", {"query": "snowy earthquake", "section": ""})
    (card,) = await scenario.say("Erin", "Pull up the snowy earthquake cookies")
    assert card.startswith("Snowy Earthquake Cookie (to try)\n")
    assert f"In Recipes to try: https://docs.google.com/document/d/{TRY_ID}/edit" in card
    assert "Cook this" in scenario.last_buttons("Erin")


async def test_the_cookbook_comes_first_for_the_same_name(
    scenario: Scenario, both: FakeGdocs
) -> None:
    (first, second, *_) = recipes(scenario).find("pancakes", charts=False)
    assert (first.recipe.to_try, second.recipe.to_try) == (False, True)


async def test_two_matches_say_which_docs(scenario: Scenario, both: FakeGdocs) -> None:
    scenario.primary.queue_tool_call("find_recipe", {"query": "pancakes", "section": ""})
    replies = await scenario.say("Erin", "What's the pancake recipe?")
    assert replies == ["From the cookbook and Recipes to try:"]
    assert scenario.last_buttons("Erin")[:2] == ["Pancakes", "Pancakes (to try)"]


async def test_the_recipes_page_has_them_under_their_own_heading(
    scenario: Scenario, both: FakeGdocs, site: httpx.AsyncClient
) -> None:
    page = (await site.get("/recipes")).text
    heading = page.index("<h2>To try</h2>")
    assert page.index("Snowy Earthquake Cookie") > heading
    assert page.index("Alfredo Sauce") < heading


async def test_the_same_doc_cant_be_both(
    scenario: Scenario, both: FakeGdocs, site: httpx.AsyncClient
) -> None:
    from tests.fixtures.cookbook import LINK

    page = await choose_try(scenario, site, LINK)
    assert "That doc is the cookbook already; pick another one." in page.text
    assert recipes(scenario).try_doc_id == TRY_ID


# ----- saving one to try ---------------------------------------------------------------------


@pytest.fixture
async def site_recipe(scenario: Scenario, both: FakeGdocs) -> FakeGdocs:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
    from tests.scenarios.test_cookbook_save import BROWNIES

    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    return both


async def test_a_web_recipe_saved_to_try_goes_into_the_try_doc(
    scenario: Scenario, site_recipe: FakeGdocs
) -> None:
    await show(scenario)
    assert "Save to try" in scenario.last_buttons("Erin")
    await scenario.tap("Erin", "Save to try")
    preview, card = scenario.inbox("Erin")[-2:]
    assert preview.splitlines()[:2] == ["Here's how it would go in Recipes to try:",
                                        "> Vegan Brownies"]  # fmt: skip
    assert "Recipes to try" in card
    await scenario.tap("Erin", "Go ahead")
    assert ("Vegan Brownies", "HEADING_4") in site_recipe.paragraphs(TRY_ID)
    assert ("Vegan Brownies", "HEADING_4") not in site_recipe.paragraphs(COOKBOOK_ID)
    brownies = next(r for r in recipes(scenario).all() if r.name == "Vegan Brownies")
    assert (brownies.source, brownies.book) == ("doc", "to_try")
    assert brownies.key.startswith("try:")


async def test_save_it_to_try_in_chat(scenario: Scenario, site_recipe: FakeGdocs) -> None:
    await show(scenario)
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "", "section": "", "where": "to_try"}
    )
    replies = await scenario.say("Erin", "Let's save that one to try")
    assert replies[0].startswith("Here's how it would go in Recipes to try:")


async def test_without_a_try_doc_it_says_where_to_choose_one(
    scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient
) -> None:
    from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
    from tests.scenarios.test_cookbook_save import BROWNIES

    await choose(scenario, site)
    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    await show(scenario)
    assert "Save to try" not in scenario.last_buttons("Erin")
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "", "section": "", "where": "to_try"}
    )
    scenario.primary.queue_text("There's no try doc yet.")
    await scenario.say("Erin", "Save that one to try")
    result = [
        b.content
        for m in scenario.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ][-1]
    assert result.startswith(NO_TRY_DOC_TEXT)
