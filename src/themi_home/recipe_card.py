"""A recipe as a picture to keep (DC10; the Day Card Plan's "Other uses").

Its name and where it's from, the ingredients (in their groups, in two columns, each amount
bold), the numbered steps with their short titles (CK12's, or the step's first words) and
its notes, as written in the cookbook, in the reader's picture theme (light or dark). The
recipe's words are the family's text, drawn as words and nothing else (escaped like any
external text). A recipe too long for one picture ends with a line saying the rest is in
the cookbook.

"send me a picture of the lasagna recipe" (`recipe_card`), and the recipe's page on the
website links its picture (`/recipes/<id>/card.png`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themi.core import keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.drawing.svg import write_svg
from themi.drawing.text import fit, text_width, wrap
from themi.standard.drawings import DrawingsPreferences
from themi_home.cooking_titles import fallback_title
from themi_home.quantities import AMOUNT, BRACKET

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi_home.recipes import Recipe

TEMPLATES = Path(__file__).parent / "drawing_templates"
WIDTH = 540
MIN_HEIGHT, MAX_HEIGHT = 675, 2400
PNG_WIDTH = 1080
PAD = 32
CONTENT = WIDTH - 2 * PAD
LINE = 19.0  # px between lines of 13.5 px text
SMALL_LINE = 17.0  # px between lines of 12 px text
COLUMN_GAP = 20
COLUMN = (CONTENT - COLUMN_GAP) / 2
STEP_X = PAD + 36  # a step's title and words, right of its number
FOOTER = 64  # the rule and the footer line under everything
MORE_TEXT = "The rest is in the cookbook."
LABEL = "MADICEN FAMILY RECIPE"
SPACING = 1.6  # the label's letter spacing, px
STEPS_HEADING = "Let\u2019s cook"

# Its own colours (not the day card's): a cookbook page in light, the same page at night.
COLORS: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F8F5EE",
        "title": "#22382B",
        "ink": "#2A2D2A",
        "muted": "#73766F",
        "accent": "#B5412B",
        "rule": "#E3DDD1",
    },
    "dark": {
        "bg": "#181B19",
        "title": "#B5D3B0",
        "ink": "#E6E3DC",
        "muted": "#9A9D96",
        "accent": "#E58A6C",
        "rule": "#2F3530",
    },
}


@dataclass(frozen=True)
class Item:
    kind: str  # "group", "ingredient", "also", "step", "note"
    lines: tuple[str, ...]
    number: int = 0
    amount: str = ""  # an ingredient's amount, drawn bold at the front of its first line
    title: str = ""  # a step's short title


def split_amount(text: str) -> tuple[str, str]:
    """The amount at the front of an ingredient line ("2 Tbsp (28 g)") and the rest, or
    ("", text) when it has none."""
    found = AMOUNT.match(text)
    if found is None:
        return "", text
    end = found.end()
    bracket = BRACKET.match(text, end)
    if bracket is not None:
        end = bracket.end()
    if end < len(text) and not text[end].isspace():
        return "", text  # "1x", "3-ingredient": not an amount
    amount, rest = text[:end].strip(), text[end:].strip()
    return (amount, rest) if rest else ("", text)


def ingredient(text: str, width: float) -> Item:
    amount, _ = split_amount(text)
    extra = text_width(amount, 13.5, True) - text_width(amount, 13.5) if amount else 0.0
    lines = tuple(wrap(text, 13.5, width - extra, 3))
    return Item("ingredient", lines, amount=amount if lines[0].startswith(amount) else "")


def ingredient_blocks(
    recipe: Recipe, show: Callable[[str], str] | None
) -> tuple[list[tuple[str, list[Item]]], str]:
    """The ingredients as (group, items) blocks, drawn in two columns, and the "Also
    needed" line: in a recipe without groups, the lines with no amount (salt & pepper)."""
    texts = [(line.group, show(line.text) if show is not None else line.text)
             for line in recipe.ingredients]  # fmt: skip  # GW2: "With grams"
    grouped = any(group for group, _ in texts)
    measured = [t for _, t in texts if split_amount(t)[0]]
    also: list[str] = []
    if not grouped and measured and len(measured) < len(texts):
        also = [t for _, t in texts if not split_amount(t)[0]]
        texts = [("", t) for t in measured]
    blocks: list[tuple[str, list[Item]]] = []
    for group, text in texts:
        if not blocks or group != blocks[-1][0]:
            blocks.append((group, []))
        blocks[-1][1].append(ingredient(text, COLUMN))
    return blocks, ", ".join(also)


def items(
    recipe: Recipe, show: Callable[[str], str] | None = None, titles: list[str] | None = None
) -> list[Item]:
    """Everything after the ingredients, in order."""
    if titles is None or len(titles) != len(recipe.steps):
        titles = [fallback_title(step.text) for step in recipe.steps]
    out = []
    step_group = ""
    for n, (step, title) in enumerate(zip(recipe.steps, titles, strict=True), start=1):
        if step.group and step.group != step_group:
            out.append(Item("group", tuple(wrap(step.group, 13.5, CONTENT, 2, bold=True))))
            step_group = step.group
        lines = tuple(wrap(step.text, 13.5, CONTENT - 36, 8))
        out.append(Item("step", lines, n, title=fit(title, 14, CONTENT - 36, bold=True)))
    for note in recipe.notes:
        out.append(Item("note", tuple(wrap(note, 12, CONTENT, 4))))
    if recipe.source_text:
        out.append(Item("note", tuple(wrap(f"Source: {recipe.source_text}", 12, CONTENT, 2))))
    return out


def spaced(text: str, size: float) -> float:
    """The width of capitals drawn with the label's letter spacing."""
    return text_width(text, size, True) + SPACING * len(text)


