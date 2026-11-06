# ruff: noqa: RUF001  (the doc's own dashes and quote marks, kept as written)
"""A trimmed copy of the family cookbook doc's structure (RC1a), for the fake Docs API.

The real doc ("Madicen Family Cookbook", read 2026-11-06) has 132 entries. This keeps a
dozen with the same shape, including each irregular one the parser has to take: Bean Dip
and Ube Gelato (part names typed as text), Biryani ("Ingredients" twice), Roasted
Vegetables (a table, so a chart), a recipe named twice, and the References tables. Recipe
text is as the doc has it, trimmed; nothing else of the family's is in here.
"""

from __future__ import annotations

from typing import Any

COOKBOOK_ID = "12OocqIHwa2rLjZSMDZnMfnoYS_q4b6MdTOSEVSLkpkk"
TITLE = "Madicen Family Cookbook"
LINK = f"https://docs.google.com/document/d/{COOKBOOK_ID}/edit?usp=sharing"

Block = tuple[Any, ...]


def recipe(name: str, ingredients: list[str], steps: list[str], *after: str) -> list[Block]:
    """A regular entry: H4 name, H5 parts, lines; a line starting "## " is an H6 group."""
    blocks: list[Block] = [("H4", name), ("H5", "Ingredients")]
    for line in ingredients:
        blocks.append(("H6", line[3:]) if line.startswith("## ") else ("P", line))
    blocks.append(("H5", "Instructions"))
    blocks.extend(("P", s) for s in steps)
    blocks.extend(("P", a) for a in after)
    blocks.append(("P", "-----"))
    return blocks


ALFREDO = recipe(
    "Alfredo Sauce",
    [
        "1 Cup cashews, soaked in water for at least 10 minutes (130g)",
        "1.5 Cups water (355mL)",
        "2 garlic cloves, peeled and left whole",
        "1 tsp mild/yellow miso",
        "1 tsp lemon juice",
        "½ tsp salt",
        "¼ tsp ground nutmeg",
        "¼ tsp onion powder",
        "¼ tsp black pepper (about 10 turns)",
    ],
    [
        "Drain and discard water from soaked cashews.",
        "Blend cashews and all other ingredients in a blender until creamy and smooth. The "
        "sauce will seem thin but no worries, it will thicken as it heats up.",
        "Transfer the sauce to a medium-sized saucepan, turn the heat to the lowest possible "
        "setting and cook for 10 minutes, stirring often so the sauce doesn’t stick to the "
        "bottom of the pan.",
    ],
    "Recipe Notes: This sauce is super yummy served over cooked whole wheat or whole grain "
    "pasta and topped with steamed broccoli and roasted cherry tomatoes,",
    "Source: Molly Patrick of Clean Food Dirty Girl",
)

RANCH = recipe(
    "Silken Tofu Ranch Dressing",
    [
        "1 package silken tofu (12.3oz) firm",
        "2 Tbsp water",
        "2 Tbsp olive oil (or sub with water — or use 1 Tbsp water and 1 Tbsp oil– for lower "
        "calories)",
        "2 fat garlic cloves ( or 2 tsp granulated garlic)",
        "1 rounded tsp onion powder (or a couple slices of white onion)",
        "1 tsp salt",
        "1½ Tbsp apple cider or sherry vinegar",
        "1 Tbsp nutritional yeast",
        "¼ –½ Cup fresh herbs- dill, basil, Italian parsley, or cilantro or a blend",
        "1 tsp crushed peppercorns (or stir these in at the end)",
    ],
    ["Blend ingredients together until smooth"],
)

BEAN_DIP: list[Block] = [
    ("H4", "Bean Dip"),
    ("P", "Ingredients"),
    ("P", "1 can chili pinto beans"),
    ("P", "1 can black beans"),
    ("P", "1 can refried beans"),
    ("P", "Frozen corn"),
    ("P", "Tabasco"),
    ("P", "Black pepper"),
    ("P", "Optional: homemade plant cheese"),
    ("P", "Tortilla chips (for serving)"),
    ("P", "Instructions"),
    ("P", "Mix everything in a pot, heat until bubbling. Eat with chips"),
    ("P", "-----"),
]

PARMESAN = recipe(
    "Simple Parmesan",
    [
        "## *Wet*",
        "50g refined coconut oil",
        "35g water",
        "2g olive oil",
        "1/4 tsp salt",
        "4g soy lecithin",
        "## *Dry*",
        "36g potato starch",
        "20g rice flour",
        "7g (1 1/2 Tbsp) nooch",
        "7g (1/2 Tbsp) miso paste",
    ],
    [
        "1\\. Combine the melted coconut oil, water, extra-virgin olive oil, salt, and soy "
        "lecithin. Using a hand blender, blend on high for about 2 minutes, making sure the oil "
        "and water are well emulsified.",
        "2\\. Place the rest of your ingredients in a pot and add the oil and water mixture as "
        "well. Heat over medium-low heat, stirring constantly and quickly, for about 2 minutes, "
        "until the mixture becomes glossy.",
        "3\\. Store in a tupperware and let set in the fridge.",
    ],
)

