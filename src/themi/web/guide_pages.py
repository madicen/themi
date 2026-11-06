"""Guides (F29ha): the family's own guides, to add, read and delete. Each person sees the
household's and their own."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.core.guides import Guides
from themi.core.tools import ToolFailed
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def guides() -> Guides:
        assert app.services.guides is not None
        return app.services.guides

    @router.get("/guides", response_class=HTMLResponse)
    def guides_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(
            request, "guides.html", session, guides=guides().visible(session.member)
        )

    @router.post("/guides")
    async def add_guide(request: Request) -> Response:
        session, form = await kit.checked(request)
        try:
            guide = guides().save(
                session.member,
                str(form.get("name", "")),
                str(form.get("text", "")),
                personal=form.get("personal") == "on",
            )
        except ToolFailed as exc:
            return kit.redirect("/guides", str(exc))
        return kit.redirect("/guides", f'Saved "{guide.name}".')

    @router.post("/guides/{guide_id}/delete")
    async def delete_guide(request: Request, guide_id: int) -> Response:
        session, _ = await kit.checked(request)
        if not guides().delete(session.member, guide_id):
            return kit.redirect("/guides", "That guide isn't one you can delete.")
        return kit.redirect("/guides", "Deleted.")

    return router
