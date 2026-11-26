"""RC8c: the vegan cheese doc, read as it's laid out (sections a level down, dividers styled
as headings, Tools apart from ingredients, Variations as notes, drafts labelled)."""

from __future__ import annotations

from tests.fixtures.cheese import cheese_document
from tests.fixtures.cookbook import document
from themi_home import cookbook as book


def parse() -> book.Cookbook:
    return book.parse(cheese_document())


def named(cookbook: book.Cookbook, name: str) -> book.ParsedRecipe:
    return next(r for r in cookbook.recipes if r.name == name)


def test_heading_2_is_a_section_when_heading_1_is_only_the_title() -> None:
    cookbook = parse()
    places = {r.name: (r.section, r.subsection) for r in cookbook.recipes}
    assert places["Rejuvelac Cultured Almond Ricotta"] == ("Cheeses", "Fresh")
    assert places["Petite Soy"] == ("Cheeses", "Aged")
    assert places["Cashew Milk"] == ("Milks", "")
    assert places["Making and Using Brine"] == ("Appendix", "")
    assert [name for name, _ in cookbook.sections] == [
        "Cheeses", "Milks", "Dairy Recipes to Convert", "Experiments", "Appendix",
    ]  # fmt: skip


def test_a_divider_styled_as_a_heading_isnt_a_recipe() -> None:
    names = [r.name for r in parse().recipes]
    assert names == [
        "Rejuvelac Cultured Almond Ricotta", "Petite Soy", "Colibrie", "Cashew Milk",
        "Parmesan", "Making and Using Brine",
    ]  # fmt: skip
    assert named(parse(), "Petite Soy").steps[-1].text == "Stir in the nigari and let it curdle."


def test_tools_are_kept_apart_from_the_ingredients() -> None:
    ricotta = named(parse(), "Rejuvelac Cultured Almond Ricotta")
    assert ricotta.tools == ["Cheesecloth", "Two ricotta molds"]
    assert [i.text for i in ricotta.ingredients] == [
        "2 Cups almonds, soaked overnight", "½ Cup rejuvelac", "1 tsp salt",
    ]  # fmt: skip
    assert not ricotta.needs_look


def test_variations_are_notes_not_steps() -> None:
    ricotta = named(parse(), "Rejuvelac Cultured Almond Ricotta")
    assert [s.group for s in ricotta.steps] == [
        "Preparing the Milk", "Forming the Cheese", "Forming the Cheese",
    ]  # fmt: skip
    assert ricotta.notes == ["Variations:", "Add chopped herbs before molding."]


def test_recipes_to_convert_are_drafts() -> None:
    cookbook = parse()
    assert named(cookbook, "Parmesan").draft == "not converted yet"
    assert named(cookbook, "Colibrie").draft == ""
    assert book.draft_of("Experiments") == "an experiment"


def test_the_cookbooks_layout_reads_as_before() -> None:
    """Its Heading 1s are sections, so nothing moves; its hashes are what they were (no
    tools, no drafts), so the next read changes nothing."""
    cookbook = book.parse(document())
    assert cookbook.sections[0][0] == "Ingredients"
    alfredo = named(cookbook, "Alfredo Sauce")
    assert (alfredo.section, alfredo.subsection) == ("Ingredients", "Sauces, Dressings & Dips")
    assert all(not r.tools and not r.draft for r in cookbook.recipes)
    data = alfredo.content_hash()
    alfredo.tools = ["A whisk"]
    assert alfredo.content_hash() != data
