"""Keeping a liked recipe in the family cookbook (RC5).

[Save to cookbook] on a web recipe (or "we liked that one, add it to the cookbook") picks
the section from the recipe's words (Desserts for brownies, Entrees for a curry...) or
asks with a button per section, shows the entry as it will appear in the doc, and stages
`cookbook_add` (household, Tier 1 to start: the approval card).

The write is one `documents.batchUpdate` against the revision just read
(`requiredRevisionId`), inserted at the end of the section, before the next Heading 1: the
name as Heading 4, "Ingredients" and "Instructions" as Heading 5, a line per ingredient and
step, "Source: <site> (<link>)" and `-----`, as the doc writes its own. If someone edited
the doc in between, it's read again and tried once more. Afterwards the web recipe becomes
the cookbook's (its new heading id), so it's found as theirs.

Changing a recipe already in the cookbook is the doc's job: Themi says so, with the link.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.connectors.gdocs import DocsConflict, DocsError
from themi.core import cookbook as book
from themi.core.recipes import PICTURE_SOURCE, Recipe, Recipes
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "cookbook_add"
EXECUTOR = "cookbook.add"
SECTION_WORDS: list[tuple[str, str]] = [
    ("Desserts", r"cookies?|cakes?|brownies?|pies?|pudding|ice cream|gelato|tart|crumble|"
                 r"cupcakes?|fudge|frosting|sweet|dessert|truffles?"),
    ("Breakfast", r"pancakes?|waffles?|scones?|oats|oatmeal|granola|french toast|muffins?|"
                  r"scramble|breakfast|hash ?browns?"),
    ("Beverages", r"smoothie|latte|tea|lemonade|syrup|shrub|cocoa|drink|juice"),
    ("Appetizers", r"dip|appetizer|bites|hummus|crostini|nachos|spring rolls?|dumplings?"),
    ("Sides", r"salad|slaw|roasted|side|bread|rolls|fries|mash(?:ed)?"),
    ("Snacks", r"snack|energy balls?|crackers|popcorn|bars?"),
    ("Ingredients", r"sauce|dressing|mayo(?:nnaise)?|pesto|gravy|cheese|seitan|crust|stock"),
    ("Entrees", r"soup|curry|pasta|noodles?|stew|tacos?|chili|bowl|stir[- ]?fry|pad|burgers?|"
                r"lasagna|risotto|casserole|pie|tofu|tempeh|masala|biryani|ramen"),
]  # fmt: skip


def guess_section(recipe: Recipe, sections: list[str]) -> str | None:
    """The cookbook section the recipe's name says, if the doc has it."""
    have = {s.lower(): s for s in sections}
    for section, words in SECTION_WORDS:
        if section.lower() in have and re.search(rf"\b(?:{words})\b", recipe.name, re.IGNORECASE):
            return have[section.lower()]
    return None


