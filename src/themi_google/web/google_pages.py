"""Google on the website: "Sign in with Google", and the Google parts of Accounts.

CR17a: the google module's pages, moved out of the core's with it; the Accounts page itself
is the core's, made of the modules' sections.

- `/auth/google` starts a sign-in. Only `openid email` is asked for, and only
  a member's sign-in address gets in.
- The "My Google accounts" section lists the signed-in member's linked Gmail accounts, with
  a button to link another (a POST, so it's CSRF-checked) and one to unlink each.
- The calendar module's "Family calendar" row, for admins (26).
- `/auth/google/callback` finishes both. A linking flow started from Telegram
  (`/link gmail`) lands here too, possibly in a browser that isn't signed in:
  the state carries the member, so it works either way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from markupsafe import Markup

from themi.accounts import AccountsError, LinkedAccount, Member
from themi.core import keys
from themi.web.accounts_page import back
from themi.web.auth import COOKIE_NAME
from themi.web.kit import Kit
from themi_google.connectors.gcal import CalendarError
from themi_google.connectors.google import (
    CALENDAR_SCOPE,
    DRIVE_FILE_SCOPE,
    TASKS_SCOPE,
    GoogleAccounts,
    OAuthError,
    ScopeNeed,
)
from themi_google.expected import DEFAULT_CATEGORY

NOT_SET_UP = "Google sign-in isn't set up on this server. /site in Telegram sends a sign-in link."


def _sentence(text: str) -> str:
    text = text.strip()
    if text.startswith("invalid literal for int"):
        return "How often and the grace period are whole numbers of days."
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")


def section_values(services: Any) -> Callable[[Member], dict[str, Any]]:
    """The "My Google accounts" section: their accounts, and what each can do (the
    expected emails, Google Tasks, the cookbook, when those modules are loaded)."""

    def values(member: Member) -> dict[str, Any]:
        accounts = services.store.linked_accounts(member.id)
        expected = services.maybe(keys.expected)
        recipes = services.maybe(keys.recipes)
        google = services.maybe(keys.google)
        needs = google.needs() if google is not None else []
        return {
            # CR18a: what each account doesn't allow yet, of what the loaded modules need
            "relink": {a.id: relink(google.missing(a)) for a in accounts} if google else {},
            "needed": {n.what for n in needs},
            "accounts": accounts,
            "can_link": services.maybe(keys.google) is not None,
            "expected": {a.id: expected.for_account(a.id) for a in accounts} if expected else {},
            "protectable": [c for c in services.autonomy.categories() if not c.capped],
            "tasks_scope": TASKS_SCOPE,
            "cookbook_scope": DRIVE_FILE_SCOPE,  # RC1a
            "cookbook": recipes.settings() if recipes is not None and recipes.ready() else None,
        }

    return values


def relink(missing: list[ScopeNeed]) -> dict[str, Any] | None:
    """CR18a: what an account linked before a module came says, and its button's words
    ("Link again for Google Tasks and the cookbook")."""
    if not missing:
        return None
    names = [n.what for n in missing]
    label = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return {
        # Markup: the sentences are the modules' own words, never anyone's input.
        "sentences": [
            Markup(n.missing or f"{n.what[:1].upper()}{n.what[1:]} isn't allowed yet.")
            for n in missing
        ],
        "label": f"Link again for {label}",
    }


def calendar_values(services: Any) -> Callable[[Member], dict[str, Any]]:
    """The "Family calendar" row (26): where tasks with dates are written."""

    def values(_member: Member) -> dict[str, Any]:
        calendar = services.get(keys.calendar)
        chosen, name = calendar.settings()
        account = calendar.account()
        return {
            "calendar": {
                "accounts": calendar.eligible_accounts(),
                "chosen": chosen,
                "name": name,
                "using": account.address if account else None,
                "problem": calendar.problem(),
            }
        }

    return values


def calendar_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    @router.post("/family/calendar")
    async def save_calendar(request: Request) -> Response:
        _session, form = await kit.checked(request, admin=True)
        calendar = app.services.maybe(keys.calendar)
        to = back("family-calendar")
        if calendar is None:
            return kit.redirect(to, "Google isn't set up on this server yet.")
        account = str(form.get("account", ""))
        try:
            calendar.choose(int(account) if account.isdigit() else None, str(form.get("name", "")))
        except ValueError as exc:
            return kit.redirect(to, f"Not saved: {exc}.")
        return kit.redirect(to, "Saved the calendar settings.")

    return router


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def google() -> GoogleAccounts | None:
        return app.services.maybe(keys.google)

    def redirect_uri() -> str:
        return GoogleAccounts.redirect_uri(kit.ctx.base_url)

    def problem(request: Request, body: str, status: int = 400) -> HTMLResponse:
        return kit.page(
            request,
            "message.html",
            status,
            title="That didn't work",
            body=body,
            offer_google=True,
        )

    @router.get("/auth/google")
    def start_signin(request: Request) -> Response:
        accounts = google()
        if accounts is None:
            return problem(request, NOT_SET_UP, 404)
        return RedirectResponse(
            accounts.oauth.authorization_url("signin", redirect_uri()), status_code=303
        )

    @router.get("/auth/google/callback", response_class=HTMLResponse)
    async def callback(
        request: Request, state: str = "", code: str = "", error: str = ""
    ) -> Response:
        accounts = google()
        if accounts is None:
            return problem(request, NOT_SET_UP, 404)
        if error:
            return problem(request, "Google sign-in was cancelled, so nothing changed.")
        if not state or not code:
            return problem(request, "That address is only for coming back from Google.")
        try:
            grant = await accounts.oauth.complete(state, code, redirect_uri())
            if grant.purpose == "signin":
                return kit.signed_in(accounts.member_for(grant))
            account = await accounts.link(grant)
        except (OAuthError, AccountsError) as exc:
            return problem(request, str(exc), 403)
        session = kit.auth.session(request.cookies.get(COOKIE_NAME))
        message = f"Linked {account.address}."
        if session is not None and session.member.id == account.member_id:
            return kit.redirect("/accounts", message)
        return kit.page(
            request,
            "message.html",
            title=message,
            body="Themi can see this inbox now. This page can be closed.",
        )

    # ----- My accounts ----------------------------------------------------------

    @router.post("/accounts/link")
    async def link(request: Request) -> Response:
        session, _ = await kit.checked(request)
        accounts = google()
        if accounts is None:
            return kit.redirect("/accounts", "Linking Gmail isn't set up on this server yet.")
        url = accounts.link_url(session.member, redirect_uri())
        return RedirectResponse(url, status_code=303)

    @router.post("/accounts/{account_id}/settings")
    async def account_settings(request: Request, account_id: int) -> Response:
        session, form = await kit.checked(request)
        senders = str(form.get("urgent_senders", "")).replace(",", "\n").splitlines()
        try:
            account = app.store.update_linked_account(
                session.member,
                account_id,
                watched=form.get("watched") == "on",
                urgent_senders=senders,
            )
        except AccountsError as exc:
            message = (
                str(exc) if "isn't an email" in str(exc) else "That account isn't one of yours."
            )
            return kit.redirect("/accounts", message)
        return kit.redirect("/accounts", f"Saved the settings for {account.address}.")

    # ----- which calendars Themi reads (K1) ------------------------------------------------

    async def _family_calendar(app: Any) -> tuple[int, str] | None:
        sync = app.services.maybe(keys.calendar)
        if sync is None or sync.account() is None:
            return None
        try:
            target = await sync.target()
        except Exception:  # not set up yet, or Google didn't answer: no family calendar to show
            return None
        return target.account.id, target.calendar_id

    def own_account(member: Member, account_id: int) -> LinkedAccount | None:
        return next((a for a in app.store.linked_accounts(member.id) if a.id == account_id), None)

    @router.get("/accounts/{account_id}/calendars", response_class=HTMLResponse)
    async def calendars_page(request: Request, account_id: int) -> Response:
        session = kit.current(request)
        account = own_account(session.member, account_id)
        reader, sync = app.services.maybe(keys.calendars), app.services.maybe(keys.calendar)
        if account is None or reader is None or sync is None:
            return kit.redirect("/accounts", "That account isn't one of yours.")
        if not account.allows(CALENDAR_SCOPE):
            return kit.redirect("/accounts", "Link this account again to let Themi see calendars.")
        try:
            listed = await sync.client(account.id).calendars()
        except CalendarError:
            return kit.redirect("/accounts", "Google didn't answer; try again in a minute.")
        chosen = {c for c, _ in reader.calendars(account.id)}
        options = [
            (str(c["id"]), str(c.get("summaryOverride") or c.get("summary") or c["id"]),
             str(c["id"]) in chosen or (c.get("primary") and chosen == {"primary"}))
            for c in listed
        ]  # fmt: skip
        copies = app.services.maybe(keys.calendar_copies)
        shown = (
            {r.calendar_id: r.level for r in copies.rules(session.member)
             if r.account_id == account.id}
            if copies is not None
            else {}
        )  # fmt: skip
        family = await _family_calendar(app)
        return kit.with_flash(
            request, "calendars.html", session, account=account, options=options,
            shown=shown, family=family if family and family[0] == account.id else None,
            labels=copies.labels(session.member) if copies is not None else {},
            copies=copies is not None,
        )  # fmt: skip

    @router.post("/accounts/{account_id}/calendars/shown")
    async def show_calendars(request: Request, account_id: int) -> Response:
        """F34f: how each calendar of theirs shows on the family calendar, and the labels."""
        session, form = await kit.checked(request)
        account = own_account(session.member, account_id)
        copies = app.services.maybe(keys.calendar_copies)
        if account is None or copies is None:
            return kit.redirect("/accounts", "That account isn't one of yours.")
        copies.set_labels(
            session.member,
            {k: str(form.get(f"label_{k}", "")) for k in ("meeting", "focus", "other")},
        )
        said = []
        current = {r.calendar_id: r.level for r in copies.rules(session.member)
                   if r.account_id == account.id}  # fmt: skip
        for key in form:
            if not key.startswith("level_"):
                continue
            calendar_id = key.removeprefix("level_")
            level = str(form.get(key) or "off")
            if level == current.get(calendar_id, "off"):
                continue
            name = str(form.get(f"name_{calendar_id}", calendar_id))
            try:
                said.append(
                    await copies.set_rule(session.member, account.id, calendar_id, name, level)
                )
            except ValueError as exc:
                said.append(f"{name}: {exc}.")
        return kit.redirect(
            f"/accounts/{account.id}/calendars", " ".join(said) or "Saved the labels."
        )

    @router.post("/accounts/{account_id}/calendars")
    async def choose_calendars(request: Request, account_id: int) -> Response:
        session, form = await kit.checked(request)
        account = own_account(session.member, account_id)
        reader = app.services.maybe(keys.calendars)
        if account is None or reader is None:
            return kit.redirect("/accounts", "That account isn't one of yours.")
        ticked = (await request.form()).getlist("calendar")  # every box, not just one
        chosen = [(str(value), str(form.get(f"name_{value}", value))) for value in ticked]
        reader.choose(account.id, chosen)
        names = ", ".join(n for _, n in chosen) or "your primary calendar"
        return kit.redirect("/accounts", f"Themi reads {names} for {account.address}.")

    @router.post("/accounts/{account_id}/expected")
    async def add_expected(request: Request, account_id: int) -> Response:
        session, form = await kit.checked(request)
        expected = app.services.maybe(keys.expected)
        if expected is None:
            return kit.redirect("/accounts", "Email isn't set up on this server.")
        try:
            added = expected.add(
                session.member,
                account_id,
                name=str(form.get("name", "")),
                sender=str(form.get("sender", "")),
                subject=str(form.get("subject", "")),
                cadence_days=int(str(form.get("cadence_days", "30")) or 30),
                grace_days=int(str(form.get("grace_days", "3")) or 3),
                category=str(form.get("category") or DEFAULT_CATEGORY),
            )
        except ValueError as exc:
            return kit.redirect("/accounts", _sentence(str(exc)))
        except AccountsError:
            return kit.redirect("/accounts", "That account isn't one of yours.")
        return kit.redirect("/accounts", f"Watching for {added.name}.")

    @router.post("/accounts/{account_id}/expected/{expected_id}/remove")
    async def remove_expected(request: Request, account_id: int, expected_id: int) -> Response:
        session, _ = await kit.checked(request)
        expected = app.services.maybe(keys.expected)
        try:
            if expected is None or expected.get(expected_id).account_id != account_id:
                raise AccountsError
            removed = expected.remove(session.member, expected_id)
        except AccountsError:
            return kit.redirect("/accounts", "That account isn't one of yours.")
        return kit.redirect("/accounts", f"No longer watching for {removed.name}.")

    @router.post("/accounts/{account_id}/unlink")
    async def unlink(request: Request, account_id: int) -> Response:
        session, _ = await kit.checked(request)
        accounts = google()
        try:
            if accounts is None:  # nothing to revoke with; just forget it
                address = app.store.get_linked_account(account_id).address
                app.store.remove_linked_account(session.member, account_id)
                return kit.redirect("/accounts", f"Unlinked {address}.")
            result = await accounts.unlink(session.member, account_id)
        except AccountsError:
            return kit.redirect("/accounts", "That account isn't one of yours.")
        if result.revoked:
            return kit.redirect(
                "/accounts", f"Unlinked {result.address}, and Google cancelled its access."
            )
        return kit.redirect(
            "/accounts",
            f"Unlinked {result.address}. Google couldn't be reached to cancel access, so it may "
            "still be listed at myaccount.google.com/permissions; removing it there finishes it.",
        )

    return router
