"""The management website: sign-in, the dashboard and personal settings.

The admin, trust-tier, rules-and-memory and AI pages live in sibling modules
and are installed from `install_site`.

Server-rendered HTML with a little HTMX (vendored, no CDN). Every page works
without JavaScript; HTMX just swaps a card in place instead of reloading.

Security:
- Sign-in by one-time link from the bot, or with Google for members' addresses
  (the google module's pages).
- Sessions are server-side; the cookie is HttpOnly and SameSite=Lax, and
  Secure when the site is on HTTPS.
- Every POST needs the session's CSRF token (form field or X-CSRF-Token header).
- Pages only ever show or change the signed-in member's own personal
  settings: no such page takes a member id.
- A strict Content-Security-Policy allows only same-origin scripts and styles.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from themi.accounts import TRACKING_INPUTS, BusyTime, InvalidValue, Member
from themi.accounts.models import DAY_NAMES
from themi.accounts.preferences import Preferences
from themi.accounts.store import MENU_BAR_MAX
from themi.autonomy import Decision
from themi.core import keys
from themi.modules.web import GROUP_ORDER, MenuEntry
from themi.standard import conversation_mode
from themi.web import icons
from themi.web.auth import COOKIE_NAME
from themi.web.kit import HERE, AdminsOnly, Kit, NotSignedIn, SiteContext

__all__ = ["SiteContext", "install_site"]

log = logging.getLogger(__name__)

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
    if page == "session":
        # BD4b, bug 2026-11-07: the session page loads its step pictures with its session
        # header (Telegram's browser may drop cookies) and shows them from blob: addresses,
        # made by its own script from its own server's answers.
        base = base.replace("img-src 'self' data:;", "img-src 'self' data: blob:;")
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
    from themi.web import accounts_page, admin_pages, ai_pages, dev_pages

    kit = Kit(ctx)
    modules_pages = ctx.app.services.web_pages
    menu = Menu([*CORE_MENU, *(entry for pages in modules_pages for entry in pages.menu)])
    kit.templates.env.globals["menu_bar"] = menu.bar
    google = ctx.app.services.maybe(keys.google)
    # Linking POSTs to Themi, which redirects to Google; browsers check that redirect too.
    form_targets = _origin(google.oauth.config.auth_url) if google is not None else ""
    home_connect = ctx.app.services.maybe(keys.home_connect)
    if home_connect is not None:  # and to Home Connect's and SingleKey ID's, to link it (H1)
        config = home_connect.client.config
        hops = f"{_origin(config.base_url)} {_origin(config.sign_in_url)}"
        form_targets = f"{form_targets} {hops}".strip()
    music = ctx.app.services.maybe(keys.music)
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

    web.include_router(core_routes(kit, menu))
    web.include_router(admin_pages.routes(kit))
    web.include_router(accounts_page.routes(kit))  # CR17a: made of the modules' sections
    web.include_router(ai_pages.routes(kit))
    web.include_router(dev_pages.routes(kit))
    for pages in modules_pages:  # CR4: each loaded module's pages
        web.include_router(pages.routes(kit))


def core_routes(kit: Kit, menu: Menu) -> APIRouter:
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
        # CR17a: a module's line stands for some of these (F16b: the noise digest's emails
        # are one link to their own page, not a card each).
        waiting = [link for fn in app.services.waiting_links if (link := fn(member))]
        held = {i for link in waiting for i in link.held}
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
        panels: list[str] = []  # CR17a: the modules' panels, in their order
        values: dict[str, Any] = {}
        for panel in sorted(app.services.dashboard_panels, key=lambda p: p.order):
            panels.append(panel.template)
            values.update((panel.values(member) or {}) if panel.values else {})
        return {
            **values,
            "panels": panels,
            "actions": actions,
            "waiting": waiting,
            "activity": [
                {**row, "words": EVENT_WORDS.get(row["event"], row["event"])} for row in activity
            ],
            "alerts": alerts,
        }

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(
            request, "dashboard.html", session, **dashboard_values(session.member)
        )

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
        pages = menu.pinnable(member)
        on_bar = menu.bar_pages(member)
        groups = menu.more_groups(member)
        off_bar = [(h, label, hint) for h, label, hint in menu.main_pages() if h not in on_bar]
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
        bar = menu.bar_pages(member)
        if action == "reset":
            app.store.set_menu_bar(member, member.id, None)
            return kit.redirect("/more", "The bar is back to Home, Tasks and Lists.")
        if action == "pin" and href not in menu.pinnable(member):
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
                app.services.maybe(keys.conversation).sidecar.recent(member, 10)
                if app.services.maybe(keys.conversation) is not None
                and conversation_mode.offered(app.services, member)
                else []
            ),
            "sections": settings_sections(app.services),  # CR7d: core's and modules', in order
            "prefs": {  # CR7a: each loaded module's preferences, by module
                model.module: app.store.preferences(member.id, model)
                for model in app.services.preference_models
            },
            **{k: v for values in app.services.settings_values for k, v in values(member).items()},
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
            for model in app.services.preference_models:  # CR7a: each module's own
                shown = model.on_form(app.services, member)
                values = from_form(model, form, shown)
                app.store.save_preferences(member, member.id, model, **values)
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
                listen_first=form.get("listen_first") == "on",
                day_ends=as_int(form.get("day_ends")),
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
        for save in app.services.settings_savers:  # CR10a: the modules' own, not preferences
            save(member, form)
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


CORE_MENU = (
    MenuEntry("/", "Home", "Today, and what's waiting on you", "Main", 10, icon=icons.HOME),
    MenuEntry(
        "/settings",
        "My settings",
        "Quiet hours, messages, phrasing",
        "You",
        10,
        bar_label="Settings",
        icon=icons.SETTINGS,
    ),
    MenuEntry("/ai", "My AI", "Which AI does each job", "You", 30, bar_label="AI", icon=icons.AI),
    MenuEntry(
        "/accounts",
        "Google accounts",
        "Gmail, calendars and Google Tasks",
        "Accounts",
        10,
        bar_label="Accounts",
        icon=icons.ACCOUNTS,
    ),
    MenuEntry(
        "/accounts#household",
        "Household connections",
        "Appliances, vacuum, calendar",
        "Accounts",
        20,
        admin_only=True,
    ),
    MenuEntry(
        "/family",
        "Family",
        "The household and its people",
        "Household",
        5,
        admin_only=True,
        bar_label="Family",
        icon=icons.FAMILY,
    ),
    MenuEntry(
        "/tiers",
        "What Themi does alone",
        "What asks first and what's automatic",
        "Household",
        40,
        bar_label="Tiers",
        icon=icons.TIERS,
    ),
    MenuEntry(
        "/dev",
        "Development",
        "Update or restart the server",
        "Admin",
        10,
        admin_only=True,
        bar_label="Dev",
        icon=icons.DEV,
    ),
)
BAR_FULL_TEXT = "The bar holds four pages, and More. Unpin one first, then pin this one."
NOT_A_PAGE = "Only pages from the More page can go on the bar."


class Menu:
    """The More page and the bottom bar (W1, F28c), from the core's entries and the loaded
    modules' (CR4)."""

    def __init__(self, entries: Sequence[MenuEntry]) -> None:
        hrefs = [e.href for e in entries]
        twice = sorted({h for h in hrefs if hrefs.count(h) > 1})
        if twice:
            raise ValueError(f"two menu entries for {', '.join(twice)}")
        self.entries = sorted(entries, key=lambda e: (e.group, e.order))
        self.by_href = {e.href: e for e in entries}

    def main_pages(self) -> list[tuple[str, str, str]]:
        """The bar's own pages (Home, Tasks, Lists for the family): the default bar."""
        return [(e.href, e.label, e.hint) for e in self.entries if e.group == "Main"]

    def default_bar(self) -> tuple[str, ...]:
        return tuple(href for href, _, _ in self.main_pages())

    def more_groups(self, member: Member) -> list[tuple[str, list[tuple[str, str, str]]]]:
        """The More page (W1): every page past the bottom bar's, grouped; empty groups
        left out."""
        groups = []
        for group in GROUP_ORDER:
            links = [
                (e.href, e.label, e.hint)
                for e in self.entries
                if e.group == group and (member.is_admin or not e.admin_only)
            ]
            if links:
                groups.append((group, links))
        return groups

    def pinnable(self, member: Member) -> dict[str, str]:
        """Every page this member can open that can go on the bar: path -> label. A part of
        a page ("/accounts#household") can't; its page can."""
        pages = {href: label for href, label, _ in self.main_pages()}
        for _, links in self.more_groups(member):
            pages.update({href: label for href, label, _ in links if "#" not in href})
        return pages

    def bar_pages(self, member: Member) -> list[str]:
        """The pages on this member's bar, in order: their choice, less any they can no
        longer open (an admin page after the role changed, a module turned off)."""
        pages = self.pinnable(member)
        chosen = self.default_bar() if member.menu_bar is None else member.menu_bar
        return [href for href in chosen if href in pages]

    def bar(self, member: Member, path: str) -> list[dict[str, Any]]:
        """The bar for base.html: the member's pages and More, the one for `path` current
        (More for any page not on the bar)."""
        pages = self.pinnable(member)
        items = []
        for href in self.bar_pages(member):
            entry = self.by_href.get(href)
            items.append(
                {
                    "href": href,
                    "label": (entry.bar_label if entry else "") or pages[href],
                    "icon": (entry.icon if entry else "") or icons.OTHER,
                    "current": _is_on(href, path),
                    "dots": False,
                }
            )
        on_some = any(item["current"] for item in items)
        items.append(
            {
                "href": "/more",
                "label": "More",
                "icon": icons.MORE,
                "current": not on_some,
                "dots": True,
            }
        )
        return items


# CR7d: the settings form's own sections, as (order, template). Modules add theirs between
# (breaks 30, body double 40, the chore chart 50, email 70).
CORE_SETTINGS = (
    (10, "settings/quiet.html"),
    (20, "settings/limit.html"),
    (60, "settings/calendars.html"),
    (80, "settings/phrasing.html"),
    (90, "settings/gentle.html"),
    (100, "settings/tracking.html"),
)


def settings_sections(services: Any) -> list[str]:
    return [template for _, template in sorted([*CORE_SETTINGS, *services.settings_sections])]


def from_form(model: type[Preferences], form: Any, shown: set[str] | None = None) -> dict[str, Any]:
    """CR7a: a module's preferences from the settings form, for the fields the page showed
    (`shown`; None is all of them). A checkbox left unticked is False; a number left empty
    is left as it was; text is passed on as written ("" may mean off)."""
    values: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        if shown is not None and name not in shown:
            continue
        if info.annotation is bool:
            values[name] = form.get(name) == "on"
        elif info.annotation is int:
            values[name] = as_int(form.get(name))
        elif name in form:
            values[name] = str(form.get(name))
    return values


def _is_on(href: str, path: str) -> bool:
    return path == href if href == "/" else path == href or path.startswith(f"{href}/")


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
