"""RC5: a web recipe they liked, added to the family cookbook doc after a yes. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fakes.recipe_site import FakeRecipeSite, recipe_page
from tests.fixtures.cookbook import COOKBOOK_ID
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cookbook import choose
from tests.scenarios.test_cookbook import linked as linked  # a fixture
from themi.ai.types import ToolResult
from themi.core import keys

URL = "https://plants.example/vegan-brownies"
BROWNIES = {
    "name": "Vegan Brownies",
    "recipeIngredient": ["1 cup flour", "½ cup cocoa", "1 cup sugar"],
    "recipeInstructions": ["Preheat the oven to 350°F.", "Mix and bake for 25 minutes."],
}


@pytest.fixture
async def ready(
    scenario: Scenario,
    linked: FakeGdocs,
    site: httpx.AsyncClient,
) -> FakeGdocs:
    await choose(scenario, site)
    fake = FakeRecipeSite()
    fake.page(URL, recipe_page(BROWNIES))
    fake.page("https://plants.example/odd", recipe_page({**BROWNIES, "name": "Mystery Thing"}))
    scenario.app.services.maybe(keys.web_recipes).reader = fake.reader()  # type: ignore[union-attr]
    return linked


async def show(scenario: Scenario, url: str = URL) -> str:
    scenario.primary.queue_tool_call("recipe_from_link", {"url": url})
    (card,) = await scenario.say("Erin", url)
    return card


def entry_in_doc(fake: FakeGdocs) -> list[tuple[str, str]]:
    paragraphs = fake.paragraphs(COOKBOOK_ID)
    start = paragraphs.index(("Vegan Brownies", "HEADING_4"))
    return paragraphs[start : start + 10]


async def test_a_liked_recipe_goes_into_the_doc(scenario: Scenario, ready: FakeGdocs) -> None:
    await show(scenario)
    assert "Save to cookbook" in scenario.last_buttons("Erin")
    await scenario.tap("Erin", "Save to cookbook")
    preview, card = scenario.inbox("Erin")[-2:]
    assert preview.splitlines()[:3] == [
        "Here's how it would go in the cookbook, under Desserts:",
        "> Vegan Brownies",
        "> Ingredients",
    ]
    assert "Vegan Brownies" in card and "cookbook under Desserts" in card
    assert ("Vegan Brownies", "HEADING_4") not in ready.paragraphs(COOKBOOK_ID)  # not yet
    await scenario.tap("Erin", "Go ahead")
    assert entry_in_doc(ready) == [
        ("Vegan Brownies", "HEADING_4"),
        ("Ingredients", "HEADING_5"),
        ("1 cup flour", "NORMAL_TEXT"),
        ("½ cup cocoa", "NORMAL_TEXT"),
        ("1 cup sugar", "NORMAL_TEXT"),
        ("Instructions", "HEADING_5"),
        ("Preheat the oven to 350°F.", "NORMAL_TEXT"),
        ("Mix and bake for 25 minutes.", "NORMAL_TEXT"),
        (f"Source: plants.example ({URL})", "NORMAL_TEXT"),
        ("-----", "NORMAL_TEXT"),
    ]
    after = ready.paragraphs(COOKBOOK_ID)
    start = after.index(("Vegan Brownies", "HEADING_4"))
    end = after.index(("-----", "NORMAL_TEXT"), start)
    assert after[end + 1] == ("Sides", "HEADING_1")  # at the end of Desserts
    row = scenario.app.db.one(
        "SELECT source, section, key FROM recipes WHERE name = 'Vegan Brownies'"
    )
    assert row is not None and row["source"] == "doc" and row["section"] == "Desserts"
    assert row["key"].startswith("h.")
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM recipes WHERE name = 'Vegan Brownies'") == 1
    scenario.primary.queue_tool_call("find_recipe", {"query": "vegan brownies", "section": ""})
    (found,) = await scenario.say("Husband", "Pull up the vegan brownies")
    assert found.startswith("Vegan Brownies (Desserts)")
    assert (
        f"In the cookbook: https://docs.google.com/document/d/{COOKBOOK_ID}/edit#heading=h."
        in found
    )


async def test_an_edit_in_between_is_read_again(scenario: Scenario, ready: FakeGdocs) -> None:
    await show(scenario)
    await scenario.tap("Erin", "Save to cookbook")
    ready.edits_before_write = 1
    await scenario.tap("Erin", "Go ahead")
    assert entry_in_doc(ready)[0] == ("Vegan Brownies", "HEADING_4")


async def test_a_doc_that_keeps_changing_isnt_written(scenario: Scenario, ready: FakeGdocs) -> None:
    await show(scenario)
    await scenario.tap("Erin", "Save to cookbook")
    ready.edits_before_write = 2
    await scenario.tap("Erin", "Go ahead")
    assert ("Vegan Brownies", "HEADING_4") not in ready.paragraphs(COOKBOOK_ID)
    action = scenario.app.db.one(
        "SELECT status FROM pending_actions WHERE category = 'cookbook_add'"
    )
    assert action == {"status": "failed"}


async def test_an_unclear_section_asks(scenario: Scenario, ready: FakeGdocs) -> None:
    await show(scenario, "https://plants.example/odd")
    await scenario.tap("Erin", "Save to cookbook")
    assert scenario.inbox("Erin")[-1] == "Which part of the cookbook should Mystery Thing go in?"
    assert scenario.last_buttons("Erin")[:3] == [
        "Under Ingredients",
        "Under Breakfast",
        "Under Entrees",
    ]
    await scenario.tap("Erin", "Under Snacks")
    assert scenario.inbox("Erin")[-2].startswith(
        "Here's how it would go in the cookbook, under Snacks:"
    )


async def test_after_cooking_a_web_recipe(scenario: Scenario, ready: FakeGdocs) -> None:
    await show(scenario)
    cooking = scenario.app.services.maybe(keys.cooking)
    recipes = scenario.app.services.maybe(keys.recipes)
    assert cooking is not None and recipes is not None
    brownies = next(r for r in recipes.all(source="web"))
    scenario.primary.queue_structured(
        {"lines": [{"n": n, "item": i, "quantity": "", "unit": "", "note": "",
                    "optional": False, "staple": False}
                   for n, i in enumerate(["flour", "cocoa", "sugar"], start=1)]}
    )  # fmt: skip
    session = await cooking.start(scenario.member("Erin"), brownies)
    await cooking.finish(session)
    last = scenario.edits("Erin")[-1]
    assert last["text"] == "Vegan Brownies, all done. Enjoy it!\nKeep this one in the cookbook?"
    assert [b["text"] for row in last["reply_markup"]["inline_keyboard"] for b in row] == [
        "Save to cookbook", "Not now",
    ]  # fmt: skip


async def test_saying_so_in_chat(scenario: Scenario, ready: FakeGdocs) -> None:
    await show(scenario)
    scenario.primary.queue_tool_call("save_recipe_to_cookbook", {"recipe": "", "section": ""})
    replies = await scenario.say("Erin", "We liked that one, add it to the cookbook")
    assert replies[0].startswith("Here's how it would go in the cookbook, under Desserts:")


async def test_a_cookbook_recipe_is_changed_in_the_doc(
    scenario: Scenario, ready: FakeGdocs
) -> None:
    scenario.primary.queue_tool_call(
        "save_recipe_to_cookbook", {"recipe": "pancakes", "section": ""}
    )
    scenario.primary.queue_text("The pancakes are in the cookbook already; edit them in the doc.")
    await scenario.say("Erin", "Add the pancakes to the cookbook")
    result = [
        b.content
        for m in scenario.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ][-1]
    assert "in the cookbook already" in result and "#heading=h." in result
