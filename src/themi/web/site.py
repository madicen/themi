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
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from themi.accounts import TRACKING_INPUTS, BusyTime, InvalidValue, Member
from themi.accounts.models import DAY_NAMES
from themi.accounts.passkeys import Passkeys
from themi.accounts.preferences import Preferences
from themi.accounts.store import MENU_BAR_MAX
from themi.autonomy import Decision
from themi.core import keys, pronouns
from themi.modules import StartReport
from themi.modules.web import GROUP_ORDER, MenuEntry
from themi.standard import conversation_mode
from themi.web import icons, welcome
from themi.web.auth import COOKIE_NAME
from themi.web.kit import HERE, AdminsOnly, Kit, NotSignedIn, SiteContext, static_file
from themi.web.welcome import SITE_LINK_CHANNELS

__all__ = ["SiteContext", "install_site"]

log = logging.getLogger(__name__)

TRACKING_LABELS = {
    "text_notes": 'Notes about how you\'re doing ("that call took a lot out of me")',
    "message_timing": "When you tend to reply, and how quickly",
    "device_activity": "Activity from household devices (laundry, feeders, a display's routines)",
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
EXPIRED_LINK = (
    "Sign-in links work once, for 10 minutes. Sending /site to Themi (/themi site in Slack) "
    "gets a fresh one."
)


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


# The chat channels where /site (Slack: `/themi site`) sends a sign-in link (SL5): in
# welcome.py, which its steps need too.


def sign_in_hint(channels: set[str]) -> str:
    """How to get a sign-in link, in the words of the chats this Themi has (SL5)."""
    ways = []
    if "telegram" in channels:
        ways.append("/site to Themi in Telegram")
    if "slack" in channels:
        ways.append("/themi site in Slack")
    if not ways:
        return "Sign in with a passkey or Google below."
    return f"Sending {' or '.join(ways)} gets you a sign-in link."


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


class PackStatic(StaticFiles):
    """CR17b: the core's static files under /static/, and each pack's under
    /static/<pack>/ (one mount, so the routes stay as they were)."""

    def __init__(self, core: Path, packs: dict[str, Path]) -> None:
        super().__init__(directory=str(core))
        self.packs = packs

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        head, _, rest = path.partition("/")
        folder = self.packs.get(head) if rest else None
        if folder is None:
            return super().lookup_path(path)
        try:
            full = static_file(path, self.packs)
            return str(full), os.stat(full)
        except (ValueError, FileNotFoundError, NotADirectoryError):
            return "", None


def install_site(web: FastAPI, ctx: SiteContext) -> None:
    from themi.web import (
        accounts_page,
        admin_pages,
        ai_pages,
        claim_pages,
        dev_pages,
        modules_page,
        passkey_pages,
    )

    kit = Kit(ctx)
    modules_pages = ctx.app.services.web_pages
    services = ctx.app.services
    names = words(services.start_report.template if services.start_report else "family")
    kit.templates.env.globals["words"] = names
    menu = Menu(
        [
            *core_menu(services, names),
            *(entry for pages in modules_pages for entry in pages.menu),
        ],
        names,
    )
    kit.templates.env.globals["menu_bar"] = menu.bar
    # F35a: Themi in the third person, as the family chose ("on her own", "she's back").
    kit.templates.env.globals["themi_words"] = lambda: pronouns.pronouns(
        pronouns.chosen(ctx.app.store)
    )
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
    web.mount("/static", PackStatic(HERE / "static", kit.static_folders), name="static")

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
    web.include_router(modules_page.routes(kit))  # SP4
    web.include_router(claim_pages.routes(kit))  # SP7a
    web.include_router(passkey_pages.routes(kit))  # SP7b
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
    def signed_out(request: Request) -> Response:
        if app.store.get_family() is None:  # SP7a: nobody has claimed this Themi yet
            return RedirectResponse("/claim", status_code=303)
        return kit.page(
            request,
            "message.html",
            title="You're signed out",
            body=sign_in_hint(set(app.channel.channels)),
            offer_google=True,
            offer_passkey=Passkeys(app.store).any(),  # SP7b
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
        report = app.services.start_report
        broken = [f"{s.name} couldn't start: {s.reason}" for s in report.failed()]
        setup_steps = finish_setting_up(report) if member.is_admin else []
        if (
            member.is_admin
            and not set(member.channels) & SITE_LINK_CHANNELS
            and not Passkeys(app.store).of(member)
        ):  # SP7b: no /site link for them, so a passkey is their way back in
            setup_steps.append(
                ("Add a passkey, so you can sign in again without Telegram.", "/passkeys")
            )
        if member.is_admin:
            # SP1: a module that couldn't start, said to admins (SP7a: the rest of what
            # SP1 said is on the "Finish setting up" card)
            alerts.extend(broken)
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
            "modules_link": bool(member.is_admin and broken),  # SP4: links to Modules
            "setup_steps": setup_steps,  # SP7a
        }

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        session = kit.current(request)
        steps = welcome.steps(app, session.member, kit.templates.env.globals["words"])
        if welcome.shown(app, session.member, steps):  # a new Themi: setting it up
            return kit.with_flash(
                request,
                "welcome.html",
                session,
                steps=steps,
                ready=welcome.ready(steps),
            )
        return kit.with_flash(
            request, "dashboard.html", session, **dashboard_values(session.member)
        )

    @router.post("/welcome/done")
    async def welcome_done(request: Request) -> Response:
        await kit.checked(request, admin=True)
        welcome.dismiss(app)
        return kit.redirect("/", "The rest of setting up is on Home, and on Modules.")

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
            "pronoun_choices": pronouns.CHOICES,  # F35a
            "themi_pronouns": pronouns.chosen(app.store),
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
        choice = str(form.get("themi_pronouns", ""))
        if choice in pronouns.CHOICES:  # F35a: anyone in the family may change it
            app.store.set_household_value(pronouns.PronounSettings.module, "themi_pronouns", choice)
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


def finish_setting_up(report: StartReport) -> list[tuple[str, str]]:
    """SP7a: what's left before this Themi is useful, for an admin's dashboard: (what to do,
    where). Empty once it's done."""
    steps = []
    if not report.has_ai():
        choices = ", ".join(report.ai_choices) or "an AI provider module"
        steps.append(
            (
                f"Themi has no AI provider yet, so it can't answer. Add one of {choices}.",
                "/modules/gemini",
            )
        )
    chats = [
        s
        for s in report.modules.values()
        if s.kind == "channel" and s.state == "on" and s.name != "web_chat"
    ]
    if not chats and "slack" in report.modules and "telegram" not in report.modules:
        steps.append(("Set up Slack, so you can chat with Themi there.", "/modules/slack"))
    elif not chats:
        steps.append(("Set up a way to chat from a phone, like Telegram.", "/modules/telegram"))
    for status in report.modules.values():
        if status.state != "not_set_up" or status.kind == "channel":
            continue
        if status.warn or status.reason.startswith("added"):
            steps.append((f"{status.name} needs its settings.", f"/modules/{status.name}"))
    return steps


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
    MenuEntry(  # SP4: what this Themi is made of, and setting it up
        "/modules",
        "Modules",
        "What Themi can do, and setting it up",
        "Admin",
        5,
        admin_only=True,
        bar_label="Modules",
        icon=icons.MODULES,
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
# What the core's pages call the people and the place. The family template's words; any
# other Themi (one person at work, or built up from empty) gets plainer ones.
FAMILY_WORDS = {
    "family": "Family",
    "family_hint": "The household and its people",
    "household": "Household",
    "name": "Family name",
}
PLAIN_WORDS = {
    "family": "People",
    "family_hint": "Who uses this Themi, and its name",
    "household": "This Themi",
    "name": "Name",
}


def words(template: str) -> dict[str, str]:
    return FAMILY_WORDS if template == "family" else PLAIN_WORDS


def core_menu(services: Any, names: dict[str, str]) -> list[MenuEntry]:
    """The core's entries for this Themi: the Accounts ones only when a module puts
    something there (a new Themi has no Google), and the Family page in its words."""
    sections = services.accounts_sections
    shown = {
        "/accounts": any(not s.household for s in sections),
        "/accounts#household": any(s.household for s in sections),
    }
    entries = []
    for entry in CORE_MENU:
        if not shown.get(entry.href, True):
            continue
        if entry.href == "/family":
            entry = replace(
                entry, label=names["family"], hint=names["family_hint"], bar_label=names["family"]
            )
        entries.append(entry)
    return entries


# An admin's bar on a Themi with no main pages of its own yet (only Home): setting it up.
SETUP_BAR = ("/modules", "/dev")
BAR_FULL_TEXT = "The bar holds four pages, and More. Unpin one first, then pin this one."
NOT_A_PAGE = "Only pages from the More page can go on the bar."


class Menu:
    """The More page and the bottom bar (W1, F28c), from the core's entries and the loaded
    modules' (CR4)."""

    def __init__(self, entries: Sequence[MenuEntry], names: dict[str, str] | None = None) -> None:
        self.group_names = {"Household": (names or FAMILY_WORDS)["household"]}
        hrefs = [e.href for e in entries]
        twice = sorted({h for h in hrefs if hrefs.count(h) > 1})
        if twice:
            raise ValueError(f"two menu entries for {', '.join(twice)}")
        self.entries = sorted(entries, key=lambda e: (e.group, e.order))
        self.by_href = {e.href: e for e in entries}

    def main_pages(self) -> list[tuple[str, str, str]]:
        """The bar's own pages (Home, Tasks, Lists for the family): the default bar."""
        return [(e.href, e.label, e.hint) for e in self.entries if e.group == "Main"]

    def default_bar(self, member: Member | None = None) -> tuple[str, ...]:
        """The main pages; for an admin of a Themi with none but Home, Modules and
        Development too (a new Themi, being set up)."""
        main = tuple(href for href, _, _ in self.main_pages())
        if member is not None and member.is_admin and main == ("/",):
            return (*main, *(href for href in SETUP_BAR if href in self.by_href))
        return main

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
                groups.append((self.group_names.get(group, group), links))
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
        chosen = self.default_bar(member) if member.menu_bar is None else member.menu_bar
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
    (85, "settings/themi.html"),  # F35a: Themi's pronouns, the family's one choice
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