PANCAKES = recipe(
    "Pancakes",
    [
        "1 ½ Cup (180 grams) white whole wheat flour",
        "1 Cup (120 grams) all-purpose flour",
        "1 Tbsp + 1 tsp baking powder (20g)",
        "1 tsp cinnamon (optional)",
        "½ tsp kosher salt",
        "2 Cups unsweetened almond milk",
        "¼ Cup (70g) unsweetened applesauce (or ¼ Cup (85g) pure maple syrup)",
        "2 tsp pure vanilla extract",
    ],
    [
        "If you’d like to keep the pancakes warm between batches, preheat the oven to 200 °F.",
        "In the bottom of a large mixing bowl, whisk together the flours, baking powder, "
        "cinnamon (if using), and salt. In a separate bowl, whisk together the almond milk, "
        "applesauce and vanilla.",
        "Make a well in the center of the dry ingredients, then pour in the wet ingredients. "
        "Stir the batter gently, just until the flour disappears.",
        "Heat a large nonstick skillet or griddle over medium-low heat.",
        "Drop the batter by ¼ Cupfuls onto the griddle. Cook on the first side until small "
        "bubbles form on top and the edges look dry, about 2 to 3 minutes. Gently flip the "
        "pancakes and cook on the other side until browned, about 1 to 2 minutes more.",
    ],
)

BIRYANI: list[Block] = [
    ("H4", "Biryani"),
    ("H5", "Ingredients"),
    ("H6", "*Masala Paste*"),
    ("P", "6-7 Shallots OR 1/2 medium sized onion"),
    ("P", "5 cloves garlic"),
    ("P", "1 inch ginger"),
    ("P", "3 cardamom"),
    ("P", "1 medium sized onion, sliced"),
    ("P", "2 Cups mix vegetables(carrot,beans,cauliflower,potato)"),
    ("P", "1 Cup (250 ml) ,Basmati Rice OR Seeraga samba"),
    ("P", "1½ Cups (375 ml), water"),
    ("P", "salt as per taste"),
    ("H5", "Ingredients"),
    ("P", "Make a paste in a food processor from the ingredients listed under masala paste "
          "and keep aside."),
    ("P", "Press SAUTE mode on Instant Pot. Add oil into the POT and add Bay leaf,star anise."),
    ("P", "Add in the sliced onions and fry till the onions are soft."),
    ("P", "Pressure cook on high for 5 minutes, then let the pressure release naturally."),
    ("P", "-----"),
]  # fmt: skip

CHANA = recipe(
    "Chana Masala",
    [
        "2 Cups dried chickpeas, soaked overnight",
        "2 Cups water",
        "2 Tbsp oil of choice",
        "1 onion, finely chopped",
        "1 bay leaf",
        "2 tsp minced garlic",
        "2 tomatoes, chopped",
        "## *Spice Blend*",
        "2 tsp coriander powder",
        "1 tsp garam masala",
        "## *Garnish*",
        "Cilantro leaves",
        "Red onion",
    ],
    [
        "Soak the chickpeas in cold water overnight. Drain, rinse and set aside.",
        "Press the sauté button on the Instant Pot. Add the oil and allow it to heat it up for "
        "a minute. Add the onion and bay leaf and stir-fry for 6-7 minutes, or until the onion "
        "begins to brown.",
        "Add the garlic, ginger, stir, then add the chopped tomatoes and cook for 5-7 minutes.",
        "Add the spices, stir, then add the chickpeas and water.",
        "Secure the lid, close the pressure valve and cook for 35 minutes at high pressure.",
        "Naturally release pressure.",
        "Discard the bay leaf, garnish with red onion and chopped cilantro.",
    ],
)

LASAGNA = recipe(
    "Lasagna",
    [
        "1 batch of Bechamel Sauce",
        "1 Tbsp olive oil",
        "1 onion, peeled and finely chopped",
        "14oz (400g) can peeled tomatoes",
        "12 lasagna sheets",
        "Fresh parsley or basil finely chopped for serving",
    ],
    [
        "Preheat the oven to 350 degrees",
        "Saute the onion in the olive oil for 2 minutes or until softened.",
        "Once simmering, lower the heat and allow the sauce to cook for around 20 minutes.",
        "Wrap the lasagna in aluminum foil and bake for 30 minutes.",
    ],
)

UBE: list[Block] = [
    ("H4", "Ube Gelato"),
    ("P", "Ingredients"),
    ("P", "1 lb. Japanese sweet potatoes (white outside, purple inside)"),
    ("P", "1¼ (300g) Cup soy milk"),
    ("P", "3-4 Medjool dates (42 grams) - remove pits"),
    ("P", "Instructions"),
    ("P", "Preheat the oven to 400° F. Roast the sweet potatoes for 1 hour."),
    ("P", "Process until smooth and freeze for 24 hours."),
    ("P", "-----"),
]

