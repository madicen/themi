"""The management website: sign-in, the dashboard and personal settings.

The admin, trust-tier, rules-and-memory and AI pages live in sibling modules
and are installed from `install_site`.

Server-rendered HTML with a little HTMX (vendored, no CDN). Every page works
without JavaScript; HTMX just swaps a card in place instead of reloading.

Security:
- Sign-in by one-time link from the bot, or with Google for members' addresses
  (google_pages).
- Sessions are server-side; the cookie is HttpOnly and SameSite=Lax, and
  Secure when the site is on HTTPS.
- Every POST needs the session's CSRF token (form field or X-CSRF-Token header).
- Pages only ever show or change the signed-in member's own personal
  settings: no such page takes a member id.
- A strict Content-Security-Policy allows only same-origin scripts and styles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from themi.accounts import TRACKING_INPUTS, BusyTime, InvalidValue, Member
from themi.accounts.models import DAY_NAMES
from themi.autonomy import Decision
from themi.web.auth import COOKIE_NAME
from themi.web.kit import HERE, AdminsOnly, Kit, NotSignedIn, SiteContext

__all__ = ["SiteContext", "install_site"]

TRACKING_LABELS = {
    "text_notes": 'Notes about how you\'re doing ("that call took a lot out of me")',
    "message_timing": "When you tend to reply, and how quickly",
    "device_activity": "Activity from household devices (laundry, feeders, the wall's routines)",
    "calendar": "When your Google calendar says you're busy (never what the events are)",
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
EXPIRED_LINK = "Sign-in links work once, for 10 minutes. Sending /site to Themi gets a fresh one."


def security_headers(response: Response, form_targets: str = "") -> None:
    """`form_targets`: extra origins a form may lead to (Google's sign-in page, via redirect)."""
    form_action = f"'self' {form_targets}".strip()
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        f"frame-ancestors 'none'; form-action {form_action}; base-uri 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # Login links carry their token in the URL; never leak it in a Referer.
    response.headers["Referrer-Policy"] = "no-referrer"


def install_site(web: FastAPI, ctx: SiteContext) -> None:
    from themi.web import (
        admin_pages,
        ai_pages,
        google_pages,
        knowledge_pages,
        task_pages,
        week_pages,
    )

    kit = Kit(ctx)
    google = ctx.app.services.google
    # Linking POSTs to Themi, which redirects to Google; browsers check that redirect too.
    form_targets = _origin(google.oauth.config.auth_url) if google is not None else ""
    web.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @web.middleware("http")
    async def headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        security_headers(response, form_targets)
        return response

    @web.exception_handler(NotSignedIn)
    async def not_signed_in(request: Request, exc: NotSignedIn) -> Response:
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/signed-out"})
        return RedirectResponse("/signed-out", status_code=303)

    @web.exception_handler(AdminsOnly)
    async def admins_only(request: Request, exc: AdminsOnly) -> Response:
        return kit.page(
            request,
            "message.html",
            403,
            title="Admins only",
            body="This page changes things for the whole household, so it's for admins.",
        )

    @web.exception_handler(PermissionError)
    async def forbidden(request: Request, exc: PermissionError) -> Response:
        return kit.page(
            request,
            "message.html",
            403,
            title="That didn't go through",
            body="The page was out of date. Going back and trying again usually helps.",
        )

    web.include_router(core_routes(kit))
    web.include_router(admin_pages.routes(kit))
    web.include_router(knowledge_pages.routes(kit))
    web.include_router(task_pages.routes(kit))
    web.include_router(week_pages.routes(kit))
    web.include_router(ai_pages.routes(kit))
    web.include_router(google_pages.routes(kit))


def core_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    # ----- signing in and out -------------------------------------------------

    @router.get("/login/{token}", response_class=HTMLResponse)
    def login_page(request: Request, token: str) -> HTMLResponse:
        if not kit.auth.link_is_valid(token):
            return kit.page(
                request,
                "message.html",
                410,
                title="That link has expired",
                body=EXPIRED_LINK,
                offer_google=True,
            )
        return kit.page(request, "login.html", token=token)

    @router.post("/login/{token}")
    def login(request: Request, token: str) -> Response:
        member = kit.auth.consume_link(token)
        if member is None:
            return kit.page(
                request, "message.html", 410, title="That link has expired", body=EXPIRED_LINK
            )
        return kit.signed_in(member)

    @router.get("/signed-out", response_class=HTMLResponse)
    def signed_out(request: Request) -> HTMLResponse:
        return kit.page(
            request,
            "message.html",
            title="You're signed out",
            body="Sending /site to Themi in Telegram gets you a sign-in link.",
            offer_google=True,
        )

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        await kit.checked(request)
        kit.auth.end_session(request.cookies.get(COOKIE_NAME))
        response = RedirectResponse("/signed-out", status_code=303)
        response.delete_cookie(COOKIE_NAME)
        return response

    # ----- dashboard ------------------------------------------------------------

    def dashboard_values(member: Member) -> dict[str, Any]:
        autonomy = app.services.autonomy
        actions = autonomy.open_for(member)
        activity = app.db.query(
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
            "actions": actions,
            "activity": [
                {**row, "words": EVENT_WORDS.get(row["event"], row["event"])} for row in activity
            ],
            "alerts": alerts,
            "groceries": app.services.groceries.needed() if app.services.groceries else [],
        }

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(
            request, "dashboard.html", session, **dashboard_values(session.member)
        )

    @router.post("/groceries/{item_id}/bought")
    async def grocery_bought(request: Request, item_id: int) -> Response:
        await kit.checked(request)
        groceries, pantry = app.services.groceries, app.services.pantry
        item = groceries.get(item_id) if groceries else None
        if item is None or item.status != "needed" or groceries is None:
            return kit.redirect("/", "That one is already off the list.")
        if pantry is not None:
            pantry.set_status(item.name, "plenty", source="list")  # takes it off the list too
        else:
            groceries.finish(item.name)
        return kit.redirect("/", f"Took {item.name} off the list.")

    @router.post("/actions/{action_id}/{decision}")
    async def decide(request: Request, action_id: int, decision: str) -> Response:
        session, _ = await kit.checked(request)
        try:
            choice = Decision(decision)
        except ValueError:
            return kit.page(request, "message.html", 404, title="Not found", body="")
        message = await app.approvals.resolve(action_id, choice, session.member)
        if request.headers.get("HX-Request"):
            action = app.services.autonomy.action(action_id)
            return kit.page(
                request, "_action_card.html", action=action, result=message, csrf=session.csrf_token
            )
        return kit.redirect("/", message)

    # ----- personal settings ------------------------------------------------------

    def settings_values(member: Member, **extra: Any) -> dict[str, Any]:
        return {
            "day_names": DAY_NAMES,
            "tracking": [
                (name, TRACKING_LABELS[name], member.tracks(name)) for name in TRACKING_INPUTS
            ],
            "strengths": STRENGTH_LABELS,
            **extra,
        }

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(request, "settings.html", session, **settings_values(session.member))

    @router.post("/settings")
    async def save_settings(request: Request) -> Response:
        session, form = await kit.checked(request)
        member = session.member  # always the signed-in member; any member_id field is ignored
        try:
            app.store.update_settings(
                member,
                member.id,
                quiet_start=str(form.get("quiet_start", "")) or None,
                quiet_end=str(form.get("quiet_end", "")) or None,
                daily_limit=as_int(form.get("daily_limit")),
                pda_enabled=form.get("pda_enabled") == "on",
                pda_strength=as_int(form.get("pda_strength")),
                phrasing=str(form.get("phrasing", "")) or None,
                phrasing_notes=str(form.get("phrasing_notes", "")),
                checkin_reviews=form.get("checkin_reviews") == "on",
                chart_limit=as_int(form.get("chart_limit")),
                tracking={name: form.get(f"track_{name}") == "on" for name in TRACKING_INPUTS},
            )
        except InvalidValue as exc:
            return kit.page(
                request,
                "settings.html",
                400,
                member=member,
                csrf=session.csrf_token,
                **settings_values(member, error=str(exc)),
            )
        return kit.redirect("/settings", "Saved.")

    @router.post("/settings/busy")
    async def add_busy_time(request: Request) -> Response:
        session, form = await kit.checked(request)
        member = app.store.get_member(session.member.id)
        try:
            busy = BusyTime(
                tuple(d for d in range(7) if form.get(f"day_{d}") == "on"),
                _parse_time(str(form.get("start", ""))),
                _parse_time(str(form.get("end", ""))),
            )
            app.store.update_settings(member, member.id, busy_times=[*member.busy_times, busy])
        except InvalidValue as exc:
            return kit.page(
                request,
                "settings.html",
                400,
                member=member,
                csrf=session.csrf_token,
                **settings_values(member, error=str(exc)),
            )
        return kit.redirect("/settings", f"Busy time added: {busy.label()}.")

    @router.post("/settings/busy/{index}/remove")
    async def remove_busy_time(request: Request, index: int) -> Response:
        session, _ = await kit.checked(request)
        member = app.store.get_member(session.member.id)
        if 0 <= index < len(member.busy_times):
            kept = [b for i, b in enumerate(member.busy_times) if i != index]
            app.store.update_settings(member, member.id, busy_times=kept)
        return kit.redirect("/settings", "Busy time removed.")

    return router


def _parse_time(text: str) -> time:
    try:
        hours, minutes = text.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise InvalidValue("a busy time needs a start and an end, like 09:00") from exc


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def as_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value))
    except ValueError as exc:
        raise InvalidValue(f"{value!r} isn't a whole number") from exc
