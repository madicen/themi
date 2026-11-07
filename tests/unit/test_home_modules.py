"""CR2b: each home module installs on the core alone, with what it requires."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.fakes.modules import module_context
from tests.fixtures.family import SeededFamily
from themi.core.appliances import Appliances, AppliancesModule
from themi.core.body_double import BodyDouble, BodyDoubleModule
from themi.core.body_double_guided import GuidedSteps, GuidedStepsModule
from themi.core.body_double_modes import ModeChooser, ModeChooserModule
from themi.core.body_double_music import MusicOffers, MusicOffersModule
from themi.core.buying import BuyingModule, ThingsToBuy
from themi.core.calls import CallsModule, VendorCalls
from themi.core.cookbook_save import CookbookSave, CookbookSaveModule
from themi.core.cooking import Cooking, CookingModule
from themi.core.cooking_timers import CookingTimers, CookingTimersModule
from themi.core.groceries import GroceriesModule, GroceryList
from themi.core.lists import ListsModule
from themi.core.maintenance import Maintenance, MaintenanceModule
from themi.core.meals import Meals, MealsModule
from themi.core.pantry import Pantry, PantryModule
from themi.core.recipe_groceries import RecipeGroceries, RecipeGroceriesModule
from themi.core.recipe_ideas import RecipeIdeas, RecipeIdeasModule
from themi.core.recipes import Recipes, RecipesModule
from themi.core.safeway import SafewayCart, SafewayModule
from themi.core.spending import Spending, SpendingModule
from themi.core.step_images import StepPictures, StepPicturesModule
from themi.core.tasks import TasksModule
from themi.core.web_recipes import WebRecipes, WebRecipesModule
from themi.modules import Module

RECIPES: list[Callable[[], Module]] = [RecipesModule, RecipeGroceriesModule]
BODY: list[Callable[[], Module]] = [BodyDoubleModule]

# module, what it provides, the modules it needs first, the jobs it adds
CASES: list[tuple[Callable[[], Module], type, list[Callable[[], Module]], set[str]]] = [
    (GroceriesModule, GroceryList, [], set()),
    (SafewayModule, SafewayCart, [GroceriesModule], {"safeway.expire"}),
    (BuyingModule, ThingsToBuy, [ListsModule], set()),
    (SpendingModule, Spending, [], set()),
    (PantryModule, Pantry, [GroceriesModule], {"pantry.predict"}),
    (MealsModule, Meals, [GroceriesModule, PantryModule], set()),
    (CallsModule, VendorCalls, [TasksModule], set()),
    (RecipesModule, Recipes, [], {"recipes.sync"}),
    (CookbookSaveModule, CookbookSave, [RecipesModule], set()),
    (RecipeGroceriesModule, RecipeGroceries, [RecipesModule], set()),
    (RecipeIdeasModule, RecipeIdeas, RECIPES, set()),
    (CookingModule, Cooking, RECIPES, {"cooking.expire"}),
    (CookingTimersModule, CookingTimers, [*RECIPES, CookingModule], set()),
    (BodyDoubleModule, BodyDouble, [], set()),
    (GuidedStepsModule, GuidedSteps, BODY, set()),
    (StepPicturesModule, StepPictures, [*BODY, GuidedStepsModule], set()),
    (ModeChooserModule, ModeChooser, BODY, set()),
    (MusicOffersModule, MusicOffers, BODY, set()),
    (WebRecipesModule, WebRecipes, [RecipesModule], {"recipes.forget_web"}),
    (MaintenanceModule, Maintenance, [TasksModule], {"maintenance.offer"}),
    (AppliancesModule, Appliances, [], set()),
]


@pytest.mark.parametrize(
    ("make", "provides", "needs", "jobs"), CASES, ids=[c[1].__name__ for c in CASES]
)
def test_the_module_installs_alone(
    family: SeededFamily,
    make: Callable[[], Module],
    provides: type,
    needs: list[Callable[[], Module]],
    jobs: set[str],
) -> None:
    ctx = module_context(family.store)
    ctx.load(*(n() for n in needs))
    before = {job.name for job in ctx.jobs}
    module = make()
    ctx.load(module)
    assert ctx.has(module.name)
    assert isinstance(ctx.get(provides), provides)
    assert {job.name for job in ctx.jobs} - before == jobs
