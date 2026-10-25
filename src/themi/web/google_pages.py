"""Google on the website: "Sign in with Google", and the My accounts page.

- `/auth/google` starts a sign-in. Only `openid email` is asked for, and only
  a member's sign-in address gets in.
- `/accounts` lists the signed-in member's linked Gmail accounts, with a
  button to link another (a POST, so it's CSRF-checked) and one to unlink each.
- `/auth/google/callback` finishes both. A linking flow started from Telegram
  (`/link gmail`) lands here too, possibly in a browser that isn't signed in:
  the state carries the member, so it works either way.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from themi.accounts import AccountsError
from themi.connectors.google import GoogleAccounts, OAuthError
from themi.web.auth import COOKIE_NAME
from themi.web.kit import Kit

NOT_SET_UP = "Google sign-in isn't set up on this server. /site in Telegram sends a sign-in link."


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def google() -> GoogleAccounts | None:
        return app.services.google

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

    @router.get("/accounts", response_class=HTMLResponse)
    def accounts_page(request: Request) -> HTMLResponse:
        session = kit.current(request)
        return kit.with_flash(
            request,
            "accounts.html",
            session,
            accounts=app.store.linked_accounts(session.member.id),
            can_link=google() is not None,
        )

    @router.post("/accounts/link")
    async def link(request: Request) -> Response:
        session, _ = await kit.checked(request)
        accounts = google()
        if accounts is None:
            return kit.redirect("/accounts", "Linking Gmail isn't set up on this server yet.")
        url = accounts.oauth.authorization_url("link", redirect_uri(), session.member)
        return RedirectResponse(url, status_code=303)

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
