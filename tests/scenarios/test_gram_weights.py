"""GW2: recipes "With grams" from the family's weights guide: the cook screen, the recipe page
and the recipe picture; and weights a recipe states, added to the guide. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.fixtures.weights_guide import WEIGHTS_GUIDE
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from tests.unit.test_day_card import golden
from themi.core import keys
from themi_home.cooking import Cooking, CookingPreferences
from themi_home.gram_weights import GramWeights, key
from themi_home.recipe_card import card_svg
from themi_home.recipes import Recipe

EXTRA = "\n1 Cup Cashews: Weight in Grams 130g"


def weights_guide(scenario: Scenario, text: str = WEIGHTS_GUIDE + EXTRA) -> int:
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    erin = scenario.member("Erin")
    return guides.save(erin, "Weights of Common Ingredients", text, personal=False).id


def with_grams(scenario: Scenario, name: str = "Erin") -> None:
    member = scenario.member(name)
    scenario.app.store.save_preferences(member, member.id, CookingPreferences,
                                        cooking_units="grams")  # fmt: skip


def weights(scenario: Scenario) -> GramWeights:
    found = scenario.app.services.maybe(GramWeights)
    assert found is not None
    return found


def recipe(scenario: Scenario, name: str) -> Recipe:
    load(scenario.app.services)
    return next(r for r in scenario.app.services.get(keys.recipes).all() if r.name == name)


async def test_the_cook_screen_with_grams(scenario: Scenario) -> None:
    weights_guide(scenario)
    alfredo = recipe(scenario, "Alfredo Sauce")
    cooking = scenario.app.services.get(Cooking)
    erin = scenario.member("Erin")
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(erin, alfredo)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await cooking.advance(session, action)
    drawer = [a["line"] for a in cooking.state(erin)["amounts"]["groups"][0]["lines"]]
    assert "½ tsp salt" in drawer  # as written: Erin hasn't chosen grams
    with_grams(scenario)
    drawer = [a["line"] for a in cooking.state(erin)["amounts"]["groups"][0]["lines"]]
    assert drawer[0] == "1 Cup (130 g) cashews, soaked in water for at least 10 minutes"
    assert "½ tsp (3 g) salt" in drawer  # from the guide
    assert "¼ tsp (0.5 g) onion powder" not in drawer  # 0.6 g: under 1 g, as written
    assert "¼ tsp onion powder" in drawer
    assert "1 tsp mild/yellow miso" in drawer  # not in the guide: as written
    husband = scenario.member("Husband")
    cooking.state(husband)  # his own units: as written
    assert "½ tsp salt" in [a["line"] for a in cooking.state(husband).get("amounts", {}).get(
        "groups", [{"lines": [{"line": "½ tsp salt"}]}])[0]["lines"]]  # fmt: skip


async def test_the_recipe_page_with_grams(scenario: Scenario, site: httpx.AsyncClient) -> None:
    weights_guide(scenario)
    pancakes = recipe(scenario, "Pancakes")
    await sign_in(scenario, site, "Erin")
    page = (await site.get(f"/recipes/{pancakes.id}")).text
    assert "1 tsp cinnamon" in page and "(120 g) all-purpose flour" not in page
    with_grams(scenario)
    page = (await site.get(f"/recipes/{pancakes.id}")).text
    assert "1 Cup (120 g) all-purpose flour" in page  # the recipe's own weight
    assert "1 Tbsp + 1 tsp (20 g) baking powder" in page
    doubled = (await site.get(f"/recipes/{pancakes.id}?scale=double")).text
    assert "2 Cups (240 g) all-purpose flour" in doubled


async def test_the_recipe_picture_with_grams(scenario: Scenario) -> None:
    weights_guide(scenario)
    pancakes = recipe(scenario, "Pancakes")
    erin = scenario.member("Erin")
    from themi_home.gram_weights import viewer_lines

    with_grams(scenario)
    svg = card_svg(pancakes, "light", viewer_lines(scenario.app.services, erin.id))
    golden("recipe_grams", svg)
    assert "(20 g) baking powder" in svg
    assert card_svg(pancakes) == card_svg(pancakes, "light", None)  # as written by default


async def test_a_recipes_own_weights_join_the_guide(scenario: Scenario) -> None:
    weights_guide(scenario, WEIGHTS_GUIDE)
    pancakes = recipe(scenario, "Pancakes")
    erin = scenario.member("Erin")
    added = await weights(scenario).learn(erin, [i.text for i in pancakes.ingredients])
    assert added == ["white whole wheat flour", "unsweetened applesauce"]
    book = weights(scenario).book()
    assert book.grams("white whole wheat flour", 1, "cup") == 120
    assert book.grams("all-purpose flour", 1, "cup") == 120  # the guide had flour: kept
    meta = weights(scenario).meta(key("white whole wheat flour"))
    assert meta is not None and meta["source"] == "recipe"
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    text = guides.household()[0].text
    assert text.endswith("1 Cup White Whole Wheat Flour: Weight in Grams 120g\n"
                         "1 Cup Unsweetened Applesauce: Weight in Grams 280g")  # fmt: skip
    assert await weights(scenario).learn(erin, [i.text for i in pancakes.ingredients]) == []


async def test_with_no_weights_guide_one_starts(scenario: Scenario) -> None:
    pancakes = recipe(scenario, "Pancakes")
    erin = scenario.member("Erin")
    await weights(scenario).learn(erin, [pancakes.ingredients[0].text])
    guide = weights(scenario).guide()
    assert guide is not None and guide.name == "Weights of Common Ingredients"
    assert guide.text.splitlines()[1] == "1 Cup White Whole Wheat Flour: Weight in Grams 120g"


@pytest.mark.parametrize("units", ["written", "grams"])
async def test_the_guides_page_shows_a_recipes_weight(
    scenario: Scenario, site: httpx.AsyncClient, units: str
) -> None:
    weights_guide(scenario, WEIGHTS_GUIDE)
    pancakes = recipe(scenario, "Pancakes")
    await weights(scenario).learn(scenario.member("Erin"), [pancakes.ingredients[0].text])
    await sign_in(scenario, site, "Erin")
    assert "from a recipe" in (await site.get("/guides")).text


async def test_the_job_reads_each_recipe_once(scenario: Scenario) -> None:
    weights_guide(scenario, WEIGHTS_GUIDE)
    recipe(scenario, "Pancakes")
    await weights(scenario).look_up()
    book = weights(scenario).book()
    assert book.grams("cashews", 1, "cup") == 130  # from the Alfredo sauce
    assert book.grams("white whole wheat flour", 1, "cup") == 120  # from the pancakes
    seen = scenario.app.db.scalar("SELECT COUNT(*) FROM gram_weights_seen")
    actions = scenario.app.db.scalar("SELECT COUNT(*) FROM pending_actions")
    await weights(scenario).look_up()
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM pending_actions") == actions
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM gram_weights_seen") == seen
