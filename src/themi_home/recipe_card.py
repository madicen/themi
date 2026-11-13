"""A recipe as a picture to keep (DC10; the Day Card Plan's "Other uses").

Its name and where it's from, the ingredients (in their groups), the numbered steps and
its notes, as written in the cookbook. The recipe's words are the family's text, drawn as
words and nothing else (escaped like any external text). A recipe too long for one picture
ends with a line saying the rest is in the cookbook.

"send me a picture of the lasagna recipe" (`recipe_card`), and the recipe's page on the
website links its picture (`/recipes/<id>/card.png`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themi.core import keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.drawing.svg import write_svg
from themi.drawing.text import text_width, wrap
from themi.standard.day_card import THEMES
from themi.standard.drawings import DrawingsPreferences

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi_home.recipes import Recipe

TEMPLATES = Path(__file__).parent / "drawing_templates"
WIDTH = 540
MIN_HEIGHT, MAX_HEIGHT = 675, 2400
PNG_WIDTH = 1080
PAD = 32
LINE = 19.0  # px between lines of 13.5 px text
MORE_TEXT = "The rest is in the cookbook."


@dataclass(frozen=True)
class Item:
    kind: str  # "heading", "group", "ingredient", "step", "note"
    lines: tuple[str, ...]
    number: int = 0


def items(recipe: Recipe) -> list[Item]:
    width = WIDTH - 2 * PAD
    out = [Item("heading", ("Ingredients",))]
    group = ""
    for line in recipe.ingredients:
        if line.group and line.group != group:
            out.append(Item("group", tuple(wrap(line.group, 13.5, width, 2, bold=True))))
            group = line.group
        out.append(Item("ingredient", tuple(wrap(line.text, 13.5, width - 16, 3))))
    out.append(Item("heading", ("Steps",)))
    step_group = ""
    for n, step in enumerate(recipe.steps, start=1):
        if step.group and step.group != step_group:
            out.append(Item("group", tuple(wrap(step.group, 13.5, width, 2, bold=True))))
            step_group = step.group
        out.append(Item("step", tuple(wrap(step.text, 13.5, width - 28, 8)), n))
    for note in recipe.notes:
        out.append(Item("note", tuple(wrap(note, 12, width, 4))))
    if recipe.source_text:
        out.append(Item("note", tuple(wrap(f"Source: {recipe.source_text}", 12, width, 2))))
    return out


def view(recipe: Recipe, theme: str = "light") -> dict[str, Any]:
    colors = THEMES[theme]
    width = WIDTH - 2 * PAD
    title = wrap(recipe.name, 24, width, 3, bold=True)
    where = recipe.section + (f" · {recipe.subsection}" if recipe.subsection else "")
    y = 40.0 + 30 * len(title) + 20  # under the title's last line
    head = {"title": title, "where": where, "where_y": y}
    y += 22
    placed = []
    cut = False
    for item in items(recipe):
        gap = 18.0 if item.kind == "heading" else 6.0
        height = gap + LINE * len(item.lines)
        if y + height > MAX_HEIGHT - 70:
            cut = True
            break
        placed.append({"kind": item.kind, "number": item.number, "y": y + gap, "lines": [
            {"y": y + gap + LINE * (k + 1) - 5, "text": t} for k, t in enumerate(item.lines)
        ]})  # fmt: skip
        y += height
    height = max(MIN_HEIGHT, y + (60 if cut else 32))
    return {
        "width": WIDTH,
        "height": round(height),
        "pad": PAD,
        "c": colors,
        "head": head,
        "title_lines": [{"y": 40 + 30 * (k + 1) - 4, "text": t} for k, t in enumerate(title)],
        "items": placed,
        "more": MORE_TEXT if cut else "",
        "more_y": y + 30,
        "step_x": PAD + 26,
        "bullet_x": PAD + 16,
        "rule_w": width,
        "number_w": text_width("10.", 13.5, True),
    }


def card_svg(recipe: Recipe, theme: str = "light") -> str:
    return write_svg("recipe_card.svg", [TEMPLATES], **view(recipe, theme))


async def card_png(services: Any, member: Member, recipe: Recipe) -> bytes | None:
    drawings = services.maybe(keys.drawings)
    if drawings is None:
        return None
    theme = services.store.preferences(member.id, DrawingsPreferences).picture_theme
    svg = card_svg(recipe, theme)
    return await drawings.png(svg, PNG_WIDTH)


@tool(
    "recipe_card",
    "Sends one recipe from the family's cookbook as a picture to keep or print: name is the "
    "recipe they named. For 'send me a picture of the lasagna recipe', 'a recipe card for "
    "the pancakes'. Use find_recipe to show it in chat instead.",
    {"name": {"type": "string"}},
)
async def recipe_card(ctx: ToolContext, args: dict[str, Any]) -> str:
    from themi_home.recipes import clear_match

    recipes = ctx.services.maybe(keys.recipes)
    if recipes is None:
        raise ToolFailed("Recipes aren't set up.")
    name = str(args["name"]).strip()
    matches = [m for m in recipes.find(name, charts=False)]
    if not matches:
        raise ToolDeclined(f'Nothing in the cookbook matches "{name}". Say so plainly.')
    recipe = clear_match(matches) or (matches[0].recipe if len(matches) == 1 else None)
    if recipe is None:
        names = ", ".join(f"{n}. {m.recipe.name}" for n, m in enumerate(matches[:4], 1))
        raise ToolDeclined(  # F42c: their answer ("the first one", a name) is understood
            f"Several recipes match ({names}): ask which one they mean. If they answer with "
            "one of these (its number, 'the first one', or its name), call again with that "
            "name, word for word."
        )
    png = await card_png(ctx.services, ctx.member, recipe)
    if png is not None and await ctx.services.outbox.send_photo(
        ctx.member, png, recipe.name, kind="recipe_card"
    ):
        ctx.answered.append("recipe_card")
        return f"Sent {recipe.name} as a picture. Don't repeat it."
    first = await recipes.send(ctx.member, recipe)  # no picture: the recipe as written
    ctx.cards.append(first)
    return f"Couldn't draw it, so sent the recipe as written: {first}. Don't repeat it."
