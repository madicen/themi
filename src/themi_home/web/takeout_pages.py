"""Takeout (35a): the household's saved takeout favourites, which the takeout rescue picks
from, and (for admins) the dinner window and the most one order may cost.

Anyone in the household can add, change or remove a favourite.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import InvalidValue
from themi.accounts.setup import parse_money_to_cents
from themi.core import keys
from themi.web.kit import Kit
from themi_home.spending import money
from themi_home.takeout import Takeout, TakeoutSettings


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def takeout() -> Takeout:
        found = app.services.maybe(keys.takeout)
        assert found is not None
        return found

    def fields(form: dict[str, Any]) -> tuple[str, str, list[str], int]:
        return (
            str(form.get("name", "")),
            str(form.get("store_url", "")),
            str(form.get("items", "")).splitlines(),
            parse_money_to_cents(str(form.get("amount", ""))),
        )

    @router.get("/takeout", response_class=HTMLResponse)
    def takeout_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        settings = takeout().settings()
        left = takeout().budget_left(takeout().today())
        return kit.with_flash(
            request,
            "takeout.html",
            session,
            favourites=[
                {"f": f, "amount": f"{f.cents / 100:.2f}", "money": money(f.cents)}
                for f in takeout().favourites()
            ],
            settings=settings,
            cap=f"{settings.order_cap_cents / 100:.2f}",
            left=None if left is None else money(max(left, 0)),
        )

    @router.post("/takeout")
    async def add_favourite(request: Request) -> Response:
        session, form = await kit.checked(request)
        try:
            saved = takeout().save_favourite(session.member, *fields(form))
        except InvalidValue as exc:
            return kit.redirect("/takeout", f"Not saved: {exc}.")
        return kit.redirect("/takeout", f"Saved {saved.name}.")

    @router.post("/takeout/settings")
    async def save_settings(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        try:
            app.store.save_household(
                session.member,
                TakeoutSettings,
                dinner_from=str(form.get("dinner_from", "")),
                dinner_until=str(form.get("dinner_until", "")),
                order_cap_cents=parse_money_to_cents(str(form.get("cap", ""))),
            )
        except InvalidValue as exc:
            return kit.redirect("/takeout", f"Not saved: {exc}.")
        return kit.redirect("/takeout", "Saved.")

    @router.post("/takeout/{favourite_id}")
    async def edit_favourite(request: Request, favourite_id: int) -> Response:
        session, form = await kit.checked(request)
        if takeout().favourite(favourite_id) is None:
            return kit.redirect("/takeout", "That favourite has been removed.")
        try:
            saved = takeout().save_favourite(session.member, *fields(form), favourite_id)
        except InvalidValue as exc:
            return kit.redirect("/takeout", f"Not saved: {exc}.")
        return kit.redirect("/takeout", f"Saved {saved.name}.")

    @router.post("/takeout/{favourite_id}/remove")
    async def remove_favourite(request: Request, favourite_id: int) -> Response:
        await kit.checked(request)
        favourite = takeout().favourite(favourite_id)
        takeout().remove_favourite(favourite_id)
        name = favourite.name if favourite else "it"
        return kit.redirect("/takeout", f"Removed {name}.")

    return router
