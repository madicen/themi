"""A trimmed copy of the vegan cheese doc's layout (RC8c), for the parser and the fake Docs API.

The real doc ("Madicen Family Cheese Recipes", read 2026-11-25) has 35 recipes. Its title is
the only Heading 1; sections are Heading 2 (Cheeses, Milks, Dairy Recipes to Convert,
Experiments, Appendix) and sub-sections Heading 3 (Fresh, Aged). Some `-----` dividers are
styled Heading 4, recipes have Heading 6 "Tools" groups under Ingredients and "Variations"
after the steps.
"""

from __future__ import annotations

from typing import Any

from tests.fixtures.cookbook import Block, document

CHEESE_TITLE = "Madicen Family Cheese Recipes"

RICOTTA: list[Block] = [
    ("H4", "Rejuvelac Cultured Almond Ricotta"),
    ("H5", "Ingredients"),
    ("P", "2 Cups almonds, soaked overnight"),
    ("P", "½ Cup rejuvelac"),
    ("P", "1 tsp salt"),
    ("H6", "*Tools*"),
    ("P", "Cheesecloth"),
    ("P", "Two ricotta molds"),
    ("H5", "Instructions"),
    ("H6", "*Preparing the Milk*"),
    ("P", "Blend the almonds with 4 cups water and strain."),
    ("H6", "*Forming the Cheese*"),
    ("P", "Stir in the rejuvelac and salt, and leave it 24 hours."),
    ("P", "Hang it in the cheesecloth for a few hours, then fill the molds."),
    ("H6", "*Variations*"),
    ("P", "Add chopped herbs before molding."),
    ("P", "-----"),
]
PETITE_SOY: list[Block] = [
    ("H4", "Petite Soy"),
    ("H5", "Ingredients"),
    ("P", "4 Cups Soy Milk"),
    ("P", "1 tsp nigari"),
    ("H5", "Instructions"),
    ("P", "Warm the Soy Milk to 160°F."),
    ("P", "Stir in the nigari and let it curdle."),
    ("H4", "\\-----"),  # a divider styled as a recipe heading, as in the real doc
]
COLIBRIE: list[Block] = [
    ("H4", "Colibrie"),
    ("H5", "Ingredients"),
    ("P", "2 Cups Cashew Milk"),
    ("P", "1 tsp salt"),
    ("H5", "Instructions"),
    ("P", "Warm the Cashew Milk to 90°F."),
    ("P", "Culture it overnight."),
    ("P", "-----"),
]
CASHEW_MILK: list[Block] = [
    ("H4", "Cashew Milk"),
    ("H5", "Ingredients"),
    ("P", "1 Cup cashews"),
    ("P", "4 Cups water"),
    ("H5", "Instructions"),
    ("P", "Blend."),
    ("P", "Strain."),
    ("P", "-----"),
]
PARMESAN: list[Block] = [
    ("H4", "Parmesan"),
    ("H5", "Ingredients"),
    ("P", "1 gallon whole milk"),
    ("P", "¼ tsp rennet"),
    ("H5", "Instructions"),
    ("P", "Heat the milk and add the rennet."),
    ("P", "-----"),
]
BRINE: list[Block] = [
    ("H4", "Making and Using Brine"),
    ("H5", "Ingredients"),
    ("P", "1 gallon water"),
    ("P", "2 lbs salt"),
    ("H5", "Instructions"),
    ("P", "Dissolve the salt in the water."),
]


def cheese_doc() -> list[Block]:
    return [
        ("H1", CHEESE_TITLE),
        ("H2", "Cheeses"),
        ("H3", "Fresh"),
        *RICOTTA,
        ("H3", "Aged"),
        *PETITE_SOY,
        *COLIBRIE,
        ("H2", "Milks"),
        *CASHEW_MILK,
        ("H2", "Dairy Recipes to Convert"),
        *PARMESAN,
        ("H2", "Experiments"),
        ("H2", "Appendix"),
        *BRINE,
    ]


def cheese_document(blocks: list[Block] | None = None) -> dict[str, Any]:
    found = document(blocks or cheese_doc())
    found["title"] = CHEESE_TITLE
    return found
