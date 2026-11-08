"""RC1a: the cookbook doc's structure, parsed into recipes."""

from __future__ import annotations

from tests.fixtures.cookbook import (
    BEAN_DIP,
    BIRYANI,
    PARMESAN,
    ROASTED,
    TITLE,
    UBE,
    document,
    recipe,
)
from themi_home import cookbook as book
from themi_home.cookbook import Line


def parse(blocks: list | None = None) -> book.Cookbook:
    return book.parse(document(blocks))


def named(cookbook: book.Cookbook, name: str) -> book.ParsedRecipe:
    return next(r for r in cookbook.recipes if r.name == name)


def test_the_whole_fixture() -> None:
    cookbook = parse()
    names = [r.name for r in cookbook.recipes]
    assert names[:5] == [
        "Alfredo Sauce",
        "Silken Tofu Ranch Dressing",
        "Bean Dip",
        "Bechamel Sauce",
        "Simple Parmesan",
    ]
    assert names.count("Chocolate Peanut Butter Bars") == 2  # both kept
    assert cookbook.title == TITLE and cookbook.revision == "rev1"
    assert [s for s, _ in cookbook.sections] == [
        "Ingredients", "Breakfast", "Entrees", "Desserts", "Sides", "Snacks", "References",
    ]  # fmt: skip
    assert len({r.key for r in cookbook.recipes}) == len(cookbook.recipes)


def test_a_regular_recipe() -> None:
    alfredo = named(parse(), "Alfredo Sauce")
    assert alfredo.section == "Ingredients" and alfredo.subsection == "Sauces, Dressings & Dips"
    assert alfredo.ingredients[0] == Line(
        "1 Cup cashews, soaked in water for at least 10 minutes (130g)"
    )
    assert len(alfredo.ingredients) == 9 and len(alfredo.steps) == 3
    assert alfredo.notes == [
        "Recipe Notes: This sauce is super yummy served over cooked whole wheat or whole grain "
        "pasta and topped with steamed broccoli and roasted cherry tomatoes,"
    ]
    assert alfredo.source == "Molly Patrick of Clean Food Dirty Girl"
    assert alfredo.needs_look == [] and alfredo.kind == "recipe"
    assert alfredo.key.startswith("h.")


def test_part_names_typed_as_text() -> None:
    for blocks, steps in ((BEAN_DIP, 1), (UBE, 2)):
        parsed = parse([("H1", "Appetizers"), *blocks]).recipes[0]
        assert parsed.steps and len(parsed.steps) == steps
        assert "Ingredients" not in [i.text for i in parsed.ingredients]
        assert parsed.needs_look == ["headings typed as text"]
    dip = parse(BEAN_DIP).recipes[0]
    assert dip.ingredients[-2].text == "Optional: homemade plant cheese"


def test_ingredients_twice_means_the_steps() -> None:
    biryani = parse(BIRYANI).recipes[0]
    assert biryani.ingredients[0] == Line("6-7 Shallots OR 1/2 medium sized onion", "Masala Paste")
    assert biryani.steps[0].text.startswith("Make a paste in a food processor")
    assert len(biryani.steps) == 4
    assert biryani.needs_look == ["two Ingredients headings"]


def test_groups_and_hand_numbering() -> None:
    parmesan = parse(PARMESAN).recipes[0]
    assert {i.group for i in parmesan.ingredients} == {"Wet", "Dry"}
    assert parmesan.steps[0].text.startswith("Combine the melted coconut oil")
    assert parmesan.steps[2].text == "Store in a tupperware and let set in the fridge."


def test_a_table_is_a_chart() -> None:
    roasted = parse(ROASTED).recipes[0]
    assert roasted.kind == "chart" and roasted.needs_look == []
    assert roasted.chart[0] == ["Vegetable", "Temp", "Time", "Prep", "Seasonings"]
    assert book.chart_text(roasted).splitlines()[1] == (
        "Broccoli: Temp 400, Time 20 min, Prep Cut to florets, Seasonings Oil, salt, pepper"
    )


def test_references_are_charts_in_that_section() -> None:
    cookbook = parse()
    grains = named(cookbook, "Instant Pot Grains Timings")
    assert grains.kind == "chart" and grains.is_reference
    assert grains.chart[2] == ["Brown Rice", "1:1", "15m", "5m"]


def test_missing_parts_are_kept_and_flagged() -> None:
    parsed = parse([("H4", "Toast"), ("P", "Bread")]).recipes[0]
    assert parsed.ingredients == [Line("Bread")]
    assert "no steps found" in parsed.needs_look
    assert "no Ingredients heading" in parsed.needs_look


def test_a_horizontal_rule_or_dashes_end_a_recipe() -> None:
    blocks = [*recipe("A", ["1 egg"], ["Fry."]), ("P", "stray words"), ("HR",)]
    cookbook = parse(blocks)
    assert len(cookbook.recipes) == 1 and cookbook.recipes[0].notes == []


def test_soft_line_breaks_split_lines() -> None:
    blocks = [("H4", "Tea"), ("H5", "Ingredients"), ("P", "1 tea bag\u000b1 Cup water"),
              ("H5", "Instructions"), ("P", "Steep.")]  # fmt: skip
    assert [i.text for i in parse(blocks).recipes[0].ingredients] == ["1 tea bag", "1 Cup water"]


def test_yield_when_written() -> None:
    blocks = recipe("Hot Dogs", ["1 Cup gluten"], ["Pan fry. Makes 12 jumbo dogs or 16 regular."])
    assert parse(blocks).recipes[0].yield_count == 12
    assert named(parse(), "Alfredo Sauce").yield_count is None


def test_the_content_hash_changes_with_the_words_only() -> None:
    first = parse().recipes[0]
    again = parse().recipes[0]
    again.position = 9
    assert first.content_hash() == again.content_hash()
    again.steps.append(Line("Enjoy."))
    assert first.content_hash() != again.content_hash()


def test_where_a_new_entry_goes() -> None:
    cookbook = parse()
    starts = dict(cookbook.sections)
    assert book.insert_at(cookbook, "Entrees") == starts["Desserts"]
    assert book.insert_at(cookbook, "references") == cookbook.end - 1
    assert book.insert_at(cookbook, "No such section") == cookbook.end - 1


def test_entry_requests_style_every_paragraph() -> None:
    paragraphs = book.entry_text(
        "Toast", [Line("1 slice bread")], [Line("Toast it.")], [], "example.com (https://x)"
    )
    assert paragraphs == [
        ("Toast", "HEADING_4"),
        ("Ingredients", "HEADING_5"),
        ("1 slice bread", "NORMAL_TEXT"),
        ("Instructions", "HEADING_5"),
        ("Toast it.", "NORMAL_TEXT"),
        ("Source: example.com (https://x)", "NORMAL_TEXT"),
        ("-----", "NORMAL_TEXT"),
    ]
    requests = book.entry_requests(100, paragraphs)
    assert requests[0]["insertText"] == {
        "location": {"index": 100},
        "text": "Toast\nIngredients\n1 slice bread\nInstructions\nToast it.\n"
        "Source: example.com (https://x)\n-----\n",
    }
    ranges = [r["updateParagraphStyle"]["range"] for r in requests[1:]]
    assert ranges[0] == {"startIndex": 100, "endIndex": 106}
    assert ranges[1] == {"startIndex": 106, "endIndex": 118}
    assert len(ranges) == len(paragraphs)
