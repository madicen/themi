"""MP1: the home pack's groups on the Modules page (the core's are in themi.modules.groups)."""

from __future__ import annotations

from themi.modules.groups import ModuleGroup

BODY_DOUBLING = ModuleGroup(
    "body_doubling",
    "Body doubling",
    "Themi keeps someone company through a task: steps, modes, music and pictures.",
    60,
    starter=("body_double", "guided_steps", "mode_chooser", "music_offers"),
)
COOKING = ModuleGroup(
    "cooking",
    "Cooking",
    "The family cookbook, cooking along on the cook screen, timers and grams.",
    70,
    starter=(
        "recipes",
        "recipe_groceries",
        "cooking",
        "cooking_timers",
        "recipe_ideas",
        "cookbook_save",
        "web_recipes",
        "gram_weights",
    ),
)
GROCERIES = ModuleGroup(
    "groceries",
    "Groceries and pantry",
    "The grocery list, what's in the pantry, and meals from it.",
    80,
    starter=("groceries", "pantry", "which_list", "buying", "meals"),
)
MONEY = ModuleGroup(
    "money",
    "Money",
    "What the family spends, and takeout against its budget.",
    90,
    starter=("spending", "takeout"),
)
HOME = ModuleGroup(
    "home",
    "Home and devices",
    "Appliances and devices around the house, and keeping the home up.",
    120,
    starter=("appliances", "maintenance"),
)
