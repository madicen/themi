"""Guides (F29ha): the family's own guides, to add, read and delete. Each person sees the
household's and their own."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.core import keys
from themi.core.tools import ToolFailed
from themi.standard.guides import Guides
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def guides() -> Guides:
        assert app.services.maybe(keys.guides) is not None
        return app.services.maybe(keys.guides)

    @router.get("/guides", response_class=HTMLResponse)
    def guides_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        shown = guides().visible(session.member)
        notes = {g.id: guides().notes(g) for g in shown}  # GW1: sources of gram weights
        originals = {g.id: guides().originals(g.id) for g in shown}  # F29hb
        return kit.with_flash(
            request, "guides.html", session, guides=shown, notes=notes, originals=originals
        )

    @router.get("/guides/{guide_id:int}/original/{n:int}")
    def guide_original(request: Request, guide_id: int, n: int) -> Response:
        """F29hb: the photo or PDF a guide was read from, decrypted only for this answer."""
        session = kit.current(request)
        found = guides().original(session.member, guide_id, n)
        if found is None:
            return Response(status_code=404)
        mime_type, data = found
        return Response(
            data,
            media_type=mime_type,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
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

    @router.post("/guides/{guide_id:int}/delete")
    async def delete_guide(request: Request, guide_id: int) -> Response:
        session, _ = await kit.checked(request)
        if not guides().delete(session.member, guide_id):
            return kit.redirect("/guides", "That guide isn't one you can delete.")
        return kit.redirect("/guides", "Deleted.")

    return router
