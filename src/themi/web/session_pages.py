"""The body double session page (BD3a): one full-screen page, their own session only.

Signed in as the site is, or, opened from Telegram as a Mini App, by the `initData`
Telegram signs (checked with the bot's token, under a minute old, the member found by
their Telegram id; anything else is 403). The page shows the mode, what it's for, the
timer (counted in the browser from the server's times: the server is the truth), the step
in Guided, and the same buttons as chat, which post to the same `BodyDouble` methods. It
polls `/session/state` every 5 seconds, so a tap in chat shows on the page and the reverse.
Nothing about energy is ever on it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from themi.web.auth import COOKIE_NAME, SESSION_TTL
from themi.web.kit import Kit, NotSignedIn


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def body_double() -> Any:
        return app.services.body_double

    def page(request: Request, **values: Any) -> HTMLResponse:
        response = kit.page(request, "session.html", **values)
        response.headers["X-Themi-Page"] = "session"  # may be framed by Telegram's web app
        return response

    @router.get("/session", response_class=HTMLResponse)
    def session_page(request: Request) -> Response:
        try:
            signed = kit.current(request)
        except NotSignedIn:  # opened from Telegram: the page signs in with initData
            return page(request, member=None, csrf="", state=None)
        bd = body_double()
        state = bd.state(signed.member) if bd is not None else {"active": False}
        return page(request, member=signed.member, csrf=signed.csrf_token, state=state)

    @router.post("/session/telegram")
    async def telegram_sign_in(request: Request) -> Response:
        form = dict(await request.form())
        channel = app.channel
        check = getattr(channel, "web_app_user", None)
        user_id = check(str(form.get("init_data", ""))) if check is not None else None
        member = app.store.member_by_telegram(user_id) if user_id is not None else None
        if member is None:
            return Response(status_code=403)
        response = Response(status_code=204)
        response.set_cookie(
            COOKIE_NAME,
            kit.auth.start_session(member),
            max_age=int(SESSION_TTL.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=kit.ctx.secure_cookies,
        )
        return response

    @router.get("/session/state")
    def session_state(request: Request) -> JSONResponse:
        signed = kit.current(request)
        bd = body_double()
        state = bd.state(signed.member) if bd is not None else {"active": False}
        return JSONResponse(state, headers={"Cache-Control": "no-store"})

    @router.post("/session/{session_id}/act")
    async def session_act(request: Request, session_id: int) -> Response:
        signed, form = await kit.checked(request)
        bd = body_double()
        found = bd.get(session_id) if bd is not None else None
        if bd is None or found is None or found.member_id != signed.member.id:
            return Response(status_code=404)  # someone else's session is no business of theirs
        try:
            seq = int(str(form.get("seq", "")))
        except ValueError:
            seq = -1
        await bd.act_from_page(
            signed.member, session_id, str(form.get("action", "")), seq,
            str(form.get("mode", "")),
        )  # fmt: skip
        if request.headers.get("X-Requested-With") == "fetch":
            return session_state(request)
        return kit.redirect("/session")

    return router
