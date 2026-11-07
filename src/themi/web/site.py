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

import logging
from collections.abc import Awaitable, Callable
from datetime import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from themi.accounts import TRACKING_INPUTS, BusyTime, InvalidValue, Member
from themi.accounts.models import DAY_NAMES
from themi.accounts.store import MENU_BAR_MAX
from themi.autonomy import Decision
from themi.core import conversation_mode
from themi.core.body_double import MODES
from themi.web.auth import COOKIE_NAME
from themi.web.kit import HERE, AdminsOnly, Kit, NotSignedIn, SiteContext
from themi.web.task_pages import task_rows

__all__ = ["SiteContext", "install_site"]

log = logging.getLogger(__name__)
HOME_TASKS = 5
GROCERIES_ON_LISTS = "/lists?open=groceries#groceries"

TRACKING_LABELS = {
    "text_notes": 'Notes about how you\'re doing ("that call took a lot out of me")',
    "message_timing": "When you tend to reply, and how quickly",
    "device_activity": "Activity from household devices (laundry, feeders, the wall's routines)",
    "calendar": "When your Google calendar says you're busy (never what the events are)",
    "reactions": "How you react to Themi's messages (👍 or 👎), to learn what lands",
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


# RC1a: the cookbook page runs Google's file picker, the one page that loads Google's own
# scripts (agreed 2026-11-06). Only a page that asks for it (the X-Themi-Page header) gets it.
PICKER_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://apis.google.com https://accounts.google.com https://*.gstatic.com; "
    "style-src 'self' 'unsafe-inline' https://accounts.google.com https://*.gstatic.com; "
    "img-src 'self' data: https://*.gstatic.com https://*.googleusercontent.com; "
    "frame-src https://docs.google.com https://drive.google.com https://accounts.google.com "
    "https://content.googleapis.com; "
    "connect-src 'self' https://*.googleapis.com https://accounts.google.com; "
)