class CookbookSave:
    def __init__(self, services: Services, recipes: Recipes) -> None:
        self.services = services
        self.recipes = recipes
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.autonomy.executors.register(EXECUTOR)(self._execute)
        s.recipe_buttons["save"] = self.on_save
        s.recipe_buttons["save_in"] = self.on_save_in
        s.recipe_buttons["save_no"] = self.on_save_no
        s.tools.register(save_recipe_to_cookbook)

    # ----- choosing and staging -----------------------------------------------------------

    def sections(self) -> list[str]:
        rows = self.db.query(
            "SELECT section, MIN(position) AS first FROM recipes WHERE source = 'doc' "
            "AND removed_at IS NULL AND section != '' GROUP BY section ORDER BY first"
        )
        return [r["section"] for r in rows if r["section"].lower() != book.REFERENCES]

    def entry(self, recipe: Recipe) -> list[tuple[str, str]]:
        site = recipe.source_text or ""
        source = f"{site} ({recipe.url})" if site and recipe.url else (recipe.url or site)
        if not recipe.url and site == PICTURE_SOURCE:
            source = "a photo"  # F34m: "your picture" is only theirs to read
        return book.entry_text(
            recipe.name, list(recipe.ingredients), list(recipe.steps), list(recipe.notes), source
        )

    def preview(self, recipe: Recipe, section: str) -> str:
        lines = [f"Here's how it would go in the cookbook, under {section}:"]
        lines += [f"> {text}" for text, _ in self.entry(recipe)[:-1]]
        return "\n".join(lines)

    async def offer(self, member: Member, recipe: Recipe, section: str | None = None) -> str:
        """Ask which section, or show the entry and stage it. Returns what was sent."""
        if self.recipes.doc_id is None:
            raise DocsError("There's no cookbook doc yet: someone can choose it on Accounts.")
        sections = self.sections()
        chosen = section or guess_section(recipe, sections)
        outbox = self.services.outbox
        if chosen is None:
            text = f"Which part of the cookbook should {recipe.name} go in?"
            await outbox.send(
                member, text, priority=Priority.REPLY, kind="recipes",
                buttons=[
                    Button(f"Under {s}"[:60], "recipe",
                           {"action": "save_in", "id": recipe.id, "section": s})
                    for s in sections
                ],
            )  # fmt: skip
            return text
        preview = self.preview(recipe, chosen)
        await outbox.send(member, preview, priority=Priority.REPLY, kind="recipes",
                          link_preview=False)  # fmt: skip
        await self.services.autonomy.stage(
            CATEGORY,
            member,
            f'Add "{recipe.name}" to the cookbook under {chosen}',
            {"recipe": recipe.id, "section": chosen},
            EXECUTOR,
            interactive=True,
        )
        return preview

    # ----- writing ------------------------------------------------------------------------

    async def _execute(self, payload: dict[str, Any], context: ExecutionContext) -> str:
        recipe = self.recipes.get(int(payload["recipe"]))
        section = str(payload["section"])
        if recipe is None:
            return "That recipe isn't kept any more, so nothing was added."
        if recipe.source == "doc":
            return f"{recipe.name} is in the cookbook already."  # a retry after it went in
        settings = self.recipes.settings()
        if not settings["doc_id"] or settings["account_id"] is None:
            raise DocsError("There's no cookbook doc to add to.")
        client = self.recipes.client(settings["account_id"])
        doc_id = settings["doc_id"]
        before = {r["key"] for r in self.db.query("SELECT key FROM recipes WHERE source = 'doc'")}
        for attempt in (1, 2):
            parsed = book.parse(await client.get(doc_id))
            at = book.insert_at(parsed, section)
            try:
                await client.batch_update(
                    doc_id, book.entry_requests(at, self.entry(recipe)), parsed.revision
                )
                break
            except DocsConflict:
                if attempt == 2:
                    raise DocsError(
                        "The cookbook kept changing while Themi wrote to it; nothing was added."
                    ) from None
                log.info("The cookbook changed under a write; reading it again")
        after = book.parse(await client.get(doc_id))
        added = next(
            (r for r in reversed(after.recipes) if r.name == recipe.name and r.key not in before),
            None,
        )
        if added is not None:  # the web recipe becomes the cookbook's own
            self.db.execute(
                "UPDATE recipes SET key = ?, source = 'doc', section = ?, updated_at = ? "
                "WHERE id = ?",
                (added.key, section, to_utc_iso(clock.now()), recipe.id),
            )
        await self.recipes.sync(force=True)
        kept = self.recipes.get(recipe.id)
        link = self.recipes.link(kept) if kept else None
        return f"Added {recipe.name} to the cookbook under {section}." + (
            f" {link}" if link else ""
        )

    # ----- buttons ------------------------------------------------------------------------

    async def _offer_from(self, event: InboundEvent, section: str | None) -> None:
        assert event.button is not None
        recipe = self.recipes.get(int(event.button.payload.get("id", 0)))
        if recipe is None:
            return
        member = self.services.store.get_member(event.member.id)
        try:
            await self.offer(member, recipe, section)
        except DocsError as exc:
            await self.services.outbox.send(member, str(exc), priority=Priority.REPLY)

    async def on_save(self, event: InboundEvent) -> None:
        await self._offer_from(event, None)

    async def on_save_in(self, event: InboundEvent) -> None:
        assert event.button is not None
        await self._offer_from(event, str(event.button.payload.get("section") or ""))

    async def on_save_no(self, event: InboundEvent) -> None:
        assert event.button is not None
        if event.button.message_id is not None:
            member = self.services.store.get_member(event.member.id)
            await self.services.outbox.edit(
                member, event.button.message_id, "Left it out of the cookbook."
            )


def _saver(ctx: ToolContext) -> CookbookSave:
    found = ctx.services.cookbook_save
    if found is None:
        raise ToolFailed("Recipes aren't set up.")
    return found


@tool(
    "save_recipe_to_cookbook",
    "Add a web recipe they liked to the family cookbook doc, when they ask ('we liked that "
    "one, add it to the cookbook'): recipe, its name, or '' for the web recipe they had "
    "last; section, a cookbook section they named, or ''. Shows the entry and asks for a "
    "yes. A recipe already in the cookbook is changed in the doc itself, not here.",
    {"recipe": {"type": "string"}, "section": {"type": "string"}},
)
async def save_recipe_to_cookbook(ctx: ToolContext, args: dict[str, Any]) -> str:
    saver = _saver(ctx)
    name = str(args.get("recipe") or "").strip()
    if name:
        matches = saver.recipes.find(name, charts=False)
        recipe = matches[0].recipe if matches else None
    else:
        row = saver.db.one(
            "SELECT id FROM recipes WHERE source = 'web' AND removed_at IS NULL "
            "ORDER BY updated_at DESC, id DESC LIMIT 1"
        )
        recipe = saver.recipes.get(row["id"]) if row else None
    if recipe is None:
        raise ToolFailed("Which recipe? There's no web recipe like that kept. Ask them.")
    if recipe.source == "doc":
        link = saver.recipes.link(recipe)
        raise ToolDeclined(
            f"{recipe.name} is in the cookbook already; changing it happens in the doc itself"
            + (f" ({link})" if link else "")
            + ". Say so."
        )
    section = str(args.get("section") or "").strip()
    if section and section.lower() not in {s.lower() for s in saver.sections()}:
        section = ""
    try:
        sent = await saver.offer(ctx.member, recipe, section or None)
    except DocsError as exc:
        raise ToolFailed(f"{exc} Say so.") from exc
    ctx.cards.append(sent)
    return "Sent them the entry and an approval card. Nothing is in the doc until they say yes."
