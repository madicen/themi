"""Cookbook recipes in meal ideas (RC7).

`suggest_meals` (prompt 27) gains one line when the pantry mostly covers a cookbook recipe:
"Or from the cookbook: Chana Masala (you'd need cilantro leaves)." with [Cook this] and
[Add cilantro leaves]. "What can we make with what we have?" lists up to five the same way.

The pick, all in code:
- Only the cookbook's own meals: not its Ingredients (sauces, crusts) or References.
- What it needs is its ingredient lines as already read (RC2a's cache, or the rules), less
  staples and optional lines. The pantry "has" an item when it isn't out; names match by
  words ("chickpeas" covers "dried chickpeas").
- At most two missing, and never the first thing it needs (the main item).
- Order: fewest missing, then most use-soon items used, then recipes finished in a
  cooking session before (RC3b); none finished in the last week.
- When their energy reads low, only short recipes: five steps or fewer and nothing that
  needs time first. That's used only to choose and is never said.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core.cooking import ahead_of_time
from themi.core.groceries import CATEGORY, EXECUTOR, and_list, list_summary
from themi.core.lists import name_key
from themi.core.recipe_groceries import RecipeGroceries
from themi.core.recipes import Recipe, Recipes, stem
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_local, to_utc_iso
from themi.modules import Module, ModuleContext

if TYPE_CHECKING:
    from themi.core.services import Services

NOT_MEALS = {"ingredients", "references"}
MAX_MISSING = 2
SHORT_STEPS = 5
RECENT = timedelta(days=7)
SOON_DAYS = 3
LISTED = 5


@dataclass(frozen=True)
class Idea:
    recipe: Recipe
    missing: tuple[str, ...]
    soon: int  # use-soon pantry items it uses
    finished: int  # cooking sessions of it that finished


def _words(name: str) -> set[str]:
    return {stem(w) for w in name_key(name).split()}


def covers(have: str, item: str) -> bool:
    """A pantry item covers an ingredient when one's words hold the other's."""
    a, b = _words(have), _words(item)
    return bool(a) and bool(b) and (a <= b or b <= a)


class RecipeIdeas:
    def __init__(self, services: Services, recipes: Recipes, groceries: RecipeGroceries):
        self.services = services
        self.recipes = recipes
        self.groceries = groceries
        self.db = services.store.db

    def install(self) -> None:
        self.services.recipe_ideas = self
        self.services.recipe_buttons["idea_add"] = self.on_add
        self.services.tools.register(cookbook_recipes_we_can_make)

    def _finished(self) -> tuple[dict[int, int], set[int]]:
        rows = self.db.query(
            "SELECT recipe_id, COUNT(*) AS n, MAX(ended_at) AS last FROM cooking_sessions "
            "WHERE outcome = 'finished' GROUP BY recipe_id"
        )
        recent_since = clock.now() - RECENT
        counts = {r["recipe_id"]: r["n"] for r in rows}
        recent = {
            r["recipe_id"] for r in rows if r["last"] and r["last"] >= to_utc_iso(recent_since)
        }
        return counts, recent

    def pick(self, member: Member, limit: int = 1) -> list[Idea]:
        pantry = self.services.pantry
        if pantry is None:
            return []
        items = pantry.items()
        have = [i.name for i in items if i.status != "out"]
        family = self.services.store.get_family()
        today: date = to_local(clock.now(), family.timezone if family else "UTC").date()
        soon = [
            i.name for i in items
            if i.status != "out" and i.expiry is not None and (i.expiry - today).days <= SOON_DAYS
        ]  # fmt: skip
        low = self.services.energy.suggested_level(member) == "low"
        counts, recent = self._finished()
        ideas: list[Idea] = []
        for recipe in self.recipes.all(source="doc"):
            if recipe.section.lower() in NOT_MEALS or not recipe.steps:
                continue
            if recipe.id in recent:
                continue
            read = self.groceries.known(recipe)
            needed = [i.item for i in read if not i.staple and not i.optional]
            if not needed:
                continue
            missing = [n for n in needed if not any(covers(h, n) for h in have)]
            if len(missing) > MAX_MISSING or needed[0] in missing:
                continue
            if low and (len(recipe.steps) > SHORT_STEPS or ahead_of_time(recipe, read)):
                continue
            used_soon = sum(1 for s in soon if any(covers(s, n) for n in needed))
            ideas.append(
                Idea(recipe, tuple(dict.fromkeys(missing)), used_soon, counts.get(recipe.id, 0))
            )
        ideas.sort(key=lambda i: (len(i.missing), -i.soon, -i.finished, i.recipe.name))
        return ideas[:limit]

    @staticmethod
    def line(idea: Idea) -> str:
        need = f" (you'd need {and_list(list(idea.missing))})" if idea.missing else ""
        return f"{idea.recipe.name}{need}"

    def buttons(self, idea: Idea) -> list[Button]:
        out = [Button("Cook this", "recipe", {"action": "cook", "id": idea.recipe.id})]
        if idea.missing:
            label = f"Add {and_list(list(idea.missing))}"
            out.append(
                Button(label[:60], "recipe", {"action": "idea_add", "items": list(idea.missing)})
            )
        return out

    def offer(self, member: Member) -> tuple[str, list[Button]] | None:
        """The line and buttons for `suggest_meals`, or None."""
        found = self.pick(member)
        if not found:
            return None
        return f"Or from the cookbook: {self.line(found[0])}.", self.buttons(found[0])

    async def on_add(self, event: InboundEvent) -> None:
        assert event.button is not None
        names = [str(n) for n in event.button.payload.get("items") or []]
        groceries = self.services.groceries
        if not names or groceries is None:
            return
        member = self.services.store.get_member(event.member.id)
        names = [n for n in names if not groceries.is_needed(n)]
        if not names:
            text = "That's on the grocery list already."
        else:
            outcome = await self.services.autonomy.stage(
                CATEGORY, member, list_summary(names), {"items": names}, EXECUTOR,
                interactive=True, requested=True,
            )  # fmt: skip
            text = (
                f"Added to the grocery list: {and_list(names)}."
                if outcome.action.status == "done"
                else f"Waiting on a yes for: {and_list(names)}."
            )
        await self.services.outbox.send(member, text, priority=Priority.REPLY, kind="recipes")


def _ideas(ctx: ToolContext) -> RecipeIdeas:
    found = ctx.services.recipe_ideas
    if found is None:
        raise ToolFailed("Recipes aren't set up.")
    return found


@tool(
    "cookbook_recipes_we_can_make",
    "Which family cookbook recipes the pantry already (almost) covers, when they ask what "
    "they could make from the cookbook with what they have: up to five as buttons, each "
    "saying anything that's missing.",
    {},
)
async def cookbook_recipes_we_can_make(ctx: ToolContext, args: dict[str, Any]) -> str:
    ideas = _ideas(ctx)
    found = ideas.pick(ctx.member, limit=LISTED)
    if not found:
        raise ToolDeclined(
            "No cookbook recipe is covered by the pantry as Themi knows it (two things or "
            "fewer to buy). Say so; suggest_meals can offer quick ideas instead."
        )
    lines = ["From the cookbook, with what you have:"]
    lines += [f"> {ideas.line(i)}" for i in found]
    text = "\n".join(lines)
    buttons = [
        Button(i.recipe.name[:60], "recipe", {"action": "show", "id": i.recipe.id}) for i in found
    ]
    await ctx.services.outbox.send(
        ctx.member, text, priority=Priority.REPLY, kind="recipes", buttons=buttons
    )
    ctx.cards.append(text)
    return f"Sent them this, with a button per recipe: {text}"


class RecipeIdeasModule(Module):
    """RC7: cookbook recipes in meal ideas."""

    name = "recipe_ideas"
    requires = ("recipes", "recipe_groceries")

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(RecipeIdeas(ctx.services, ctx.get(Recipes), ctx.get(RecipeGroceries))).install()
