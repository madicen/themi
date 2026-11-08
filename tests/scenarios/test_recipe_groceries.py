"""RC2a: what a recipe needs, onto the grocery list. The clock starts Wednesday 21 October
2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core import keys

BIRYANI = [
    ("shallots", False), ("garlic", False), ("ginger", False), ("cardamom", False),
    ("onion", False), ("mix vegetables", False), ("basmati rice", False),
    ("water", True), ("salt", True),
]  # fmt: skip


def items(rows: list[tuple[str, bool]]) -> dict:
    return {
        "lines": [
            {"n": n, "item": item, "quantity": "", "unit": "", "note": "", "optional": False,
             "staple": staple}
            for n, (item, staple) in enumerate(rows, start=1)
        ]
    }  # fmt: skip


@pytest.fixture
def cookbook(scenario: Scenario) -> Scenario:
    load(scenario.app.services)
    return scenario


def on_list(scenario: Scenario) -> list[str]:
    groceries = scenario.app.services.maybe(keys.groceries)
    assert groceries is not None
    return sorted(i.name for i in groceries.needed())


async def test_michael_adds_biryani_without_the_cardamom(
    cookbook: Scenario, fake_ourgroceries: FakeOurGroceries
) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani"], "scale": ""}
    )
    cookbook.primary.queue_structured(items(BIRYANI))
    (card,) = await cookbook.say("Husband", "Add the biryani to the grocery list")
    assert card.splitlines()[0] == "For Biryani, the grocery list would get 7:"
    assert "> · water (a staple)" in card and "> ✓ basmati rice" in card
    assert cookbook.last_buttons("Husband")[-2:] == ["Add 7", "Not now"]
    prompt = cookbook.primary.requests[-1].prompt
    assert '<data source="recipe">' in prompt and "6. 2 Cups mix vegetables" in prompt
    await cookbook.tap("Husband", "✓ cardamom")
    assert "> · cardamom" in cookbook.edits("Husband")[-1]["text"]
    await cookbook.tap("Husband", "Add 6")
    assert cookbook.edits("Husband")[-1]["text"].startswith("Added to the grocery list: shallots,")
    assert on_list(cookbook) == [
        "basmati rice", "garlic", "ginger", "mix vegetables", "onion", "shallots",
    ]  # fmt: skip
    await cookbook.run_periodic("groceries.mirror")
    assert sorted(fake_ourgroceries.values()) == [
        "basmati rice", "garlic", "ginger", "mix vegetables", "onion", "shallots",
    ]  # fmt: skip


async def test_lines_read_once_are_kept(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani"], "scale": ""}
    )
    cookbook.primary.queue_structured(items(BIRYANI))
    await cookbook.say("Husband", "Add the biryani to the grocery list")
    calls = len(cookbook.primary.requests)
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani"], "scale": ""}
    )
    await cookbook.say("Erin", "Put what we need for biryani on the list")
    assert len(cookbook.primary.requests) == calls + 1  # the tool round only, no reading


async def test_no_model_reads_by_rule(cookbook: Scenario) -> None:
    from themi.ai.errors import PermanentError

    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["alfredo sauce"], "scale": ""}
    )
    cookbook.primary.queue_error(PermanentError("no key"), op="structured")
    cookbook.fallback.queue_error(PermanentError("no key"), op="structured")
    (card,) = await cookbook.say("Erin", "Add the alfredo sauce to the grocery list")
    assert "> ✓ cashews" in card and "> · salt (a staple)" in card
    assert "> · black pepper (a staple)" in card


async def test_the_pantry_has_plenty(cookbook: Scenario) -> None:
    pantry = cookbook.app.services.maybe(keys.pantry)
    assert pantry is not None
    pantry.set_status("garlic", "plenty", source="said")
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani"], "scale": ""}
    )
    cookbook.primary.queue_structured(items(BIRYANI))
    (card,) = await cookbook.say("Husband", "Add the biryani to the grocery list")
    assert "> · garlic (the pantry has plenty)" in card


async def test_two_recipes_one_card(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani", "chana masala"], "scale": ""}
    )
    cookbook.primary.queue_structured(items(BIRYANI))
    cookbook.primary.queue_structured(
        items([("dried chickpeas", False), ("water", True), ("oil", False), ("onion", False)])
    )
    (card,) = await cookbook.say("Erin", "Get what we need for biryani and chana masala")
    assert card.startswith("For Biryani and Chana Masala")
    assert "> ✓ onion (for both)" in card
    assert card.count("> ✓ onion") == 1


async def test_a_base_recipe_in_the_cookbook_is_offered(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["lasagna"], "scale": ""}
    )
    cookbook.primary.queue_structured(
        items([("bechamel sauce", False), ("olive oil", False), ("onion", False),
               ("peeled tomatoes", False), ("lasagna sheets", False), ("parsley", False)])
    )  # fmt: skip
    (card,) = await cookbook.say("Erin", "Add the lasagna to the grocery list")
    assert "Bechamel Sauce is in the cookbook too." in card
    cookbook.primary.queue_structured(
        items([("onion", False), ("cloves", False), ("bay leaf", False), ("soy milk", False),
               ("butter", False), ("flour", False), ("nutmeg", False), ("salt", True)])
    )  # fmt: skip
    await cookbook.tap("Erin", "Use the recipe: Bechamel Sauce")
    edited = cookbook.edits("Erin")[-1]["text"]
    assert edited.startswith("For Lasagna and Bechamel Sauce")
    assert "> ✓ soy milk" in edited and "> ✓ onion (for both)" in edited
    assert "is in the cookbook too" not in edited


async def test_already_on_the_list(cookbook: Scenario) -> None:
    groceries = cookbook.app.services.maybe(keys.groceries)
    assert groceries is not None
    cookbook.primary.queue_tool_call("add_to_grocery_list", {"items": ["garlic"]})
    cookbook.primary.queue_text("Added.")
    await cookbook.say("Erin", "Add garlic to the list")
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani"], "scale": ""}
    )
    cookbook.primary.queue_structured(items(BIRYANI))
    await cookbook.say("Husband", "Add the biryani to the grocery list")
    await cookbook.tap("Husband", "Add 7")
    text = cookbook.edits("Husband")[-1]["text"]
    assert "Already on the list or waiting: garlic." in text


async def test_not_now_leaves_the_list(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["biryani"], "scale": ""}
    )
    cookbook.primary.queue_structured(items(BIRYANI))
    await cookbook.say("Husband", "Add the biryani to the grocery list")
    await cookbook.tap("Husband", "Not now")
    assert cookbook.edits("Husband")[-1]["text"] == "Left the grocery list as it is."
    assert on_list(cookbook) == []


async def test_from_the_recipe_card(cookbook: Scenario) -> None:
    """RC1b's scenario: Erin asks for the ranch dressing and taps [Add to grocery list]."""
    cookbook.primary.queue_tool_call("find_recipe", {"query": "ranch dressing", "section": ""})
    await cookbook.say("Erin", "Can you pull up our ranch dressing?")
    assert "Add to grocery list" in cookbook.last_buttons("Erin")
    cookbook.primary.queue_structured(
        items([("silken tofu", False), ("water", True), ("olive oil", False), ("garlic", False),
               ("onion powder", False), ("salt", True), ("apple cider vinegar", False),
               ("nutritional yeast", False), ("fresh herbs", False), ("peppercorns", False)])
    )  # fmt: skip
    (card,) = await cookbook.tap("Erin", "Add to grocery list")
    assert card.startswith("For Silken Tofu Ranch Dressing, the grocery list would get 7:")
    assert "> · olive oil (the pantry has plenty)" in card  # a family staple


