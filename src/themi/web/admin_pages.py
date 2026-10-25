"""Household pages: the family (admins only) and trust tiers (admins change, all can see).

Turning a category's "automatic" switch on creates and locks an autonomy-grant
rule in the admin's name, so the change is visible in /rules and can be
undone like any other rule. Capped categories have no switch at all.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi.accounts import AccountsError, InvalidValue, Role
from themi.accounts.setup import pairing_instructions, parse_money_to_cents
from themi.autonomy import AutonomyError
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
            **extra,
        }

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
        return kit.with_flash(
            request, "tiers.html", session, categories=app.services.autonomy.categories()
        )

    @router.post("/tiers/{category}/{change}")
    async def change_tier(request: Request, category: str, change: str) -> Response:
        session, _ = await kit.checked(request, admin=True)
        rulebook, autonomy = app.rulebook, app.services.autonomy
        try:
            if change == "automatic":
                rulebook.grant_automatic(session.member, category)
                message = "Automatic from now on. It's listed with the household rules."
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
