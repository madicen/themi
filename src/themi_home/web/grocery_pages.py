"""CR10a: adding to the grocery list from the Lists page. The groceries module's page:
the Lists page is the lists module's, and works without the grocery list."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from themi.accounts import InvalidValue
from themi.core import keys
from themi.core.wording import item_name
from themi.web.kit import Kit
from themi_home.groceries import CATEGORY, EXECUTOR, list_summary

GROCERIES_ON_LISTS = "/lists?open=groceries#groceries"


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    @router.post("/groceries/add")
    async def add_grocery(request: Request) -> Response:
        """The grocery list (OurGroceries' too), from the Lists page. Typed in here, it's
        asked for in their own words, as in chat: that's their yes, unless the category
        always asks or is paused (then it waits on a yes like any other)."""
        session, form = await kit.checked(request)
        groceries = app.services.maybe(keys.groceries)
        to = "/lists?open=groceries#groceries"
        if groceries is None:
            return kit.redirect(to, "The grocery list isn't set up on this server.")
        try:
            name = item_name(str(form.get("item", "")))
        except InvalidValue:
            return kit.redirect(to, "That doesn't look like an item.")
        if groceries.is_needed(name) or name in groceries.awaiting_approval():
            return kit.redirect(to, "That's on it already.")
        outcome = await app.services.autonomy.stage(
            CATEGORY, session.member, list_summary([name]), {"items": [name]}, EXECUTOR,
            requested=True,
        )  # fmt: skip
        return kit.redirect(to, outcome.message)

    @router.post("/groceries/{item_id}/bought")  # CR17a: from the dashboard and Lists
    async def grocery_bought(request: Request, item_id: int) -> Response:
        _, form = await kit.checked(request)
        back = GROCERIES_ON_LISTS if form.get("back") == "lists" else "/"
        groceries, pantry = app.services.maybe(keys.groceries), app.services.maybe(keys.pantry)
        item = groceries.get(item_id) if groceries else None
        if item is None or item.status != "needed" or groceries is None:
            return kit.redirect(back, "That one is already off the list.")
        if pantry is not None:
            pantry.set_status(item.name, "plenty", source="list")  # takes it off the list too
        else:
            groceries.finish(item.name)
        return kit.redirect(back, f"Took {item.name} off the list.")

    return router
