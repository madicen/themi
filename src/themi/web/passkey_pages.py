"""SP7b: passkeys for admins without Telegram, and a recovery code.

An admin adds passkeys on /passkeys (offered after the claim, and on My settings), and
makes a recovery code to print. On the signed-out page, "Sign in with a passkey" and "Use
a recovery code" are there once any admin has a passkey. Family members never see any of
it: they sign in with the link /site sends.

The WebAuthn checks are py_webauthn's. The relying party is the site's own host name
(`THEMI_PUBLIC_URL`'s), and passkeys work only where the browser counts the site as
secure: HTTPS, or `localhost` (not `127.0.0.1`) when trying Themi on one computer.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from themi.accounts.passkeys import Passkeys
from themi.web.auth import WebAuth
from themi.web.kit import Kit

COOKIE = "themi_passkey"


def relying_party(base_url: str) -> tuple[str, str]:
    """(the relying party's id, the origin) for the site at `base_url`."""
    parts = urlparse(base_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    return parts.hostname or "localhost", origin


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    keys = Passkeys(app.store)
    rp_id, origin = relying_party(kit.ctx.base_url)

    def with_challenge(body: str, token: str) -> Response:
        response = Response(body, media_type="application/json")
        response.set_cookie(
            COOKIE, token, max_age=300, httponly=True, samesite="strict",
            secure=kit.ctx.secure_cookies,
        )  # fmt: skip
        return response

    def csrf_ok(request: Request) -> Any:
        session = kit.admin(request)
        if not WebAuth.csrf_ok(session, request.headers.get("X-CSRF-Token")):
            raise PermissionError("missing or wrong CSRF token")
        return session

    # ----- the admin's page -------------------------------------------------------------

    @router.get("/passkeys", response_class=HTMLResponse)
    def passkeys_page(request: Request) -> HTMLResponse:
        session = kit.admin(request)
        return kit.with_flash(
            request,
            "passkeys.html",
            session,
            passkeys=keys.of(session.member),
            has_code=keys.has_recovery_code(session.member),
            secure=origin.startswith("https://") or rp_id == "localhost",
        )

    @router.post("/passkeys/options")
    def register_options(request: Request) -> Response:
        session = csrf_ok(request)
        member = session.member
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name="Themi",
            user_id=str(member.id).encode(),
            user_name=member.name,
            user_display_name=member.name,
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=p.credential_id) for p in keys.of(member)
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        token = keys.start("register", options.challenge, member)
        return with_challenge(options_to_json(options), token)

    @router.post("/passkeys/register")
    async def register(request: Request) -> Response:
        session = csrf_ok(request)
        body = await request.json()
        challenge = keys.finish(request.cookies.get(COOKIE), "register", session.member)
        if challenge is None:
            return JSONResponse({"error": "That took too long. Try again."}, status_code=400)
        try:
            found = verify_registration_response(
                credential=body.get("credential"),
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=origin,
                require_user_verification=False,
            )
        except Exception as exc:  # what the library says is wrong with it
            return JSONResponse({"error": f"That passkey wasn't accepted: {exc}"}, 400)
        name = (
            str(body.get("name") or "").strip()[:60]
            or f"Passkey {len(keys.of(session.member)) + 1}"
        )
        keys.add(
            session.member, found.credential_id, found.credential_public_key, found.sign_count, name
        )
        return JSONResponse({"next": "/passkeys"})

    @router.post("/passkeys/{passkey_id}/remove")
    async def remove(request: Request, passkey_id: int) -> Response:
        session, _ = await kit.checked(request, admin=True)
        keys.remove(session.member, passkey_id)
        return kit.redirect("/passkeys", "Removed that passkey.")

    @router.post("/passkeys/recovery-code", response_class=HTMLResponse)
    async def recovery_code(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        code = keys.new_recovery_code(session.member)
        return kit.with_flash(request, "recovery_code.html", session, code=code)

    # ----- signing in -----------------------------------------------------------------

    @router.post("/passkeys/sign-in/options")
    def sign_in_options() -> Response:
        options = generate_authentication_options(
            rp_id=rp_id, user_verification=UserVerificationRequirement.PREFERRED
        )
        token = keys.start("sign_in", options.challenge)
        return with_challenge(options_to_json(options), token)

    @router.post("/passkeys/sign-in")
    async def sign_in(request: Request) -> Response:
        body = await request.json()
        credential = body.get("credential") or {}
        challenge = keys.finish(request.cookies.get(COOKIE), "sign_in")
        refused = JSONResponse({"error": "That passkey didn't sign you in."}, status_code=400)
        if challenge is None:
            return JSONResponse({"error": "That took too long. Try again."}, status_code=400)
        try:
            passkey = keys.find(base64url_to_bytes(str(credential.get("rawId", ""))))
        except Exception:
            return refused
        if passkey is None:
            return refused
        member = app.store.get_member(passkey.member_id)
        if not member.is_admin:
            return refused
        try:
            checked = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=False,
            )
        except Exception:
            return refused
        keys.used(passkey, checked.new_sign_count)
        redirect = kit.signed_in(member, "/")
        return JSONResponse({"next": "/"}, headers={"set-cookie": redirect.headers["set-cookie"]})

    @router.get("/recovery", response_class=HTMLResponse)
    def recovery_page(request: Request) -> HTMLResponse:
        return kit.page(request, "recovery.html")

    @router.post("/recovery", response_class=HTMLResponse)
    async def use_recovery(request: Request) -> Response:
        form = await request.form()
        member = keys.use_recovery_code(str(form.get("code", "")))
        if member is None:
            return kit.page(
                request, "recovery.html", 400, problem="That isn't a recovery code that works."
            )
        response = kit.signed_in(member, "/passkeys")
        message = kit.redirect("/passkeys", "Signed in. That code is used up: make a new one.")
        response.headers.append("set-cookie", message.headers["set-cookie"])
        return response

    return router


def offered(kit: Kit) -> bool:
    """Whether the signed-out page offers passkeys and recovery codes."""
    return Passkeys(kit.app.store).any()
