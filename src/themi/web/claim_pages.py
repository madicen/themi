"""SP7a: the first visit. A Themi nobody has claimed asks for its claim code, the
household's name and timezone, and the claimant's name, and makes them its first admin.
When Themi made its own secret key, the next page shows it once, to be saved.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import available_timezones

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from themi.accounts.claim import Claim, ClaimError
from themi.settings import key_beside_database
from themi.web.kit import Kit

DEFAULT_TIMEZONE = "America/Los_Angeles"


def data_folder(kit: Kit) -> Path | None:
    settings = kit.app.services.settings
    return Path(settings.db_path).parent if settings is not None else None


def made_key(kit: Kit) -> str | None:
    """The secret key, when Themi made it itself (SP2), else None."""
    services = kit.app.services
    env, settings = services.environment, services.settings
    if settings is None or env.get("THEMI_SECRET_KEY") or env.get("THEMI_SECRET_KEY_FILE"):
        return None
    if not key_beside_database({"THEMI_DB_PATH": str(settings.db_path)}).exists():
        return None
    return settings.secret_key.reveal()


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    claim = Claim(app.store)
    zones = sorted(z for z in available_timezones() if "/" in z and not z.startswith("Etc/"))

    def form(request: Request, status: int = 200, problem: str = "", **values: str) -> Response:
        response = kit.page(
            request,
            "claim.html",
            status,
            problem=problem,
            zones=zones,
            values={"timezone": DEFAULT_TIMEZONE, **values},
        )
        return response

    @router.get("/claim", response_class=HTMLResponse)
    def claim_page(request: Request) -> Response:
        if not claim.needed():
            return RedirectResponse("/", status_code=303)
        return form(request)

    @router.post("/claim", response_class=HTMLResponse)
    async def claim_it(request: Request) -> Response:
        if not claim.needed():
            return RedirectResponse("/", status_code=303)
        data = {k: str(v) for k, v in (await request.form()).items()}
        report = app.services.start_report
        try:
            admin = claim.claim(
                data.get("code", ""),
                data.get("household", ""),
                data.get("timezone", ""),
                data.get("name", ""),
                data_folder(kit),
                report.template,
            )
        except ClaimError as exc:
            keep = {k: data.get(k, "") for k in ("household", "timezone", "name")}
            return form(request, 400, str(exc), **keep)
        return kit.signed_in(admin, "/claim/key" if made_key(kit) else "/")

    @router.get("/claim/key", response_class=HTMLResponse)
    def key_page(request: Request) -> Response:
        session = kit.admin(request)
        key = made_key(kit)
        if key is None or claim.key_saved() or claim.claimant() != session.member.id:
            return RedirectResponse("/", status_code=303)
        return kit.with_flash(request, "claim_key.html", session, key=key)

    @router.post("/claim/key")
    async def key_saved(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        if claim.claimant() == session.member.id:
            claim.note_key_saved()
        return kit.redirect("/", "Welcome to Themi. Start on the Modules page.")

    return router