def label(where: str) -> str:
    """The line over the title: where it is in the cookbook, then LABEL. LABEL stays whole;
    a long section is shortened to fit."""
    if not where:
        return LABEL
    room = CONTENT - spaced(f" / {LABEL}", 11)
    where = where.upper()
    if spaced(where, 11) > room:
        where = fit(where, 11, room - SPACING * len(where), bold=True)
    return f"{where} / {LABEL}" if where else LABEL


def footer_text(recipe: Recipe) -> str:
    steps = len(recipe.steps)
    name = re.sub(r"\s+and\s+", " + ", recipe.name, flags=re.IGNORECASE).upper()
    count = f"{steps} STEP{'' if steps == 1 else 'S'}"
    return f"{fit(name, 10.5, CONTENT - 120, bold=True)}  /  {count}"


def view(
    recipe: Recipe,
    theme: str = "light",
    show: Callable[[str], str] | None = None,
    titles: list[str] | None = None,
) -> dict[str, Any]:
    colors = COLORS.get(theme, COLORS["light"])
    where = recipe.section + (f" / {recipe.subsection}" if recipe.subsection else "")
    eyebrow = label(where)
    title = wrap(recipe.name, 30, CONTENT, 3, bold=True)
    title_lines = [{"y": 82 + 36 * k, "text": t} for k, t in enumerate(title)]
    rule_y = 82 + 36 * (len(title) - 1) + 20
    limit = MAX_HEIGHT - FOOTER - 40
    placed: list[dict[str, Any]] = []
    cut = False

    def lines(item: Item, x: float, top: float, step: float = LINE) -> list[dict[str, Any]]:
        return [
            {"x": x, "y": top + step * (k + 1) - 5, "text": t} for k, t in enumerate(item.lines)
        ]

    y = rule_y + 46.0
    placed.append({"kind": "heading", "lines": [{"x": PAD, "y": y, "text": "Ingredients"}]})
    y += 10
    blocks, also = ingredient_blocks(recipe, show)
    for group, block in blocks:
        top = y + (8 if group else 0)
        if group:
            group_lines = wrap(group, 13.5, CONTENT, 2, bold=True)
            if top + LINE * len(group_lines) > limit:
                cut = True
                break
            heading = Item("group", tuple(group_lines))
            placed.append({"kind": "group", "lines": lines(heading, PAD, top)})
            top += LINE * len(group_lines)
        half = (len(block) + 1) // 2
        bottom = top
        for column, x in ((block[:half], PAD), (block[half:], PAD + COLUMN + COLUMN_GAP)):
            row = top
            for item in column:
                row += 8
                if row + LINE * len(item.lines) > limit:
                    cut = True
                    break
                placed.append({"kind": "ingredient", "amount": item.amount,
                               "lines": lines(item, x, row)})  # fmt: skip
                row += LINE * len(item.lines)
            bottom = max(bottom, row)
        y = bottom
        if cut:
            break
    if also and not cut:
        note = Item("also", tuple(wrap(f"Also needed: {also}", 12, CONTENT, 3)))
        placed.append({"kind": "note", "lines": lines(note, PAD, y + 12, SMALL_LINE)})
        y += 12 + SMALL_LINE * len(note.lines)
    if not cut:
        y += 44
        placed.append({"kind": "heading", "lines": [{"x": PAD, "y": y, "text": STEPS_HEADING}]})
        y += 6
        for item in items(recipe, show, titles):
            if item.kind == "step":
                height = 16 + LINE * (len(item.lines) + 1)
                if y + height > limit:
                    cut = True
                    break
                placed.append(
                    {
                        "kind": "step",
                        "number": f"{item.number:02d}",
                        "title": item.title,
                        "title_y": y + 16 + LINE - 5,
                        "lines": lines(item, STEP_X, y + 16 + LINE),
                    }
                )
            else:
                gap = 18.0 if item.kind == "group" else 10.0
                step = LINE if item.kind == "group" else SMALL_LINE
                height = gap + step * len(item.lines)
                if y + height > limit:
                    cut = True
                    break
                placed.append({"kind": item.kind, "lines": lines(item, PAD, y + gap, step)})
            y += height
    more_y = y + 30
    if cut:
        y = more_y
    height = round(max(MIN_HEIGHT, y + 28 + FOOTER))
    return {
        "width": WIDTH,
        "height": height,
        "pad": PAD,
        "c": colors,
        "eyebrow": eyebrow,
        "spacing": SPACING,
        "title_lines": title_lines,
        "rule_y": rule_y,
        "rule_w": CONTENT,
        "items": placed,
        "step_x": STEP_X,
        "more": MORE_TEXT if cut else "",
        "more_y": more_y,
        "footer": footer_text(recipe),
        "footer_rule_y": height - FOOTER + 20,
        "footer_y": height - 26,
    }


def card_svg(
    recipe: Recipe,
    theme: str = "light",
    show: Callable[[str], str] | None = None,
    titles: list[str] | None = None,
) -> str:
    return write_svg("recipe_card.svg", [TEMPLATES], **view(recipe, theme, show, titles))


async def card_png(services: Any, member: Member, recipe: Recipe) -> bytes | None:
    drawings = services.maybe(keys.drawings)
    if drawings is None:
        return None
    theme = services.store.preferences(member.id, DrawingsPreferences).picture_theme
    from themi_home.gram_weights import viewer_lines

    cooking = services.maybe(keys.cooking)  # CK12's step titles, kept: no model call here
    titles = cooking.titles.titles(recipe) if cooking is not None else None
    svg = card_svg(recipe, theme, viewer_lines(services, member.id), titles)
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
