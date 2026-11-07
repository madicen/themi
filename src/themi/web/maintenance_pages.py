"""Maintenance (33): the household's seasonal and long-term upkeep, each with its interval,
active months, step-by-step guide and the notes from past runs.

Anyone in the household can add, change, mark done or remove an item, as in chat. Only
putting due dates on the family calendar asks first (its card comes in Telegram).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import Member
from themi.core import keys
from themi.core.maintenance import MONTHS, Maintenance, every_words, months_words
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def maintenance() -> Maintenance:
        assert app.services.maybe(keys.maintenance) is not None
        return app.services.maybe(keys.maintenance)

    def back(item_id: int | None = None, message: str | None = None) -> Response:
        to = f"/maintenance?open={item_id}#item-{item_id}" if item_id else "/maintenance"
        return kit.redirect(to, message)

    def months_of(form: dict[str, Any]) -> tuple[int, ...]:
        chosen = tuple(m for m in range(1, 13) if form.get(f"m{m}") == "on")
        return chosen if len(chosen) < 12 else ()

    def owner_of(form: dict[str, Any]) -> Member | None:
        said = str(form.get("owner", "")).strip()
        members = {str(m.id): m for m in app.store.list_members()}
        return members.get(said)

    def steps_of(form: dict[str, Any]) -> list[str]:
        return str(form.get("steps", "")).splitlines()

    def interval_of(form: dict[str, Any]) -> int:
        try:
            return int(str(form.get("interval_days", "")).strip())
        except ValueError as exc:
            raise ValueError("the interval is a number of days") from exc

    @router.get("/maintenance", response_class=HTMLResponse)
    def maintenance_page(request: Request, opened: str = Query("", alias="open")) -> HTMLResponse:
        session = kit.current(request)
        m = maintenance()
        today = m.today()
        rows = []
        for item in sorted(m.items(), key=lambda i: (m.next_due(i, today), i.id)):
            due = m.next_due(item, today)
            last = m.last_done(item)
            rows.append(
                {
                    "item": item,
                    "due": due,
                    "overdue": due <= today,
                    "last": last,
                    "every": every_words(item.interval_days),
                    "months": months_words(item.active_months),
                    "owner": app.store.get_member(item.owner).name if item.owner else "",
                    "runs": m.runs(item, 10),
                    "offered": m.open_task(item) is not None,
                }
            )
        return kit.with_flash(
            request,
            "maintenance.html",
            session,
            rows=rows,
            months=MONTHS,
            members=app.store.list_members(),
            names={m.id: m.name for m in app.store.list_members()},
            today=today,
            opened=opened,
        )

    @router.post("/maintenance")
    async def add_item(request: Request) -> Response:
        session, form = await kit.checked(request)
        last = str(form.get("last_done", "")).strip()
        try:
            last_done = date.fromisoformat(last) if last else None
            if last_done is not None and last_done > maintenance().today():
                raise ValueError("the last time it was done can't be in the future")
            if maintenance().find(str(form.get("name", ""))) is not None:
                raise ValueError("there's an item with that name already")
            item, _ = await maintenance().set(
                session.member,
                str(form.get("name", "")),
                interval_days=interval_of(form),
                months=months_of(form),
                guide=steps_of(form),
                owner=owner_of(form),
                last_done=last_done,
            )
        except ValueError as exc:
            return back(None, f"{str(exc).capitalize()}.")
        return back(item.id, f"Added {item.name}.")

    @router.post("/maintenance/{item_id}")
    async def edit_item(request: Request, item_id: int) -> Response:
        session, form = await kit.checked(request)
        item = maintenance().get(item_id)
        if item is None:
            return back(None, "That item has been removed.")
        name = " ".join(str(form.get("name", "")).split())
        try:
            item, _ = await maintenance().set(
                session.member,
                item.name,
                interval_days=interval_of(form),
                months=months_of(form),
                guide=steps_of(form),
                owner=owner_of(form),
                new_name=name if name != item.name else "",
            )
        except ValueError as exc:
            return back(item.id, f"{str(exc).capitalize()}.")
        return back(item.id, f"Saved {item.name}.")

    @router.post("/maintenance/{item_id}/done")
    async def mark_done(request: Request, item_id: int) -> Response:
        session, form = await kit.checked(request)
        item = maintenance().get(item_id)
        if item is None:
            return back(None, "That item has been removed.")
        said = await maintenance().log(
            item, session.member, maintenance().today(), str(form.get("notes", ""))
        )
        return back(item.id, said)

    @router.post("/maintenance/{item_id}/delete")
    async def delete_item(request: Request, item_id: int) -> Response:
        session, _ = await kit.checked(request)
        item = maintenance().get(item_id)
        if item is None:
            return back(None, "That item has been removed.")
        await maintenance().remove(item, session.member)
        return back(None, f"Removed {item.name}.")

    return router
