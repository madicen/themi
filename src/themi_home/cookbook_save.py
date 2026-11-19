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

F49i (idea #224): a recipe from Recipes to try that's a keeper moves into the cookbook (the
end-of-cooking wrap's "A keeper?", the chat card's [Add to the cookbook], or "move X to the
cookbook"). The same approval card copies it into the cookbook, as the try doc has it, and
then deletes it from the try doc (its heading through its `-----`, one deleteContentRange
against the revision just read), so it's in one place. The stored recipe becomes the
cookbook's, not a new row, so its cooking history stays with it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi_google.connectors.gdocs import DocsConflict, DocsError
from themi_home import cookbook as book
from themi_home import home_groups
from themi_home.cookbook import Line
from themi_home.groups import COOKING
from themi_home.recipes import (
    COOKBOOK,
    DOC_NAMES,
    NO_TRY_DOC_TEXT,
    PICTURE_SOURCE,
    TO_TRY,
    TRY_KEY,
    Recipe,
    Recipes,
)

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "cookbook_add"
EXECUTOR = "cookbook.add"
KEEP_LABEL = "Add to the cookbook"
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
        s.recipe_buttons["save_try"] = self.on_save_try  # F49h
        s.recipe_buttons["keep"] = self.on_keep  # F49i
        s.recipe_buttons["keep_in"] = self.on_keep_in
        s.recipe_buttons["keep_no"] = self.on_keep_no
        s.tools.register(save_recipe_to_cookbook)

    # ----- choosing and staging -----------------------------------------------------------

    def sections(self) -> list[str]:
        rows = self.db.query(
            "SELECT section, MIN(position) AS first FROM recipes WHERE source = 'doc' "
            "AND removed_at IS NULL AND section != '' GROUP BY section ORDER BY first"
        )
        return [r["section"] for r in rows if r["section"].lower() != book.REFERENCES]

    def entry(self, recipe: Recipe) -> list[tuple[str, str]]:
        if recipe.source == "doc":  # F49i: a keeper from Recipes to try, as Themi reads it
            return book.entry_text(recipe.name, list(recipe.ingredients), list(recipe.steps),
                                   list(recipe.notes), recipe.source_text)  # fmt: skip
        site = recipe.source_text or ""
        source = f"{site} ({recipe.url})" if site and recipe.url else (recipe.url or site)
        if not recipe.url and site == PICTURE_SOURCE:
            source = "a photo"  # F34m: "your picture" is only theirs to read
        return book.entry_text(
            recipe.name, self._with_grams(recipe), list(recipe.steps), list(recipe.notes), source
        )

    def _with_grams(self, recipe: Recipe) -> list[Line]:
        """GW7 (Michael): a web recipe goes into the cookbook with the grams Themi knows for
        its lines ("1 cup almond flour (96 g)"); a line with no known weight as written."""
        from themi_home.gram_weights import GramWeights, weigh

        weights = self.services.maybe(GramWeights)
        if weights is None:
            return list(recipe.ingredients)
        known = weights.book()
        return [replace(i, text=weigh(i.text, known).line) for i in recipe.ingredients]

    def preview(self, recipe: Recipe, section: str) -> str:
        lines = [f"Here's how it would go in the cookbook, under {section}:"]
        lines += [f"> {text}" for text, _ in self.entry(recipe)[:-1]]
        if recipe.to_try:
            lines.append(f"Then it comes out of {DOC_NAMES[TO_TRY]}.")
        return "\n".join(lines)

    @staticmethod
    def keep_buttons(recipe: Recipe) -> list[Button]:
        """F49i: [Add to the cookbook] [Not yet], for a recipe from Recipes to try."""
        return [
            Button(KEEP_LABEL, "recipe", {"action": "keep", "id": recipe.id}),
            Button("Not yet", "recipe", {"action": "keep_no", "id": recipe.id}),
        ]

    async def offer_to_try(self, member: Member, recipe: Recipe) -> str:
        """F49h (idea #224): show the entry and stage it for the Recipes to try doc, at its
        end (no sections to choose). Returns what was sent."""
        if self.recipes.try_doc_id is None:
            raise DocsError(NO_TRY_DOC_TEXT)
        lines = [f"Here's how it would go in {DOC_NAMES[TO_TRY]}:"]
        lines += [f"> {text}" for text, _ in self.entry(recipe)[:-1]]
        preview = "\n".join(lines)
        await self.services.outbox.send(member, preview, priority=Priority.REPLY,
                                        kind="recipes", link_preview=False)  # fmt: skip
        await self._replace_waiting(member, recipe, DOC_NAMES[TO_TRY])
        await self.services.autonomy.stage(
            CATEGORY,
            member,
            f'Add "{recipe.name}" to {DOC_NAMES[TO_TRY]}',
            {"recipe": recipe.id, "section": "", "book": TO_TRY},
            EXECUTOR,
            interactive=True,
        )
        return preview

    async def offer(self, member: Member, recipe: Recipe, section: str | None = None) -> str:
        """Ask which section, or show the entry and stage it. Returns what was sent. A recipe
        from Recipes to try is moved (F49i): copied in, then taken out of the try doc."""
        if self.recipes.doc_id is None:
            raise DocsError("There's no cookbook doc yet: someone can choose it on Accounts.")
        keep = recipe.source == "doc"
        if keep and not recipe.to_try:
            raise DocsError(f"{recipe.name} is in the cookbook already.")
        sections = self.sections()
        chosen = section or guess_section(recipe, sections)
        outbox = self.services.outbox
        if chosen is None:
            text = f"Which part of the cookbook should {recipe.name} go in?"
            await outbox.send(
                member, text, priority=Priority.REPLY, kind="recipes",
                buttons=[
                    Button(f"Under {s}"[:60], "recipe",
                           {"action": "keep_in" if keep else "save_in", "id": recipe.id,
                            "section": s})
                    for s in sections
                ],
            )  # fmt: skip
            return text
        preview = self.preview(recipe, chosen)
        await outbox.send(member, preview, priority=Priority.REPLY, kind="recipes",
                          link_preview=False)  # fmt: skip
        await self._replace_waiting(member, recipe, chosen)
        summary = f'Add "{recipe.name}" to the cookbook under {chosen}'
        payload: dict[str, Any] = {"recipe": recipe.id, "section": chosen}
        if keep:
            summary = f'Move "{recipe.name}" to the cookbook under {chosen}, out of Recipes to try'
            payload["keep"] = True
        await self.services.autonomy.stage(
            CATEGORY, member, summary, payload, EXECUTOR, interactive=True
        )
        return preview

    async def _replace_waiting(self, member: Member, recipe: Recipe, section: str) -> None:
        """F45a (bug #212): "save it under breakfast" after the Sides card: the card still
        waiting for this recipe gives way, so only one waits."""
        for row in self.db.query(
            "SELECT id, payload FROM pending_actions WHERE category = ? AND member_id = ? "
            "AND status IN ('pending', 'snoozed') ORDER BY id",
            (CATEGORY, member.id),
        ):
            if json.loads(row["payload"]).get("recipe") == recipe.id:
                await self.services.autonomy.withdraw(
                    row["id"], f"Replaced: under {section} instead."
                )

    # ----- writing ------------------------------------------------------------------------

    async def _execute(self, payload: dict[str, Any], context: ExecutionContext) -> str:
        recipe = self.recipes.get(int(payload["recipe"]))
        section = str(payload["section"])
        if payload.get("keep"):
            return await self._keep(recipe, section)
        which = str(payload.get("book") or COOKBOOK)  # F49h: or Recipes to try
        where = DOC_NAMES[which]
        if recipe is None:
            return "That recipe isn't kept any more, so nothing was added."
        if recipe.source == "doc":
            return f"{recipe.name} is in {DOC_NAMES[recipe.book]} already."  # a retry
        settings = self.recipes.settings(which)
        if not settings["doc_id"] or settings["account_id"] is None:
            raise DocsError(f"There's no {where.removeprefix('the ')} doc to add to.")
        client = self.recipes.client(settings["account_id"])
        doc_id = settings["doc_id"]
        prefix = TRY_KEY if which == TO_TRY else ""
        before = {
            r["key"].removeprefix(prefix)
            for r in self.db.query(
                "SELECT key FROM recipes WHERE source = 'doc' AND book = ?", (which,)
            )
        }
        entry = self.entry(recipe)
        await self._write(client, doc_id, where, lambda d: book.entry_requests(
            book.insert_at(book.parse(d), section), entry))  # fmt: skip
        after = book.parse(await client.get(doc_id))
        added = next(
            (r for r in reversed(after.recipes) if r.name == recipe.name and r.key not in before),
            None,
        )
        if added is not None:  # the web recipe becomes the doc's own
            self.db.execute(
                "UPDATE recipes SET key = ?, source = 'doc', section = ?, book = ?, "
                "updated_at = ? WHERE id = ?",
                (prefix + added.key, added.section if prefix else section, which,
                 to_utc_iso(clock.now()), recipe.id),
            )  # fmt: skip
        await self.recipes.sync(force=True, which=which)
        kept = self.recipes.get(recipe.id)
        link = self.recipes.link(kept) if kept else None
        under = f" under {section}" if section else ""
        return f"Added {recipe.name} to {where}{under}." + (f" {link}" if link else "")

    @staticmethod
    async def _write(
        client: Any,
        doc_id: str,
        where: str,
        requests: Callable[[dict[str, Any]], list[dict[str, Any]] | None],
        *,
        nothing: str = "nothing was added",
    ) -> bool:
        """One batchUpdate against the revision just read; read again and tried once more if
        someone edited in between. False when `requests` found nothing to do."""
        for attempt in (1, 2):
            document = await client.get(doc_id)
            wanted = requests(document)
            if wanted is None:
                return False
            try:
                await client.batch_update(doc_id, wanted, str(document.get("revisionId", "")))
                return True
            except DocsConflict:
                if attempt == 2:
                    raise DocsError(
                        f"{where.capitalize()} kept changing while Themi wrote to it; {nothing}."
                    ) from None
                log.info("%s changed under a write; reading it again", where.capitalize())
        raise AssertionError("unreachable")

    async def _keep(self, recipe: Recipe | None, section: str) -> str:
        """F49i: copy a recipe from Recipes to try into the cookbook, then delete it from the
        try doc. The stored recipe becomes the cookbook's (its key, section and book)."""
        if recipe is None:
            return "That recipe isn't kept any more, so nothing was moved."
        if not recipe.to_try:
            return f"{recipe.name} is in the cookbook already."  # a retry
        cookbook, trying = self.recipes.settings(COOKBOOK), self.recipes.settings(TO_TRY)
        if not cookbook["doc_id"] or cookbook["account_id"] is None:
            raise DocsError("There's no cookbook doc to add to.")
        if not trying["doc_id"] or trying["account_id"] is None:
            raise DocsError(NO_TRY_DOC_TEXT)
        try_client = self.recipes.client(trying["account_id"])
        await self.recipes.sync(force=True, which=TO_TRY)  # as the try doc is now
        fresh = self.recipes.get(recipe.id)
        if fresh is None or fresh.removed or not fresh.to_try:
            return f"{recipe.name} isn't in {DOC_NAMES[TO_TRY]} any more, so nothing was moved."
        recipe, key = fresh, fresh.key.removeprefix(TRY_KEY)
        entry = self.entry(recipe)  # what the preview showed
        client, doc_id = self.recipes.client(cookbook["account_id"]), cookbook["doc_id"]
        before = {
            r["key"]
            for r in self.db.query(
                "SELECT key FROM recipes WHERE source = 'doc' AND book = ?", (COOKBOOK,)
            )
        }
        await self._write(client, doc_id, "the cookbook", lambda d: book.entry_requests(
            book.insert_at(book.parse(d), section), entry))  # fmt: skip
        after = book.parse(await client.get(doc_id))
        added = next(
            (r for r in reversed(after.recipes) if r.name == recipe.name and r.key not in before),
            None,
        )
        if added is not None:  # the same row, now the cookbook's: its history stays
            self.db.execute(
                "UPDATE recipes SET key = ?, source = 'doc', section = ?, subsection = '', "
                "book = ?, updated_at = ? WHERE id = ?",
                (added.key, added.section, COOKBOOK, to_utc_iso(clock.now()), recipe.id),
            )

        def deleting(document: dict[str, Any]) -> list[dict[str, Any]] | None:
            at = book.entry_range(document, key, recipe.name)
            return book.delete_requests(at) if at else None  # None: gone already

        out = ""
        try:
            await self._write(try_client, trying["doc_id"], DOC_NAMES[TO_TRY], deleting,
                              nothing="it's in both now")  # fmt: skip
        except DocsError as exc:
            out = f" It's still in {DOC_NAMES[TO_TRY]} too ({exc}): delete it there by hand."
        await self.recipes.sync(force=True, which=COOKBOOK)
        await self.recipes.sync(force=True, which=TO_TRY)
        kept = self.recipes.get(recipe.id)
        link = self.recipes.link(kept) if kept else None
        moved = f"Moved {recipe.name} to the cookbook under {section}"
        if not out:
            moved += f", and out of {DOC_NAMES[TO_TRY]}"
        return f"{moved}.{out}" + (f" {link}" if link else "")

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

    async def on_save_try(self, event: InboundEvent) -> None:
        """F49h: [Save to try] on a web recipe's card."""
        assert event.button is not None
        recipe = self.recipes.get(int(event.button.payload.get("id", 0)))
        if recipe is None:
            return
        member = self.services.store.get_member(event.member.id)
        try:
            await self.offer_to_try(member, recipe)
        except DocsError as exc:
            await self.services.outbox.send(member, str(exc), priority=Priority.REPLY)

    async def on_keep(self, event: InboundEvent) -> None:
        """F49i: [Add to the cookbook] on a recipe from Recipes to try."""
        await self._offer_from(event, None)

    async def on_keep_in(self, event: InboundEvent) -> None:
        assert event.button is not None
        await self._offer_from(event, str(event.button.payload.get("section") or ""))

    async def on_keep_no(self, event: InboundEvent) -> None:
        assert event.button is not None
        if event.button.message_id is not None:
            member = self.services.store.get_member(event.member.id)
            await self.services.outbox.edit(
                member, event.button.message_id, f"Left it in {DOC_NAMES[TO_TRY]} for now."
            )

    async def on_save_no(self, event: InboundEvent) -> None:
        assert event.button is not None
        if event.button.message_id is not None:
            member = self.services.store.get_member(event.member.id)
            await self.services.outbox.edit(
                member, event.button.message_id, "Left it out of the cookbook."
            )


def _saver(ctx: ToolContext) -> CookbookSave:
    found = ctx.services.maybe(keys.cookbook_save)
    if found is None:
        raise ToolFailed("Recipes aren't set up.")
    return found


@tool(
    "save_recipe_to_cookbook",
    "Add a web recipe to a family recipe doc, when they ask: where=cookbook for one they "
    "liked ('we liked that one, add it to the cookbook'), where=to_try for one they want to "
    "try ('save that to try', 'add it to the try list', 'not cookbook-worthy yet'). Also "
    "where=cookbook for one from Recipes to try that's a keeper ('move X to the cookbook'): "
    "it moves, out of Recipes to try. recipe, its name, or '' for the web recipe they had "
    "last; section, a cookbook section they named, or ''. Shows the entry and asks for a yes. "
    "A recipe already in the cookbook is changed in the doc itself, not here.",
    {
        "recipe": {"type": "string"},
        "section": {"type": "string"},
        "where": {"type": "string", "enum": [COOKBOOK, TO_TRY]},
    },
)
async def save_recipe_to_cookbook(ctx: ToolContext, args: dict[str, Any]) -> str:
    saver = _saver(ctx)
    name = str(args.get("recipe") or "").strip()
    if name:
        matches = saver.recipes.find(name, charts=False)
        recipe = matches[0].recipe if matches else None
        if recipe is not None and str(args.get("where") or COOKBOOK) == COOKBOOK:
            same = [m.recipe for m in matches if m.recipe.name.lower() == recipe.name.lower()]
            recipe = next((r for r in same if r.to_try), recipe)  # F49i: the one to move
    else:
        row = saver.db.one(
            "SELECT id FROM recipes WHERE source = 'web' AND removed_at IS NULL "
            "ORDER BY updated_at DESC, id DESC LIMIT 1"
        )
        recipe = saver.recipes.get(row["id"]) if row else None
    if recipe is None:
        raise ToolFailed("Which recipe? There's no web recipe like that kept. Ask them.")
    where = str(args.get("where") or COOKBOOK)
    if recipe.source == "doc" and not (recipe.to_try and where == COOKBOOK):
        link = saver.recipes.link(recipe)
        raise ToolDeclined(
            f"{recipe.name} is in {DOC_NAMES[recipe.book]} already; changing it happens in the "
            "doc itself" + (f" ({link})" if link else "") + ". Say so."
        )
    if where == TO_TRY:  # F49h
        try:
            sent = await saver.offer_to_try(ctx.member, recipe)
        except DocsError as exc:
            raise ToolFailed(f"{exc} Say so.") from exc
        ctx.cards.append(sent)
        return (
            "Sent them the entry and an approval card for Recipes to try. Nothing is in the "
            "doc until they say yes."
        )
    section = str(args.get("section") or "").strip()
    if section and section.lower() not in {s.lower() for s in saver.sections()}:
        section = ""
    try:
        sent = await saver.offer(ctx.member, recipe, section or None)
    except DocsError as exc:
        raise ToolFailed(f"{exc} Say so.") from exc
    ctx.cards.append(sent)
    if recipe.to_try:
        return (
            "Sent them the entry and an approval card to move it into the cookbook and out of "
            "Recipes to try. Nothing changes until they say yes."
        )
    return "Sent them the entry and an approval card. Nothing is in the doc until they say yes."


class CookbookSaveModule(Module):
    """RC5: saving a liked recipe to the cookbook."""

    name = "cookbook_save"
    title = "Save to the cookbook"
    group = COOKING
    summary = "Saves a recipe the family liked to the family cookbook."
    tool_groups = (home_groups.RECIPES,)
    requires = ("recipes",)

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(CookbookSave(ctx.services, ctx.get(Recipes)))
        ctx.services.get(keys.cookbook_save).install()
