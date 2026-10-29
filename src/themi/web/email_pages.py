"""Emails to archive (F16b): each person's own offers to archive noise, to archive all,
archive the ticked ones or keep the ticked ones. No route takes a member id."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.core.noise_digest import NoiseDigest
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def noise() -> NoiseDigest | None:
        return app.services.noise

    @router.get("/email/noise", response_class=HTMLResponse)
    def noise_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        digest = noise()
        actions = digest.waiting(session.member) if digest else []
        rows = [{"id": a.id, "line": digest.line(a)} for a in actions] if digest else []
        return kit.with_flash(request, "email_noise.html", session, rows=rows)

    @router.post("/email/noise")
    async def answer_noise(request: Request) -> Response:
        session, form = await kit.checked(request)
        digest = noise()
        if digest is None:
            return kit.redirect("/email/noise", "Email isn't set up.")
        member = session.member
        if form.get("do") == "all":
            ids = [a.id for a in digest.waiting(member)]
        else:
            ticked = [str(i) for i in (await request.form()).getlist("action")]
            ids = [int(i) for i in ticked if i.isdigit()]
        if not ids:
            return kit.redirect("/email/noise", "Tick the ones you mean first.")
        if form.get("do") == "keep":
            kept = await digest.keep(member, ids)
            return kit.redirect("/email/noise", f"Kept {kept} in the inbox.")
        done, failed = await digest.archive(member, ids)
        message = f"Archived {done}." + (
            f" {failed} didn't go through; they're on the dashboard to try again." if failed else ""
        )
        return kit.redirect("/email/noise", message)

    return router