def security_headers(response: Response, form_targets: str = "") -> None:
    """`form_targets`: extra origins a form may lead to (Google's sign-in page, via redirect)."""
    form_action = f"'self' {form_targets}".strip()
    page = response.headers.get("X-Themi-Page")
    if page is not None:
        del response.headers["X-Themi-Page"]
    base = (
        PICKER_POLICY
        if page == "picker"
        else "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    )
    # BD3a: the session page opens as a Telegram Mini App, which Telegram's web app frames.
    ancestors = "https://web.telegram.org" if page == "session" else "'none'"
    response.headers["Content-Security-Policy"] = (
        f"{base}frame-ancestors {ancestors}; form-action {form_action}; base-uri 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    if page != "session":
        response.headers["X-Frame-Options"] = "DENY"
    # Login links carry their token in the URL; never leak it in a Referer.
    response.headers["Referrer-Policy"] = "no-referrer"


def install_site(web: FastAPI, ctx: SiteContext) -> None:
    from themi.web import (
        admin_pages,
        ai_pages,
        connection_pages,
        dev_pages,
        email_pages,
        google_pages,
        guide_pages,
        knowledge_pages,
        list_pages,
        maintenance_pages,
        recipe_pages,
        safeway_pages,
        session_pages,
        spending_pages,
        task_pages,
        week_pages,
    )

    kit = Kit(ctx)
    kit.templates.env.globals["menu_bar"] = menu_bar
    google = ctx.app.services.google
    # Linking POSTs to Themi, which redirects to Google; browsers check that redirect too.
    form_targets = _origin(google.oauth.config.auth_url) if google is not None else ""
    home_connect = ctx.app.services.home_connect
    if home_connect is not None:  # and to Home Connect's and SingleKey ID's, to link it (H1)
        config = home_connect.client.config
        hops = f"{_origin(config.base_url)} {_origin(config.sign_in_url)}"
        form_targets = f"{form_targets} {hops}".strip()
    music = ctx.app.services.music
    if music is not None:  # BD5b: linking Spotify leads to its sign-in page
        accounts = _origin(music.links.client.config.accounts_url)
        form_targets = f"{form_targets} {accounts}".strip()
    web.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @web.middleware("http")
    async def headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        security_headers(response, form_targets)
        if request.url.path.startswith("/static/"):  # checked each time (a cheap 304)
            response.headers["Cache-Control"] = "no-cache"
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
        log.info("Refused %s %s: %s", request.method, request.url.path, exc)
        return kit.page(
            request,
            "message.html",
            403,
            title="That didn't go through",
            body="The page was out of date. Going back and trying again usually helps.",
        )

    web.include_router(core_routes(kit))
    web.include_router(admin_pages.routes(kit))
    web.include_router(connection_pages.routes(kit))
    web.include_router(knowledge_pages.routes(kit))
    web.include_router(guide_pages.routes(kit))
    web.include_router(recipe_pages.routes(kit))
    web.include_router(task_pages.routes(kit))
    web.include_router(list_pages.routes(kit))
    web.include_router(week_pages.routes(kit))
    web.include_router(spending_pages.routes(kit))
    web.include_router(maintenance_pages.routes(kit))
    web.include_router(safeway_pages.routes(kit))
    web.include_router(email_pages.routes(kit))
    web.include_router(ai_pages.routes(kit))
    web.include_router(dev_pages.routes(kit))
    web.include_router(google_pages.routes(kit))
    web.include_router(session_pages.routes(kit))  # BD3a


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
        noise = app.services.noise.waiting(member) if app.services.noise else []
        held = {a.id for a in noise}  # F16b: one link to their own page, not a card each
        actions = [a for a in actions if a.id not in held]
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
        tasks: dict[str, Any] = {"mine": [], "more_tasks": 0}
        if app.services.taskboard is not None:  # W2: the first few, with Done
            tasks = task_rows(app, member, limit=HOME_TASKS)
            total = len(app.services.taskboard.open_for(member))
            tasks["more_tasks"] = total if total > HOME_TASKS else 0
        appliances = app.services.appliances
        return {
            **tasks,
            "around_the_house": appliances.at_a_glance() if appliances else None,
            "actions": actions,
            "activity": [
                {**row, "words": EVENT_WORDS.get(row["event"], row["event"])} for row in activity
            ],
            "alerts": alerts,
            "noise_count": len(noise),
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
        _, form = await kit.checked(request)
        back = GROCERIES_ON_LISTS if form.get("back") == "lists" else "/"
        groceries, pantry = app.services.groceries, app.services.pantry
        item = groceries.get(item_id) if groceries else None
        if item is None or item.status != "needed" or groceries is None:
            return kit.redirect(back, "That one is already off the list.")
        if pantry is not None:
            pantry.set_status(item.name, "plenty", source="list")  # takes it off the list too
        else:
            groceries.finish(item.name)
        return kit.redirect(back, f"Took {item.name} off the list.")

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

    @router.get("/more", response_class=HTMLResponse)
    def more(request: Request) -> HTMLResponse:
        session = kit.current(request)
        member = session.member
        pages = pinnable(member)
        on_bar = bar_pages(member)
        groups = more_groups(member)
        off_bar = [(h, label, hint) for h, label, hint in MAIN_PAGES if h not in on_bar]
        if off_bar:  # Home, Tasks or Lists taken off the bar: still a tap away
            groups.insert(0, ("Main", off_bar))
        return kit.with_flash(
            request,
            "more.html",
            session,
            groups=groups,
            bar=[(href, pages[href]) for href in on_bar],
            on_bar=set(on_bar),
            bar_full=len(on_bar) >= MENU_BAR_MAX,
            pinnable=set(pages),
        )

    @router.post("/more/bar")
    async def change_bar(request: Request) -> Response:
        """Pin, unpin or move a page on the signed-in member's own menu bar (F28c)."""
        session, form = await kit.checked(request)
        member = session.member
        action, href = str(form.get("action", "")), str(form.get("href", ""))
        bar = bar_pages(member)
        if action == "reset":
            app.store.set_menu_bar(member, member.id, None)
            return kit.redirect("/more", "The bar is back to Home, Tasks and Lists.")
        if action == "pin" and href not in pinnable(member):
            return kit.page(request, "message.html", 400, title="Not a page", body=NOT_A_PAGE)
        if action not in ("pin", "unpin", "up", "down") or (action != "pin" and href not in bar):
            return kit.redirect("/more")
        if action == "pin":
            if href in bar:
                return kit.redirect("/more")
            if len(bar) >= MENU_BAR_MAX:
                return kit.redirect("/more", BAR_FULL_TEXT)
            bar.append(href)
        elif action == "unpin":
            bar.remove(href)
        else:
            at = bar.index(href)
            to = at - 1 if action == "up" else at + 1
            if 0 <= to < len(bar):
                bar[at], bar[to] = bar[to], bar[at]
        app.store.set_menu_bar(member, member.id, bar)
        return kit.redirect("/more")

    # ----- personal settings ------------------------------------------------------

    def settings_values(member: Member, **extra: Any) -> dict[str, Any]:
        return {
            "day_names": DAY_NAMES,
            "tracking": [
                (name, TRACKING_LABELS[name], member.tracks(name)) for name in TRACKING_INPUTS
            ],
            "strengths": STRENGTH_LABELS,
            "conversation_offered": conversation_mode.offered(app.services, member),
            "picked_out": (  # CM1b: what the sidecar picked out lately
                app.services.conversation.sidecar.recent(member, 10)
                if app.services.conversation is not None
                and conversation_mode.offered(app.services, member)
                else []
            ),
            "job_modes": job_modes(member),  # BD2
            **extra,
        }

    def job_modes(member: Member) -> list[tuple[str, str, str]]:
        """(category, its words, their own mode or "") for each kind of job (BD2)."""
        from themi.core.body_double_modes import CATEGORIES, CATEGORY_WORDS

        body_double = app.services.body_double
        if body_double is None or body_double.modes is None:
            return []
        own = body_double.modes.defaults(member)
        return [(c, CATEGORY_WORDS[c], own.get(c, "")) for c in CATEGORIES]

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
                done_praise=form.get("done_praise") == "on",
                listen_first=form.get("listen_first") == "on",
                day_budget=as_int(form.get("day_budget")),
                focus_count=as_int(form.get("focus_count")),
                chart_limit=as_int(form.get("chart_limit")),
                chart_counts_shared=form.get("chart_counts_shared") == "on",
                calendar_details=str(form.get("calendar_details", "")) or None,
                morning_summary=str(form.get("morning_summary", "")),
                morning_summary_empty=form.get("morning_summary_empty") == "on",
                getting_ready_minutes=as_int(form.get("getting_ready_minutes")),
                leave_heads_up=form.get("leave_heads_up") == "on",
                setup_note=form.get("setup_note") == "on",
                list_style=str(form.get("list_style", "")) or None,
                break_extend_minutes=as_int(form.get("break_extend_minutes")),
                sprint_work_minutes=as_int(form.get("sprint_work_minutes")),
                sprint_break_minutes=as_int(form.get("sprint_break_minutes")),
                noise_emails=str(form.get("noise_emails", "")) or None,
                tracking={name: form.get(f"track_{name}") == "on" for name in TRACKING_INPUTS},
                conversation_mode=(  # CM1a: only when the switch was on the page
                    form.get("conversation_mode") == "on"
                    if conversation_mode.offered(app.services, member)
                    else None
                ),
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
        body_double = app.services.body_double
        if body_double is not None and body_double.modes is not None:  # BD2: their own modes
            for category, _, _ in job_modes(member):
                if f"job_mode_{category}" in form:
                    chosen = str(form.get(f"job_mode_{category}", ""))
                    body_double.modes.set_default(
                        member, category, chosen if chosen in MODES else None
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


def more_groups(member: Member) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """The More page (W1): every page past the bottom bar's three, grouped."""
    admin = member.is_admin
    accounts = [("/accounts", "Google accounts", "Gmail, calendars and Google Tasks")]
    if admin:
        accounts.append(
            ("/accounts#household", "Household connections", "Appliances, vacuum, calendar")
        )
    household = [
        ("/knowledge", "Rules & memory", "What Themi keeps to and remembers"),
        ("/guides", "Guides", "Your own cooking charts and how-tos"),
        ("/recipes", "Recipes", "The family cookbook, and cooking with Themi"),
        ("/tiers", "What Themi does alone", "What asks first and what's automatic"),
        ("/maintenance", "Maintenance", "Filters, gutters and other upkeep"),
        ("/spending", "Spending", "Takeout and business expenses"),
        ("/safeway", "Safeway", "The cart helper and remembered products"),
    ]
    if admin:
        household.insert(0, ("/family", "Family", "The household and its people"))
    groups = [
        (
            "You",
            [
                ("/settings", "My settings", "Quiet hours, messages, phrasing"),
                ("/week", "My week", "How Themi sees your week"),
                ("/ai", "My AI", "Which AI does each job"),
            ],
        ),
        ("Accounts", accounts),
        ("Household", household),
    ]
    if admin:
        groups.append(("Admin", [("/dev", "Development", "Update or restart the server")]))
    return groups


# ----- the menu bar (F28c, idea #144) ---------------------------------------------

MAIN_PAGES = [
    ("/", "Home", "Today, and what's waiting on you"),
    ("/tasks", "Tasks", "Everything to do"),
    ("/lists", "Lists", "Shopping and the other lists"),
]
DEFAULT_BAR = ("/", "/tasks", "/lists")
BAR_FULL_TEXT = "The bar holds four pages, and More. Unpin one first, then pin this one."
NOT_A_PAGE = "Only pages from the More page can go on the bar."
# The bar's short names; pages not named here use their More-page label.
BAR_LABELS = {
    "/settings": "Settings",
    "/week": "Week",
    "/ai": "AI",
    "/accounts": "Accounts",
    "/knowledge": "Rules",
    "/tiers": "Tiers",
    "/maintenance": "Upkeep",
    "/family": "Family",
    "/dev": "Dev",
}
# Inline SVG paths (the CSP allows no inline styles; the stylesheet strokes them).
BAR_ICONS = {
    "/": "M3 11 12 4l9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
    "/tasks": "m4 12 5 5L20 6",
    "/lists": "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
    "/settings": "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
    "/week": "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
    "/ai": "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
    "/accounts": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6",
    "/knowledge": "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11",
    "/tiers": "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z",
    "/maintenance": "M14 6a4 4 0 0 0 5 5L11 19a2 2 0 0 1-3-3l8-8a4 4 0 0 0-2-2z",
    "/spending": "M12 3v18M17 7H10a3 3 0 0 0 0 6h4a3 3 0 0 1 0 6H6",
    "/safeway": "M3 4h3l2 11h11l2-8H7M10 20h.01M17 20h.01",
    "/family": (
        "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20c0-3 3-5 6-5s6 2 6 5"
        "M16 5a3 3 0 0 1 0 6M18 15c2 1 3 3 3 5"
    ),
    "/dev": "m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14",
}
ICON_OTHER = "M12 12h.01M12 5h.01M12 19h.01"
ICON_MORE = "M5 12h.01M12 12h.01M19 12h.01"


def pinnable(member: Member) -> dict[str, str]:
    """Every page this member can open that can go on the bar: path -> label. A part of a
    page ("/accounts#household") can't; its page can."""
    pages = {href: label for href, label, _ in MAIN_PAGES}
    for _, links in more_groups(member):
        pages.update({href: label for href, label, _ in links if "#" not in href})
    return pages


def bar_pages(member: Member) -> list[str]:
    """The pages on this member's bar, in order: their choice, less any they can no longer
    open (an admin page after the role changed)."""
    pages = pinnable(member)
    chosen = DEFAULT_BAR if member.menu_bar is None else member.menu_bar
    return [href for href in chosen if href in pages]


def _is_on(href: str, path: str) -> bool:
    return path == href if href == "/" else path == href or path.startswith(f"{href}/")


def menu_bar(member: Member, path: str) -> list[dict[str, Any]]:
    """The bar for base.html: the member's pages and More, the one for `path` current
    (More for any page not on the bar)."""
    pages = pinnable(member)
    items = [
        {
            "href": href,
            "label": BAR_LABELS.get(href, pages[href]),
            "icon": BAR_ICONS.get(href, ICON_OTHER),
            "current": _is_on(href, path),
            "dots": False,
        }
        for href in bar_pages(member)
    ]
    on_some = any(item["current"] for item in items)
    items.append(
        {"href": "/more", "label": "More", "icon": ICON_MORE, "current": not on_some, "dots": True}
    )
    return items


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
