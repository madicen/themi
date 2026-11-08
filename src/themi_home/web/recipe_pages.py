"""Recipes on the website (RC1a, RC6).

RC1a: the cookbook page under Accounts. A person picks the family's recipe doc in Google's
file picker (scope `drive.file`, so Themi can open that file and nothing else of theirs);
pasting the doc's link also works where Google already lets Themi open it (a doc picked
before, or `make dev`'s fake). The picker page is the one page that loads Google's own
scripts, so it gets its own, wider Content-Security-Policy.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import LinkedAccount, Member
from themi.core import keys
from themi.web.kit import Kit
from themi_google.connectors.gdocs import DocsError, doc_id_from
from themi_google.connectors.google import DRIVE_FILE_SCOPE
from themi_home.cooking import Session, step_parts
from themi_home.quantities import NeedsYield, describe, scale_for, scale_line
from themi_home.recipe_groceries import BAKING_TEXT, SCALED_TEXT, is_baking
from themi_home.recipes import Recipe, Recipes, search

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

    @router.get("/accounts/{account_id}/cookbook", response_class=HTMLResponse)
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

    @router.post("/accounts/{account_id}/cookbook")
    async def choose_cookbook(request: Request, account_id: int) -> Response:
        session, form = await kit.checked(request)
        book = recipes()
        back = f"/accounts/{account_id}/cookbook"
        if book is None:
            return kit.redirect("/accounts", "Recipes aren't set up on this server.")
        doc_id = doc_id_from(str(form.get("doc", "")))
        if doc_id is None:
            return kit.redirect(back, "That doesn't look like a Google Doc's link.")
        try:
            said = await book.choose(session.member, account_id, doc_id)
        except DocsError as exc:
            return kit.redirect(back, str(exc))
        return kit.redirect(back, said)

    @router.post("/accounts/{account_id}/cookbook/read")
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
        return kit.redirect(back, book.summary(result))

    # ----- RC6: the Recipes page -----------------------------------------------------------

    def book() -> Recipes:
        found = recipes()
        assert found is not None
        return found

    @router.get("/recipes", response_class=HTMLResponse)
    def recipes_page(
        request: Request, q: str = Query(""), section: str = Query("")
    ) -> HTMLResponse:
        session = kit.current(request)
        everything = book().all(include_charts=True)
        if q.strip():
            shown = [m.recipe for m in search(everything, q, section=section)]
        else:
            shown = [r for r in everything if not section or r.section == section]
        sections = list(dict.fromkeys(r.section for r in everything if r.section))
        return kit.with_flash(
            request,
            "recipes.html",
            session,
            recipes=shown,
            sections=sections,
            section=section,
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

    @router.get("/recipes/kitchen", response_class=HTMLResponse)
    def kitchen(request: Request) -> Response:
        session = kit.current(request)
        return kit.with_flash(request, "kitchen.html", session, **kitchen_values(session.member))

    @router.get("/recipes/kitchen/state", response_class=HTMLResponse)
    def kitchen_state(request: Request) -> Response:
        session = kit.current(request)
        return kit.page(request, "_kitchen.html", csrf=session.csrf_token,
                        **kitchen_values(session.member))  # fmt: skip

    def kitchen_values(member: Member) -> dict[str, Any]:
        cooking = app.services.maybe(keys.cooking)
        current: Session | None = cooking.current(member) if cooking else None
        if cooking is None or current is None:
            return {"cooking": None}
        recipe = book().get(current.recipe_id)
        assert recipe is not None
        parts = step_parts(recipe)
        step = parts[min(current.step, len(parts) - 1)] if parts else None
        return {
            "cooking": current,
            "recipe": recipe,
            "heading": cooking.heading(current, recipe),
            "lines": cooking.lines(current, recipe),
            "step": step,
            "steps": len(recipe.steps),
            "first": current.step == 0,
            "last": current.step >= len(parts) - 1,
            "prep": current.prep,
            "ahead": current.ahead,
        }

    @router.post("/recipes/kitchen/{session_id}/{action}")
    async def kitchen_move(request: Request, session_id: int, action: str) -> Response:
        signed, _ = await kit.checked(request)
        cooking = app.services.maybe(keys.cooking)
        current = cooking.get(session_id) if cooking else None
        if (
            cooking is None
            or current is None
            or action not in ("next", "back", "stop", "skip")
            or (current.member_id != signed.member.id and not current.in_group)
            or app.db.scalar("SELECT ended_at FROM cooking_sessions WHERE id = ?", (session_id,))
        ):
            return kit.redirect("/recipes/kitchen", "That cooking session has ended.")
        if action == "skip" and current.phase == "prep":
            await cooking.after_prep(current)
            await cooking.show(current)
        else:
            await cooking.advance(current, action)  # the chat's card moves too
        if request.headers.get("HX-Request"):
            return kitchen_state(request)
        return kit.redirect("/recipes/kitchen")

    @router.get("/recipes/{recipe_id}", response_class=HTMLResponse)
    def recipe_page(request: Request, recipe_id: int, scale: str = Query("")) -> Response:
        session = kit.current(request)
        recipe = book().get(recipe_id)
        if recipe is None or recipe.removed:
            return kit.redirect("/recipes", "That recipe isn't in the cookbook any more.")
        factor, problem = scaled(recipe, scale)
        lines = [scale_line(i.text, factor).line for i in recipe.ingredients]
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

    @router.post("/recipes/{recipe_id}/groceries")
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

    @router.post("/recipes/{recipe_id}/cook")
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
        await cooking.start(member, recipe, scale=factor, scale_said=said)
        return kit.redirect("/recipes/kitchen", "Cooking: the same card is in your chat.")

    return router
