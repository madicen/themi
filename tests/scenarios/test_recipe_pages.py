"""RC6: the website's Recipes page and the kitchen view. The clock starts Wednesday 21
October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.core import keys


@pytest.fixture
async def signed_in(scenario: Scenario, site: httpx.AsyncClient) -> str:
    load(scenario.app.services)
    return await sign_in(scenario, site, "Erin")


def recipe_id(scenario: Scenario, name: str) -> int:
    return int(scenario.app.db.scalar("SELECT id FROM recipes WHERE name = ?", (name,)))


async def test_the_list_search_and_sections(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    page = await site.get("/recipes")
    assert page.status_code == 200
    assert "Alfredo Sauce" in page.text and "Roasted Vegetables" in page.text
    assert "Need a look" in page.text and "two Ingredients headings" in page.text
    found = await site.get("/recipes", params={"q": "chickpeas"})
    assert "Chana Masala" in found.text and "Alfredo Sauce" not in found.text
    desserts = await site.get("/recipes", params={"section": "Desserts"})
    assert "Ube Gelato" in desserts.text and "Pancakes" not in desserts.text


async def test_a_recipe_scaled(scenario: Scenario, site: httpx.AsyncClient, signed_in: str) -> None:
    pancakes = recipe_id(scenario, "Pancakes")
    page = await site.get(f"/recipes/{pancakes}", params={"scale": "double"})
    assert "3 Cups (360 grams) white whole wheat flour" in page.text
    assert "A double batch of" in page.text
    assert "Pan size and times may need changing." in page.text
    asked = await site.get(f"/recipes/{pancakes}", params={"scale": "for 6"})
    assert "doesn&#39;t say how many it makes" in asked.text


async def test_add_to_grocery_list_sends_the_card(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    alfredo = recipe_id(scenario, "Alfredo Sauce")
    scenario.primary.queue_structured(
        {"lines": [{"n": n, "item": i, "quantity": "", "unit": "", "note": "", "optional": False,
                    "staple": i in ("water", "salt", "black pepper")}
                   for n, i in enumerate(["cashews", "water", "garlic", "miso", "lemon juice",
                                          "salt", "nutmeg", "onion powder", "black pepper"], 1)]}
    )  # fmt: skip
    response = await site.post(
        f"/recipes/{alfredo}/groceries", data={"csrf": signed_in, "scale": ""}
    )
    assert response.status_code == 303
    assert scenario.inbox("Erin")[-1].startswith("For Alfredo Sauce, the grocery list would get")


async def test_the_kitchen_view_moves_the_chat_card(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    ranch = recipe_id(scenario, "Silken Tofu Ranch Dressing")
    items = ["silken tofu", "water", "olive oil", "garlic", "onion powder", "salt",
             "apple cider vinegar", "nutritional yeast", "fresh herbs", "peppercorns"]  # fmt: skip
    scenario.primary.queue_structured(
        {"lines": [{"n": n, "item": i, "quantity": "", "unit": "", "note": "", "optional": False,
                    "staple": False} for n, i in enumerate(items, 1)]}
    )  # fmt: skip
    await site.post(f"/recipes/{ranch}/cook", data={"csrf": signed_in, "scale": ""})
    view = await site.get("/recipes/kitchen")
    assert "What it uses" not in view.text and "1 package silken tofu (12.3oz) firm" in view.text
    assert scenario.inbox("Erin")[-1].startswith("Cooking Silken Tofu Ranch Dressing. What it uses")
    session = scenario.app.services.maybe(keys.cooking).current(scenario.member("Erin"))  # type: ignore[union-attr]
    assert session is not None
    scenario.primary.queue_structured({"jobs": []})
    moved = await site.post(
        f"/recipes/kitchen/{session.id}/next", data={"csrf": signed_in},
        headers={"HX-Request": "true"},
    )  # fmt: skip
    assert "Blend ingredients together until smooth" in moved.text  # the fragment
    assert scenario.edits("Erin")[-1]["text"].startswith(
        "Silken Tofu Ranch Dressing: step 1 of 1"
    )  # the chat's card moved too
    state = await site.get("/recipes/kitchen/state")
    assert 'hx-trigger="every 5s"' in state.text


async def test_only_family_members(scenario: Scenario, site: httpx.AsyncClient) -> None:
    load(scenario.app.services)
    page = await site.get("/recipes", follow_redirects=False)
    assert page.status_code in (302, 303, 401)
    assert "Alfredo Sauce" not in page.text


async def test_the_diet_setting(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    await site.post("/recipes/diet", data={"csrf": signed_in})
    assert scenario.app.services.maybe(keys.recipes).diet() == ""  # type: ignore[union-attr]
    await site.post("/recipes/diet", data={"csrf": signed_in, "vegan": "on"})
    assert scenario.app.services.maybe(keys.recipes).diet() == "vegan"  # type: ignore[union-attr]


async def test_it_is_on_the_more_page(
    scenario: Scenario, site: httpx.AsyncClient, signed_in: str
) -> None:
    more = await site.get("/more")
    assert 'href="/recipes"' in more.text
