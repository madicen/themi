"""Household pages: the family (admins only) and trust tiers (admins change, all can see).

Turning a category's "automatic" switch on creates and locks an autonomy-grant
rule in the admin's name, so the change is visible in /rules and can be
undone like any other rule. Capped categories have no switch at all.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from themi.accounts import AccountsError, InvalidValue, Role
from themi.accounts.setup import pairing_instructions, parse_money_to_cents
from themi.autonomy import AutonomyError
from themi.connectors.homeconnect import HomeConnectAccount, HomeConnectError
from themi.connectors.travel import TravelError
from themi.core.rules import RuleError
from themi.web.kit import Kit


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    store = app.store

    # ----- family ---------------------------------------------------------------

    def family_values(**extra: Any) -> dict[str, Any]:
        family = store.get_family()
        return {
            "family": family,
            "budget": f"{family.takeout_budget_cents / 100:.2f}" if family else "0.00",
            "members": store.list_members(),
            "calendar": calendar_values(),
            "home": app.services.travel.home() if app.services.travel else None,
            "travel": app.services.travel is not None,
            "home_connect": home_connect_values(),
            **extra,
        }

    def calendar_values() -> dict[str, Any] | None:
        calendar = app.services.calendar
        if calendar is None:
            return None
        chosen, name = calendar.settings()
        account = calendar.account()
        return {
            "accounts": calendar.eligible_accounts(),
            "chosen": chosen,
            "name": name,
            "using": account.address if account else None,
            "problem": calendar.problem(),
        }

    def home_connect_values() -> dict[str, Any] | None:
        account, dishwasher = app.services.home_connect, app.services.dishwasher
        if account is None or dishwasher is None:
            return None
        states = {r["device_id"]: r["state"] for r in app.db.query("SELECT * FROM device_states")}
        return {
            "linked": account.linked(),
            "devices": [(d, states.get(d.id)) for d in dishwasher.devices()],
        }

    # ----- Home Connect (H1) ----------------------------------------------------------------

    @router.post("/family/home-connect/link")
    async def link_home_connect(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        account = app.services.home_connect
        if account is None:
            return kit.redirect("/family", "Home Connect isn't set up on this server.")
        redirect = HomeConnectAccount.redirect_uri(kit.ctx.base_url)
        return RedirectResponse(
            account.authorization_url(session.member, redirect), status_code=303
        )

    @router.get("/auth/home-connect/callback")
    async def home_connect_callback(
        request: Request, state: str = "", code: str = "", error: str = ""
    ) -> Response:
        account, dishwasher = app.services.home_connect, app.services.dishwasher
        if account is None or dishwasher is None:
            return kit.redirect("/family", "Home Connect isn't set up on this server.")
        if error or not state or not code:
            return kit.redirect("/family", "Home Connect wasn't linked, so nothing changed.")
        try:
            member_id = await account.complete(
                state, code, HomeConnectAccount.redirect_uri(kit.ctx.base_url)
            )
            added = await dishwasher.add_appliances(store.get_member(member_id))
        except (HomeConnectError, AccountsError) as exc:
            return kit.redirect("/family", f"Home Connect wasn't linked: {exc}")
        names = ", ".join(d.name for d in added)
        return kit.redirect(
            "/family", f"Linked Home Connect. Found {names}." if names else "Linked Home Connect."
        )

    @router.post("/family/home-connect/unlink")
    async def unlink_home_connect(request: Request) -> Response:
        await kit.checked(request, admin=True)
        if app.services.home_connect is not None:
            app.services.home_connect.unlink()
        return kit.redirect(
            "/family",
            "Unlinked Home Connect. Removing Themi in the Home Connect app's settings finishes it.",
        )

    @router.post("/family/home")
    async def save_home(request: Request) -> Response:
        """The family's home, for travel times (K4)."""
        _, form = await kit.checked(request, admin=True)
        travel = app.services.travel
        if travel is None:
            return kit.redirect("/family", "Travel times aren't set up.")
        address = str(form.get("address", ""))
        try:
            place = await travel.set_home(address)
        except TravelError:
            return kit.redirect("/family", "The map service didn't answer; try again shortly.")
        if place is None:
            return kit.redirect(
                "/family", "That address wasn't found on the map. Try adding the city."
            )
        return kit.redirect("/family", "Home saved. Travel times start from there.")

    @router.get("/family", response_class=HTMLResponse)
    def family_page(request: Request) -> HTMLResponse:
        session = kit.admin(request)
        return kit.with_flash(request, "family.html", session, **family_values())

    @router.post("/family")
    async def save_family(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        staples = tuple(line.strip() for line in str(form.get("staples", "")).splitlines())
        try:
            store.update_family(
                session.member,
                name=str(form.get("name", "")),
                timezone=str(form.get("timezone", "")),
                takeout_budget_cents=parse_money_to_cents(str(form.get("budget", "0"))),
                staples=staples,
            )
        except AccountsError as exc:
            return kit.page(
                request,
                "family.html",
                400,
                member=session.member,
                csrf=session.csrf_token,
                **family_values(error=str(exc)),
            )
        return kit.redirect("/family", "Saved.")

    @router.post("/family/calendar")
    async def save_calendar(request: Request) -> Response:
        _session, form = await kit.checked(request, admin=True)
        calendar = app.services.calendar
        if calendar is None:
            return kit.redirect("/family", "Google isn't set up on this server yet.")
        account = str(form.get("account", ""))
        try:
            calendar.choose(int(account) if account.isdigit() else None, str(form.get("name", "")))
        except ValueError as exc:
            return kit.redirect("/family", f"Not saved: {exc}.")
        return kit.redirect("/family", "Saved the calendar settings.")

    @router.post("/family/members")
    async def add_member(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        role = Role.ADMIN if form.get("role") == "admin" else Role.MEMBER
        try:
            member = store.create_member(session.member, str(form.get("name", "")), role)
            code = store.create_invite(session.member, member.id)
        except AccountsError as exc:
            return kit.redirect("/family", str(exc))
        return kit.redirect("/family", pairing_instructions(member, code))

    @router.post("/family/members/{member_id}/invite")
    async def new_invite(request: Request, member_id: int) -> Response:
        session, _ = await kit.checked(request, admin=True)
        member = store.get_member(member_id)
        if member.telegram_user_id is not None:
            return kit.redirect("/family", f"{member.name} is already connected.")
        code = store.create_invite(session.member, member.id)
        return kit.redirect("/family", pairing_instructions(member, code))

    @router.post("/family/members/{member_id}/email")
    async def set_email(request: Request, member_id: int) -> Response:
        session, form = await kit.checked(request, admin=True)
        try:
            member = store.set_email(session.member, member_id, str(form.get("email", "")))
        except AccountsError as exc:
            return kit.redirect("/family", str(exc))
        if member.email:
            return kit.redirect(
                "/family", f"{member.name} can sign in with Google as {member.email}."
            )
        return kit.redirect("/family", f"{member.name} no longer signs in with Google.")

    @router.post("/family/members/{member_id}/role")
    async def change_role(request: Request, member_id: int) -> Response:
        session, form = await kit.checked(request, admin=True)
        role = Role.ADMIN if form.get("role") == "admin" else Role.MEMBER
        try:
            member = store.set_role(session.member, member_id, role)
        except InvalidValue as exc:
            return kit.redirect("/family", str(exc))
        return kit.redirect(
            "/family", f"{member.name} is now {'an admin' if member.is_admin else 'a member'}."
        )

    @router.post("/family/members/{member_id}/remove")
    async def remove_member(request: Request, member_id: int) -> Response:
        session, form = await kit.checked(request, admin=True)
        member = store.get_member(member_id)
        if form.get("confirm_name", "").strip().lower() != member.name.lower():
            return kit.redirect("/family", f"To remove {member.name}, type their name to confirm.")
        # Their Gmail tokens are revoked at Google once they're removed here.
        tokens = [store.refresh_token(a.id) for a in store.linked_accounts(member_id)]
        try:
            store.delete_member(session.member, member_id)
        except InvalidValue as exc:
            return kit.redirect("/family", str(exc))
        google = kit.app.services.google
        if google is not None:
            for token in tokens:
                await google.revoke_quietly(token)
        return kit.redirect("/family", f"{member.name} has been removed, with their data.")

    # ----- trust tiers ------------------------------------------------------------

    @router.get("/tiers", response_class=HTMLResponse)
    def tiers_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        autonomy = app.services.autonomy
        categories = autonomy.categories()
        names = {m.id: m.name for m in store.list_members()}
        # F16a: a personal category is automatic per person, so show theirs and who else's.
        mine = {c.name for c in categories if autonomy.granted(c.name, session.member)}
        others = {
            c.name: [names[i] for i in autonomy.granted_to(c.name) if i != session.member.id]
            for c in categories
            if c.scope == "member"
        }
        return kit.with_flash(
            request, "tiers.html", session, categories=categories, mine=mine, others=others
        )

    @router.post("/tiers/{category}/{change}")
    async def change_tier(request: Request, category: str, change: str) -> Response:
        session, _ = await kit.checked(request)  # the rulebook checks who may (F16a)
        rulebook, autonomy = app.rulebook, app.services.autonomy
        try:
            if change == "automatic":
                rule = rulebook.grant_automatic(session.member, category)
                message = (
                    "Automatic for you from now on. It's listed with your rules."
                    if rule.scope == "personal"
                    else "Automatic from now on. It's listed with the household rules."
                )
            elif change == "supervised":
                rulebook.revoke_automatic(session.member, category)
                message = "Back to asking first."
            elif change == "resume":
                autonomy.resume(category, by=session.member)
                message = "Resumed. It runs automatically again."
            else:
                return kit.page(request, "message.html", 404, title="Not found", body="")
        except (RuleError, AutonomyError, AccountsError) as exc:
            message = str(exc)
        return kit.redirect("/tiers", message)

    return router