BARS = recipe(
    "Chocolate Peanut Butter Bars",
    ["1 Cup peanut butter", "1 Cup chocolate chips"],
    ["Melt, mix, and chill for 1 hour."],
)
BARS_AGAIN = recipe(
    "Chocolate Peanut Butter Bars",
    ["2 Cups oats", "1/2 Cup peanut butter", "1/2 Cup chocolate chips"],
    ["Mix the oats and peanut butter, press into a pan, top with melted chocolate."],
)

ROASTED: list[Block] = [
    ("H4", "Roasted Vegetables"),
    (
        "TABLE",
        [
            ["**Vegetable**", "**Temp**", "**Time**", "**Prep**", "**Seasonings**"],
            ["Carrot", "425", "30 min", "Cut to 1.5 inch", "Oil, salt, pepper"],
            ["Broccoli", "400", "20 min", "Cut to florets", "Oil, salt, pepper"],
            ["Zucchini", "425", "20 min", "Cut to 1 inch", "Oil, italian seasoning, salt"],
        ],
    ),
    ("HR",),
]

WEIGHTS: list[Block] = [
    ("H4", "Weights of Common Ingredients"),
    (
        "TABLE",
        [
            ["**Ingredient**", "**Weight in Grams**"],
            ["1 Cup Flour", "120g"],
            ["1 tsp Salt", "6g"],
        ],
    ),
    ("P", "-----"),
]

GRAINS: list[Block] = [
    ("H4", "Instant Pot Grains Timings"),
    (
        "TABLE",
        [
            ["**Name of Grain**", "**Grain : Water Ratio**", "**High Pressure Time**",
             "**Natural Release Time**"],
            ["Steel Cut Oats", "1:2", "4m", "10m"],
            ["Brown Rice", "1:1", "15m", "5m"],
            ["Quinoa", "1:1.5", "3m", "10m"],
        ],
    ),
]  # fmt: skip

SNACK = recipe(
    "Hardtack",
    ["2 Cups flour", "1/2 tsp salt", "3/4 Cup water"],
    ["Preheat the oven to 250 degrees F.", "Bake for at least four hours."],
)


def cookbook() -> list[Block]:
    return [
        ("T", TITLE),
        ("H1", TITLE),
        ("H1", "Ingredients"),
        ("H3", "Sauces, Dressings & Dips"),
        *ALFREDO,
        *RANCH,
        *BEAN_DIP,
        ("H3", "Other"),
        *PARMESAN,
        ("H1", "Breakfast"),
        *PANCAKES,
        ("H1", "Entrees"),
        *BIRYANI,
        *CHANA,
        *LASAGNA,
        ("H1", "Desserts"),
        *UBE,
        *BARS,
        *BARS_AGAIN,
        ("H1", "Sides"),
        *ROASTED,
        ("H1", "Snacks"),
        *SNACK,
        ("H1", "References"),
        *WEIGHTS,
        *GRAINS,
    ]


def document(blocks: list[Block] | None = None, revision: str = "rev1") -> dict[str, Any]:
    """The Docs API's JSON for these blocks, without a server (for parser unit tests)."""
    content: list[dict[str, Any]] = []
    index = 1
    for n, block in enumerate(blocks or cookbook()):
        kind = block[0]
        if kind == "TABLE":
            rows = [
                {"tableCells": [{"content": [{"paragraph": _p(c, "NORMAL_TEXT")}]} for c in row]}
                for row in block[1]
            ]
            content.append(
                {"startIndex": index, "endIndex": index + 10, "table": {"tableRows": rows}}
            )
            index += 10
            continue
        if kind == "HR":
            paragraph = {
                "elements": [{"horizontalRule": {}}, {"textRun": {"content": "\n"}}],
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            }
            content.append({"startIndex": index, "endIndex": index + 1, "paragraph": paragraph})
            index += 1
            continue
        style = {"T": "TITLE", "P": "NORMAL_TEXT"}.get(kind, f"HEADING_{kind[1:]}")
        text = str(block[1])
        paragraph = _p(text, style, f"h.{n:04d}" if style.startswith("HEADING") else "")
        content.append(
            {"startIndex": index, "endIndex": index + len(text) + 1, "paragraph": paragraph}
        )
        index += len(text) + 1
    return {"title": TITLE, "revisionId": revision, "body": {"content": content}}


def _p(text: str, style: str, heading_id: str = "") -> dict[str, Any]:
    paragraph_style: dict[str, Any] = {"namedStyleType": style}
    if heading_id:
        paragraph_style["headingId"] = heading_id
    return {"elements": [{"textRun": {"content": f"{text}\n"}}], "paragraphStyle": paragraph_style}


def load(services: Any, blocks: list[Block] | None = None) -> None:
    """Put the fixture cookbook in Themi's copy, as a sync would (no Google needed)."""
    from themi.core import cookbook as book

    services.recipes.store_doc(book.parse(document(blocks)).recipes)
    services.store.db.execute(
        "UPDATE cookbook SET doc_id = ?, title = ? WHERE id = 1", (COOKBOOK_ID, TITLE)
    )
