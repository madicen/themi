"""Lists (L1a): Themi's named lists, the household's and your own.

You see the household's lists and your personal ones, never someone else's personal list,
whatever a form says. Changes here are the person's own, so nothing waits for a yes.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import InvalidValue, Member
from themi.core.lists import ListItem, Lists, NamedList
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def lists() -> Lists:
        assert app.services.lists is not None
        return app.services.lists

    def mine(member: Member, list_id: int) -> NamedList | None:
        return lists().get(list_id, member)

    def item_of(nl: NamedList, item_id: int) -> ListItem | None:
        return next((i for i in nl.items if i.id == item_id), None)

    @router.get("/lists", response_class=HTMLResponse)
    def lists_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        found = lists().visible(session.member)
        return kit.with_flash(
            request,
            "lists.html",
            session,
            lists=found,
            stores={nl.id: lists().stores(nl) for nl in found if nl.purpose},
        )

    @router.post("/lists")
    async def create_list(request: Request) -> Response:
        session, form = await kit.checked(request)
        personal = form.get("personal") == "on"
        try:
            nl = lists().create(session.member, str(form.get("name", "")), personal=personal)
        except InvalidValue as exc:
            return kit.redirect("/lists", f"{str(exc).capitalize()}.")
        return kit.redirect("/lists", f"Made the list {nl.name}.")

    @router.post("/lists/{list_id}/add")
    async def add_item(request: Request, list_id: int) -> Response:
        session, form = await kit.checked(request)
        nl = mine(session.member, list_id)
        if nl is None:
            return kit.redirect("/lists", "That list isn't one you can see.")
        try:
            added = lists().add(nl, [str(form.get("item", ""))], session.member)
        except InvalidValue as exc:
            return kit.redirect("/lists", f"{str(exc).capitalize()}.")
        return kit.redirect("/lists", f"Added to {nl.name}." if added else "That's on it already.")

    @router.post("/lists/{list_id}/items/{item_id}/tick")
    async def tick_item(request: Request, list_id: int, item_id: int) -> Response:
        session, form = await kit.checked(request)
        nl = mine(session.member, list_id)
        item = item_of(nl, item_id) if nl else None
        if item is None:
            return kit.redirect("/lists", "That item isn't on a list you can see.")
        lists().tick(item, form.get("done") == "1", session.member)
        return kit.redirect("/lists")

    @router.post("/lists/{list_id}/items/{item_id}/remove")
    async def remove_item(request: Request, list_id: int, item_id: int) -> Response:
        session, _ = await kit.checked(request)
        nl = mine(session.member, list_id)
        item = item_of(nl, item_id) if nl else None
        if item is None:
            return kit.redirect("/lists", "That item isn't on a list you can see.")
        lists().remove(item)
        return kit.redirect("/lists", f"Took {item.name} off.")

    @router.post("/lists/{list_id}/items/{item_id}/store")
    async def set_store(request: Request, list_id: int, item_id: int) -> Response:
        """Where a thing to buy usually comes from (L2a)."""
        session, form = await kit.checked(request)
        nl = mine(session.member, list_id)
        item = item_of(nl, item_id) if nl else None
        buying = app.services.buying
        if item is None or buying is None:
            return kit.redirect("/lists", "That item isn't on a list you can see.")
        store = " ".join(str(form.get("store", "")).split())[:40]
        if store:
            buying.remember(item.name, store=store)
            return kit.redirect("/lists", f"{item.name}: usually from {store}.")
        buying.forget_store(item.name)
        return kit.redirect("/lists", f"Forgot where {item.name} comes from.")

    @router.post("/lists/{list_id}/clear")
    async def clear_ticked(request: Request, list_id: int) -> Response:
        session, _ = await kit.checked(request)
        nl = mine(session.member, list_id)
        if nl is None:
            return kit.redirect("/lists", "That list isn't one you can see.")
        cleared = lists().clear_ticked(nl)
        return kit.redirect("/lists", f"Cleared {cleared} ticked from {nl.name}.")

    @router.post("/lists/{list_id}/delete")
    async def delete_list(request: Request, list_id: int) -> Response:
        session, _ = await kit.checked(request)
        nl = mine(session.member, list_id)
        if nl is None:
            return kit.redirect("/lists", "That list isn't one you can see.")
        lists().delete(nl)
        return kit.redirect("/lists", f"Deleted the list {nl.name}.")

    return router