async def test_an_unclear_name_asks(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["chocolate peanut butter bars"], "scale": ""}
    )
    cookbook.primary.queue_text("There are two: which one?")
    await cookbook.say("Erin", "Add the chocolate peanut butter bars to the list")
    result = [
        b.content
        for m in cookbook.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ]
    assert any("could be: Chocolate Peanut Butter Bars" in r for r in result)


# ----- RC2b: scaling --------------------------------------------------------------------

PANCAKES = [
    ("white whole wheat flour", False), ("all-purpose flour", False), ("baking powder", False),
    ("cinnamon", False), ("kosher salt", True), ("almond milk", False), ("applesauce", False),
    ("vanilla extract", False),
]  # fmt: skip


async def test_double_the_pancakes(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["pancakes"], "scale": "double"}
    )
    cookbook.primary.queue_structured(items(PANCAKES))
    (card,) = await cookbook.say("Erin", "Double the pancakes and put them on the grocery list")
    lines = card.splitlines()
    assert lines[0] == "For a double batch of Pancakes, the grocery list would get 6:"
    assert "> ✓ white whole wheat flour: 3 Cups (360 grams)" in lines
    assert "> ✓ baking powder: 2 Tbsp + 2 tsp (40g)" in lines
    assert "> ✓ almond milk: 4 Cups" in lines
    assert "Amounts in the steps are for the original; the scaled ones are here." in lines
    assert "Pan size and times may need changing." in lines  # baking powder


async def test_for_six_asks_how_many_it_makes_once(cookbook: Scenario) -> None:
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["chana masala"], "scale": "for 6"}
    )
    cookbook.primary.queue_text("How many does the chana masala make as written?")
    replies = await cookbook.say("Erin", "Add the chana masala for 6 to the grocery list")
    assert replies == ["How many does the chana masala make as written?"]
    result = [
        b.content
        for m in cookbook.primary.last_request.messages
        for b in m.content
        if isinstance(b, ToolResult)
    ][-1]
    assert "doesn't say how many it makes" in result and "set_recipe_yield" in result
    cookbook.primary.queue_tool_call("set_recipe_yield", {"recipe": "chana masala", "makes": 4})
    cookbook.primary.queue_tool_call(
        "add_recipe_to_grocery_list", {"recipes": ["chana masala"], "scale": "for 6"}
    )
    cookbook.primary.queue_structured(
        items([("dried chickpeas", False), ("water", True), ("oil", False), ("onion", False)])
    )
    (card,) = await cookbook.say("Erin", "It makes 4")
    assert card.startswith("For Chana Masala for 6, the grocery list would get")
    assert "> ✓ dried chickpeas: 3 Cups" in card
    chana = cookbook.app.db.one("SELECT yield_said FROM recipes WHERE name = 'Chana Masala'")
    assert chana == {"yield_said": 4}  # kept: not asked again
