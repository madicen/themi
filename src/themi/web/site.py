"""The management website: sign-in, the dashboard, and personal settings.

Server-rendered HTML with a little HTMX (vendored, no CDN). Every page works
without JavaScript; HTMX just swaps an approval card in place instead of
reloading the page.

Security:
- Sign-in by one-time link only (Google sign-in arrives in prompt 21).
- Sessions are server-side; the cookie is HttpOnly and SameSite=Lax, and
  Secure when the site is on HTTPS.
- Every POST needs the session's CSRF token (form field or X-CSRF-Token header).
- Pages only ever show or change the signed-in member's own settings: no
  page takes a member id, so there's nothing to tamper with.
- A strict Content-Security-Policy allows only same-origin scripts and styles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from themi.accounts import TRACKING_INPUTS, InvalidValue, Member
from themi.autonomy import Decision
from themi.localtime import to_local
from themi.web.auth import COOKIE_NAME, SESSION_TTL, Session, WebAuth

HERE = Path(__file__).parent
FLASH_COOKIE = "themi_flash"

TRACKING_LABELS = {
    "text_notes": 'Notes about how you\'re doing ("that call took a lot out of me")',
    "message_timing": "When you tend to reply, and how quickly",
    "device_activity": "Activity from household devices (laundry, feeders)",
}
EVENT_WORDS = {
    "staged": "Asked about",
    "auto_approved": "Handled automatically",
    "approved": "Approved",
    "executed": "Done",
    "execution_failed": "Didn't go through",
    "declined": "Left as is",
    "snoozed": "Put off",
    "resurfaced": "Asked again",
    "expired": "Lapsed",
}
STRENGTH_LABELS = {
    0: "Light: only soften outright demands",
    1: "Gentle: also soften reminders and pressure",
    2: "Standard: also soften instructions",
    3: "Strict: soften anything that sounds like a must",
}


class NotSignedIn(Exception):
    pass


@dataclass
class SiteContext:
    app: Any  # themi.app.App (typed loosely to keep this module import-light)
    base_url: str
    secure_cookies: bool


def security_headers(response: Response) -> None:
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # Login links carry their token in the URL; never leak it in a Referer.
    response.headers["Referrer-Policy"] = "no-referrer"


def install_site(web: FastAPI, ctx: SiteContext) -> None:
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    auth = WebAuth(ctx.app.store)
    router = APIRouter()
    web.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def tz() -> str:
        family = ctx.app.store.get_family()
        return family.timezone if family else "UTC"

    def local_time(moment: str | datetime) -> str:
        value = datetime.fromisoformat(moment) if isinstance(moment, str) else moment
        return to_local(value, tz()).strftime("%a %d %b, %I:%M %p").replace(" 0", " ")

    templates.env.filters["local_time"] = local_time

    def page(request: Request, name: str, status: int = 200, **values: Any) -> HTMLResponse:
        response = templates.TemplateResponse(request, name, values, status_code=status)
        response.headers["Cache-Control"] = "no-store"
        return response

    def current(request: Request) -> Session:
        session = auth.session(request.cookies.get(COOKIE_NAME))
        if session is None:
            raise NotSignedIn
        return session

    async def checked(request: Request) -> tuple[Session, dict[str, Any]]:
        """The session and form for a POST, after checking its CSRF token."""
        session = current(request)
        form = dict(await request.form())
        submitted = form.get("csrf") or request.headers.get("X-CSRF-Token")
        if not WebAuth.csrf_ok(session, str(submitted) if submitted else None):
            raise PermissionError("missing or wrong CSRF token")
        return session, form

    def flash_and_redirect(url: str, message: str | None = None) -> RedirectResponse:
        response = RedirectResponse(url, status_code=303)
        if message:
            response.set_cookie(
                FLASH_COOKIE,
                message,
                max_age=60,
                httponly=True,
                samesite="lax",
                secure=ctx.secure_cookies,
            )
        return response

    def with_flash(request: Request, name: str, **values: Any) -> HTMLResponse:
        """Render a page with any one-off message from the previous POST, then forget it."""
        flash = request.cookies.get(FLASH_COOKIE)
        response = page(request, name, flash=flash, **values)
        if flash:
            response.delete_cookie(FLASH_COOKIE)
        return response

    @web.middleware("http")
    async def headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        security_headers(response)
        return response

    @web.exception_handler(NotSignedIn)
    async def not_signed_in(request: Request, exc: NotSignedIn) -> Response:
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/signed-out"})
        return RedirectResponse("/signed-out", status_code=303)

    @web.exception_handler(PermissionError)
    async def forbidden(request: Request, exc: PermissionError) -> Response:
        return page(
            request,
            "message.html",
            403,
            title="That didn't go through",
            body="The page was out of date. Going back and trying again usually helps.",
        )

    # ----- signing in and out -------------------------------------------------

    @router.get("/login/{token}", response_class=HTMLResponse)
    def login_page(request: Request, token: str) -> HTMLResponse:
        if not auth.link_is_valid(token):
            return page(
                request,
                "message.html",
                410,
                title="That link has expired",
                body="Sign-in links work once, for 10 minutes. Sending /site to Themi "
                "gets a fresh one.",
            )
        return page(request, "login.html", token=token)

    @router.post("/login/{token}")
    def login(request: Request, token: str) -> Response:
        member = auth.consume_link(token)
        if member is None:
            return page(
                request,
                "message.html",
                410,
                title="That link has expired",
                body="Sign-in links work once, for 10 minutes. Sending /site to Themi "
                "gets a fresh one.",
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            auth.start_session(member),
            max_age=int(SESSION_TTL.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=ctx.secure_cookies,
        )
        return response

    @router.get("/signed-out", response_class=HTMLResponse)
    def signed_out(request: Request) -> HTMLResponse:
        return page(
            request,
            "message.html",
            title="You're signed out",
            body="Sending /site to Themi in Telegram gets you a sign-in link.",
        )

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        await checked(request)
        auth.end_session(request.cookies.get(COOKIE_NAME))
        response = RedirectResponse("/signed-out", status_code=303)
        response.delete_cookie(COOKIE_NAME)
        return response

    # ----- dashboard ------------------------------------------------------------

    def dashboard_values(member: Member) -> dict[str, Any]:
        autonomy = ctx.app.services.autonomy
        actions = autonomy.open_for(member)
        activity = ctx.app.db.query(
            "SELECT a.event, a.created_at, p.summary FROM action_audit a "
            "JOIN pending_actions p ON p.id = a.action_id "
            "WHERE p.member_id = ? AND a.event IN "
            "('auto_approved', 'executed', 'execution_failed', 'declined', 'snoozed', 'expired') "
            "ORDER BY a.id DESC LIMIT 12",
            (member.id,),
        )
        alerts = []
        if member.is_admin:
            for category in autonomy.categories():
                if category.escalated:
                    alerts.append(
                        f"{category.label} is asking again because: {category.escalation_reason}"
                    )
        failed = [a for a in actions if a.status == "failed"]
        if failed:
            alerts.append(f"{len(failed)} action(s) didn't go through and can be tried again.")
        return {
            "member": member,
            "actions": actions,
            "activity": [
                {**row, "words": EVENT_WORDS.get(row["event"], row["event"])} for row in activity
            ],
            "alerts": alerts,
        }

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        session = current(request)
        return with_flash(
            request, "dashboard.html", csrf=session.csrf_token, **dashboard_values(session.member)
        )

    @router.post("/actions/{action_id}/{decision}")
    async def decide(request: Request, action_id: int, decision: str) -> Response:
        session, _ = await checked(request)
        try:
            choice = Decision(decision)
        except ValueError:
            return page(request, "message.html", 404, title="Not found", body="")
        message = await ctx.app.approvals.resolve(action_id, choice, session.member)
        if request.headers.get("HX-Request"):
            action = ctx.app.services.autonomy.action(action_id)
            return page(
                request, "_action_card.html", action=action, result=message, csrf=session.csrf_token
            )
        return flash_and_redirect("/", message)

    # ----- settings ---------------------------------------------------------------

    def settings_values(member: Member, **extra: Any) -> dict[str, Any]:
        return {
            "member": member,
            "tracking": [
                (name, TRACKING_LABELS[name], member.tracks(name)) for name in TRACKING_INPUTS
            ],
            "strengths": STRENGTH_LABELS,
            **extra,
        }

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        session = current(request)
        return with_flash(
            request, "settings.html", csrf=session.csrf_token, **settings_values(session.member)
        )

    @router.post("/settings")
    async def save_settings(request: Request) -> Response:
        session, form = await checked(request)
        member = session.member  # always the signed-in member; any member_id field is ignored
        try:
            ctx.app.store.update_settings(
                member,
                member.id,
                quiet_start=str(form.get("quiet_start", "")) or None,
                quiet_end=str(form.get("quiet_end", "")) or None,
                daily_limit=_int(form.get("daily_limit")),
                pda_enabled=form.get("pda_enabled") == "on",
                pda_strength=_int(form.get("pda_strength")),
                tracking={name: form.get(f"track_{name}") == "on" for name in TRACKING_INPUTS},
            )
        except InvalidValue as exc:
            return page(
                request,
                "settings.html",
                400,
                csrf=session.csrf_token,
                **settings_values(member, error=str(exc)),
            )
        return flash_and_redirect("/settings", "Saved.")

    web.include_router(router)


def _int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value))
    except ValueError as exc:
        raise InvalidValue(f"{value!r} isn't a whole number") from exc
