"""RC1b: finding a recipe by name, ingredient or section, and the card it's sent as."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.fixtures.cookbook import document
from themi.core import cookbook as book
from themi.core.cookbook import Line
from themi.core.recipes import Recipe, chart_row, clear_match, recipe_lines, search, stem


def recipes() -> list[Recipe]:
    out = []
    for n, parsed in enumerate(book.parse(document()).recipes, start=1):
        out.append(
            Recipe(
                n, parsed.key, "doc", None, parsed.section, parsed.subsection, parsed.name,
                tuple(parsed.ingredients), tuple(parsed.steps), tuple(parsed.notes),
                parsed.source, parsed.kind, tuple(tuple(r) for r in parsed.chart),
                parsed.yield_count, None, "; ".join(parsed.needs_look), False,
                datetime(2026, 11, 6, tzinfo=UTC),
            )
        )  # fmt: skip
    return out


def names(text: str, section: str = "") -> list[str]:
    return [m.recipe.name for m in search(recipes(), text, section=section)]


def test_by_name() -> None:
    assert names("the ranch dressing")[0] == "Silken Tofu Ranch Dressing"
    assert clear_match(search(recipes(), "alfredo sauce recipe")) is not None
    assert clear_match(search(recipes(), "Simple Parmesan")).name == "Simple Parmesan"  # type: ignore[union-attr]


def test_by_ingredient() -> None:
    found = names("something with chickpeas")
    assert found == ["Chana Masala"]
    assert "Pancakes" in names("almond milk")


def test_by_section() -> None:
    assert names("a dessert") == [
        "Ube Gelato", "Chocolate Peanut Butter Bars", "Chocolate Peanut Butter Bars",
    ]  # fmt: skip
    assert names("peanut butter", section="Desserts")[:2] == ["Chocolate Peanut Butter Bars"] * 2


def test_two_with_one_name_isnt_a_clear_match() -> None:
    assert clear_match(search(recipes(), "chocolate peanut butter bars")) is None


def test_nothing_matches() -> None:
    assert names("beef wellington") == []
    assert names("a recipe please") == []


def test_a_chart_row() -> None:
    roasted = next(r for r in recipes() if r.name == "Roasted Vegetables")
    assert chart_row(roasted, [stem("broccoli")]) == (
        "Broccoli: Temp 400, Time 20 min, Prep Cut to florets, Seasonings Oil, salt, pepper"
    )
    assert chart_row(roasted, ["kale"]) is None
    assert names("how long do I roast broccoli")[0] == "Roasted Vegetables"


def test_stems() -> None:
    assert [stem(w) for w in ("dressings", "cookies", "roasted", "tomatoes", "baked")] == [
        "dressing", "cooky", "roast", "tomato", "baked",
    ]  # fmt: skip


def test_the_card_quotes_the_recipe_as_written() -> None:
    biryani = next(r for r in recipes() if r.name == "Biryani")
    first, second = recipe_lines(biryani, "https://docs.google.com/document/d/x/edit#heading=h.1")
    assert first.splitlines()[:4] == ["Biryani (Entrees)", "", "Ingredients", "> Masala Paste:"]
    assert "> - 5 cloves garlic" in first
    assert second.splitlines()[1].startswith("> 1. Make a paste in a food processor")
    assert second.endswith("In the cookbook: https://docs.google.com/document/d/x/edit#heading=h.1")
    alfredo = next(r for r in recipes() if r.name == "Alfredo Sauce")
    _, steps = recipe_lines(alfredo)
    assert "> Source: Molly Patrick of Clean Food Dirty Girl" in steps
    head, _ = recipe_lines(alfredo)
    assert head.startswith("Alfredo Sauce (Ingredients · Sauces, Dressings & Dips)")


def test_a_long_recipe_is_two_messages_worth() -> None:
    long = recipes()[0]
    long = Recipe(**{**long.__dict__, "steps": tuple(Line("Stir. " * 100) for _ in range(8))})
    first, second = recipe_lines(long)
    assert len(first) < 3_800 < len(first) + len(second)
