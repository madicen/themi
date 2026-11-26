"""Recipes on the website (RC1a, RC6; CK1 retired the kitchen view for /session).

RC1a: the cookbook page under Accounts. A person picks the family's recipe doc in Google's
file picker (scope `drive.file`, so Themi can open that file and nothing else of theirs);
pasting the doc's link also works where Google already lets Themi open it (a doc picked
before, or `make dev`'s fake). The picker page is the one page that loads Google's own
scripts, so it gets its own, wider Content-Security-Policy.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import LinkedAccount, Member
from themi.core import keys
from themi.web.kit import Kit
from themi_google.connectors.gdocs import DocsError, doc_id_from
from themi_google.connectors.google import DRIVE_FILE_SCOPE
from themi_home.gram_weights import viewer_lines
from themi_home.quantities import NeedsYield, describe, scale_for, scale_line
from themi_home.recipe_card import card_png
from themi_home.recipe_groceries import BAKING_TEXT, SCALED_TEXT, is_baking
from themi_home.recipes import COOKBOOK, TO_TRY, Recipe, Recipes, search

NEW_BOOK = "new"  # RC8b: the select's "A new recipe book…"

SCALES = [
    ("½", "half"),
    ("1\u00d7", ""),
    ("2\u00d7", "double"),
    ("3\u00d7", "x3"),
]  # half, 1x, 2x, 3x

PICKER_HEADER = "X-Themi-Page"  # read and removed by the site's security headers


def _origin(url: str) -> str:
    """The scheme and host the browser's Google sign-in sees ("https://themi.example")."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def recipes() -> Recipes | None:
        return app.services.maybe(keys.recipes)

    def own_account(member: Member, account_id: int) -> LinkedAccount | None:
        return next((a for a in app.store.linked_accounts(member.id) if a.id == account_id), None)

    @router.get("/accounts/{account_id:int}/cookbook", response_class=HTMLResponse)
    def cookbook_page(request: Request, account_id: int) -> Response:
        session = kit.current(request)
        account = own_account(session.member, account_id)
        book = recipes()
        if account is None or book is None or not book.ready():
            return kit.redirect("/accounts", "That account isn't one of yours.")
        if not account.allows(DRIVE_FILE_SCOPE):
            return kit.redirect(
                "/accounts",
                "Link this account again (with Google Drive ticked) to pick the cookbook.",
            )
        config = book.config
        assert config is not None
        settings = book.settings()
        response = kit.with_flash(
            request,
            "cookbook.html",
            session,
            account=account,
            cookbook=settings,
            to_try=book.settings(TO_TRY),  # F49h
            shelves=[(b, book.count(b.key)) for b in book.shelves()],  # RC8b
            chosen_here=settings["account_id"] == account.id,
            picker=bool(config.picker_api_key and config.project_number),
            client_id=config.client_id,
            picker_key=config.picker_api_key,
            project_number=config.project_number,
            looks=[r for r in book.all(include_charts=True) if r.needs_look],
            origin=_origin(app.services.site_url) or str(request.base_url).rstrip("/"),
        )
        response.headers[PICKER_HEADER] = "picker"
        return response

    @router.post("/accounts/{account_id:int}/cookbook")
    async def choose_cookbook(request: Request, account_id: int) -> Response:
        session, form = await kit.checked(request)
        book = recipes()
        back = f"/accounts/{account_id}/cookbook"
        if book is None:
            return kit.not_set_up("/accounts", "Recipes aren't set up on this server.", "recipes")
        doc_id = doc_id_from(str(form.get("doc", "")))
        if doc_id is None:
            return kit.redirect(back, "That doesn't look like a Google Doc's link.")
        asked = str(form.get("book") or COOKBOOK)
        made = None
        if asked == NEW_BOOK:  # RC8b: a recipe book of its own
            try:
                made = book.add_book(str(form.get("name") or ""))
            except DocsError as exc:
                return kit.redirect(back, str(exc))
            which = made.key
        else:
            known = {b.key for b in book.books()}
            which = asked if asked in known else COOKBOOK  # F49h, RC8b
        try:
            said = await book.choose(session.member, account_id, doc_id, which)
        except DocsError as exc:
            if made is not None:  # a new book that couldn't be read isn't kept
                app.store.db.execute("DELETE FROM recipe_books WHERE id = ?", (made.id,))
            return kit.redirect(back, str(exc))
        return kit.redirect(back, said)

    @router.post("/accounts/{account_id:int}/cookbook/books/{key}")
    async def change_book(request: Request, account_id: int, key: str) -> Response:
        """RC8b: a book of its own's switches, its name, or stopping reading it."""
        _, form = await kit.checked(request)
        book = recipes()
        back = f"/accounts/{account_id}/cookbook"
        if book is None:
            return kit.not_set_up("/accounts", "Recipes aren't set up on this server.", "recipes")
        try:
            action = str(form.get("action") or "")
            if action == "remove":
                said = book.remove_book(key)
            elif action == "rename":
                said = book.rename_book(key, str(form.get("name") or ""))
            else:
                book.set_switches(
                    key,
                    meal_ideas=bool(form.get("meal_ideas")),
                    found_unasked=bool(form.get("found_unasked")),
                    save_button=bool(form.get("save_button")),
                )
                said = f"Saved how {book.book(key).name} shows up."
        except DocsError as exc:
            said = str(exc)
        return kit.redirect(back, said)

    @router.post("/accounts/{account_id:int}/cookbook/read")
    async def read_now(request: Request, account_id: int) -> Response:
        await kit.checked(request)
        book = recipes()
        back = f"/accounts/{account_id}/cookbook"
        if book is None or book.doc_id is None:
            return kit.redirect(back, "There's no cookbook yet.")
        result = await book.sync(force=True)
        if result is None:
            return kit.redirect(
                back, book.settings()["problem"] or "The cookbook couldn't be read."
            )
        said = book.summary(result)
        for other in book.books():  # F49h: the other docs too; RC8b: every book's
            if other.role == "main" or not other.doc_id:
                continue
            where = book.doc_name(other.key)
            read = await book.sync(force=True, which=other.key)
            said += " " + (
                book.summary(read, where) if read is not None
                else book.settings(other.key)["problem"] or f"{where} couldn't be read."
            )  # fmt: skip
        return kit.redirect(back, said)

    # ----- RC6: the Recipes page -----------------------------------------------------------

    def book() -> Recipes:
        found = recipes()
        assert found is not None
        return found

    @router.get("/recipes", response_class=HTMLResponse)
    def recipes_page(
        request: Request,
        q: str = Query(""),
        section: str = Query(""),
        shelf: str = Query("", alias="book"),
    ) -> HTMLResponse:
        session = kit.current(request)
        everything = book().all(include_charts=True)
        shelves = book().shelves()  # RC8b: each book of its own is a chip, listed apart
        chosen = next((b for b in shelves if b.key == shelf), None)
        if chosen is not None:
            everything = [r for r in everything if r.book == chosen.key]
            section = ""
        else:
            everything = [r for r in everything if not r.on_shelf]
        if q.strip():
            shown = [m.recipe for m in search(everything, q, section=section)]
        else:
            shown = [r for r in everything if not section or r.section == section]
        sections = list(dict.fromkeys(r.section for r in everything if r.section and not r.to_try))
        return kit.with_flash(
            request,
            "recipes.html",
            session,
            recipes=[r for r in shown if not r.to_try],
            to_try=[r for r in shown if r.to_try],  # F49h: under their own heading
            sections=[] if chosen else sections,
            section=section,
            shelves=shelves,
            shelf=chosen,
            q=q,
            looks=[r for r in everything if r.needs_look],
            diet=book().diet(),
            has_cookbook=book().doc_id is not None,
            link=book().link,
        )

    @router.post("/recipes/diet")
    async def set_diet(request: Request) -> Response:
        _, form = await kit.checked(request)
        diet = "vegan" if form.get("vegan") == "on" else ""
        book().set_diet(diet)
        return kit.redirect(
            "/recipes", "Web recipes: vegan first." if diet else "Web recipes: any diet."
        )

    def scaled(recipe: Recipe, said: str) -> tuple[float, str | None]:
        try:
            return scale_for(said, recipe.makes), None
        except NeedsYield:
            return 1.0, (
                f"{recipe.name} doesn't say how many it makes. Tell Themi in chat, or pick "
                "½, 2\u00d7 or 3\u00d7."
            )
        except ValueError:
            return 1.0, "That isn't an amount to scale by."

    # CK1: RC6's kitchen view is retired; the cook screen on /session took its place.
    @router.get("/recipes/kitchen")
    @router.get("/recipes/kitchen/state")
    def kitchen() -> Response:
        return kit.redirect("/session")

    @router.post("/recipes/kitchen/{session_id:int}/{action}")
    def kitchen_move(session_id: int, action: str) -> Response:
        return kit.redirect("/session")

    @router.get("/recipes/{recipe_id:int}/card.png")
    async def recipe_card_png(request: Request, recipe_id: int) -> Response:
        """DC10: the recipe as a picture, to keep or print."""
        session = kit.current(request)
        recipe = book().get(recipe_id)
        if recipe is None or recipe.removed or recipe.is_chart:
            return kit.redirect("/recipes", "That recipe isn't in the cookbook any more.")
        png = await card_png(app.services, session.member, recipe)
        if png is None:
            return kit.redirect(f"/recipes/{recipe_id}", "The picture couldn't be drawn.")
        return Response(png, media_type="image/png")

    @router.get("/recipes/{recipe_id:int}", response_class=HTMLResponse)
    def recipe_page(request: Request, recipe_id: int, scale: str = Query("")) -> Response:
        session = kit.current(request)
        recipe = book().get(recipe_id)
        if recipe is None or recipe.removed:
            return kit.redirect("/recipes", "That recipe isn't in the cookbook any more.")
        factor, problem = scaled(recipe, scale)
        show = viewer_lines(app.services, session.member.id)  # GW2: "With grams"
        lines = [show(scale_line(i.text, factor).line) for i in recipe.ingredients]
        groups = [i.group for i in recipe.ingredients]
        return kit.with_flash(
            request,
            "recipe.html",
            session,
            recipe=recipe,
            lines=list(zip(groups, lines, strict=True)),
            scale=scale if not problem else "",
            batch=describe(scale, factor) if factor != 1 else "",
            scales=SCALES,
            notes=[SCALED_TEXT] + ([BAKING_TEXT] if is_baking(recipe) else [])
            if factor != 1
            else [],
            problem=problem,
            link=book().link(recipe),
            chart=recipe.chart,
        )

    @router.post("/recipes/{recipe_id:int}/groceries")
    async def to_groceries(request: Request, recipe_id: int) -> Response:
        signed, form = await kit.checked(request)
        recipe = book().get(recipe_id)
        groceries = app.services.maybe(keys.recipe_groceries)
        if recipe is None or groceries is None:
            return kit.redirect("/recipes", "That recipe isn't in the cookbook any more.")
        said = str(form.get("scale", ""))
        factor, problem = scaled(recipe, said)
        if problem:
            return kit.redirect(f"/recipes/{recipe_id}", problem)
        member = app.store.get_member(signed.member.id)
        await groceries.send(member, await groceries.build(member, [recipe], factor, said))
        return kit.redirect(
            f"/recipes/{recipe_id}?scale={said}", "The grocery card is in your Telegram chat."
        )

    @router.post("/recipes/{recipe_id:int}/cook")
    async def cook(request: Request, recipe_id: int) -> Response:
        signed, form = await kit.checked(request)
        recipe = book().get(recipe_id)
        cooking = app.services.maybe(keys.cooking)
        if recipe is None or cooking is None or recipe.is_chart:
            return kit.redirect("/recipes", "That recipe can't be cooked step by step.")
        said = str(form.get("scale", ""))
        factor, problem = scaled(recipe, said)
        if problem:
            return kit.redirect(f"/recipes/{recipe_id}", problem)
        member = app.store.get_member(signed.member.id)
        # F41b (bug #198): started here, it stays on the screen; chat hears nothing of it
        await cooking.start(member, recipe, scale=factor, scale_said=said, from_page=True)
        return kit.redirect("/session", f"Cooking {recipe.name} on this screen.")

    return router
