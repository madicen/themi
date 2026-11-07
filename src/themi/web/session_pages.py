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

import contextlib
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from themi.accounts.store import InvalidValue
from themi.web.auth import COOKIE_NAME, SESSION_TTL
from themi.web.kit import Kit, NotSignedIn

log = logging.getLogger(__name__)


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
    def session_page(request: Request, ticket: str = "") -> Response:
        token = ""
        member = kit.auth.consume_link(ticket) if ticket else None
        if member is not None:  # signed in from Telegram: the page carries the session
            token = kit.auth.start_session(member)
            signed = kit.auth.session(token)
        else:
            try:
                signed = kit.current(request)
            except NotSignedIn:  # opened from Telegram: the page signs in with initData
                return page(request, member=None, csrf="", state=None, session_token="")
        assert signed is not None
        bd = body_double()
        state = bd.state(signed.member) if bd is not None else {"active": False}
        response = page(request, member=signed.member, csrf=signed.csrf_token, state=state,
                        session_token=token)  # fmt: skip
        if token:  # the cookie too, for a browser that keeps it
            response.set_cookie(
                COOKIE_NAME, token, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                samesite="lax", secure=kit.ctx.secure_cookies,
            )  # fmt: skip
        return response

    @router.post("/session/telegram")
    async def telegram_sign_in(request: Request) -> Response:
        form = dict(await request.form())
        channel = app.channel
        check = getattr(channel, "web_app_user", None)
        user_id = check(str(form.get("init_data", ""))) if check is not None else None
        member = app.store.member_by_telegram(user_id) if user_id is not None else None
        if member is None:
            return Response(status_code=403)
        # A one-time ticket (a sign-in link's token: once, 10 minutes) for the page's
        # address, not a cookie: Telegram's in-app browser may drop cookies (bug 2026-11-07).
        ticket = kit.auth.create_link_token(member)
        return JSONResponse({"ticket": ticket}, headers={"Cache-Control": "no-store"})

    @router.post("/session/report")
    async def page_report(request: Request) -> Response:
        """What went wrong on the page itself (a script error, a refused request), so a
        problem in Telegram's in-app browser shows in the server's log. Short text only."""
        body = (await request.body())[:500].decode("utf-8", "replace")
        who = "signed out"
        with contextlib.suppress(NotSignedIn):
            who = f"member {kit.current(request).member.id}"
        log.warning("Session page (%s, %s): %s", who,
                    request.headers.get("user-agent", "")[:80], " ".join(body.split()))  # fmt: skip
        return Response(status_code=204)

    @router.post("/session/ticket")
    async def fresh_ticket(request: Request) -> JSONResponse:
        """A new one-time ticket, so the page can reload itself without a cookie."""
        signed, _ = await kit.checked(request)
        ticket = kit.auth.create_link_token(signed.member)
        return JSONResponse({"ticket": ticket}, headers={"Cache-Control": "no-store"})

    @router.get("/session/state")
    def session_state(request: Request) -> JSONResponse:
        signed = kit.current(request)
        bd = body_double()
        state = bd.state(signed.member) if bd is not None else {"active": False}
        return JSONResponse(state, headers={"Cache-Control": "no-store"})

    @router.post("/session/music")
    async def session_music(request: Request) -> Response:
        """BD5a: their loop and volume, kept for next time."""
        signed, form = await kit.checked(request)
        from themi.core.body_double_music import set_sound

        sound = str(form.get("sound", "")) or None
        try:
            volume = int(str(form["volume"])) if form.get("volume") not in (None, "") else None
            set_sound(app.store, signed.member, sound, volume)
        except (ValueError, InvalidValue):
            return Response(status_code=400)
        bd = body_double()
        if form.get("played") and bd is not None:  # BD5b: it played in this session
            from themi.core.body_double_music import LOOPS

            member = app.store.get_member(signed.member.id)
            loop = LOOPS[member.body_double_sound]
            bd.note_music(member, f"builtin:{loop.key}", loop.name)
        return Response(status_code=204)

    @router.post("/session/chat")
    async def session_chat(request: Request) -> Response:
        """BD3b: chat on the page during a sprint's break, as their own chat with Themi."""
        signed, form = await kit.checked(request)
        bd = body_double()
        event = bd.page_chat_event(signed.member, str(form.get("text", ""))) if bd else None
        handler = getattr(app.channel, "handler", None)
        if event is not None and handler is not None:
            await handler.handle(event, app.channel)
        if request.headers.get("X-Requested-With") == "fetch":
            return session_state(request)
        return kit.redirect("/session")

    @router.get("/session/pictures/{session_id}/{index}")
    def step_picture(request: Request, session_id: int, index: int) -> Response:
        """BD4b: a step's picture, only ever to the session's owner."""
        signed = kit.current(request)
        bd = body_double()
        pictures = getattr(bd, "pictures", None)
        found = bd.get(session_id) if bd is not None else None
        if pictures is None or found is None or found.member_id != signed.member.id:
            return Response(status_code=404)
        row = pictures.row(session_id, index)
        path = pictures.path(row) if row is not None else None
        if row is None or path is None:
            return Response(status_code=404)
        return FileResponse(path, media_type=row["mime_type"] or "image/png",
                            headers={"Cache-Control": "private, max-age=3600"})  # fmt: skip

    @router.post("/session/pictures/redo")
    async def redo_picture(request: Request) -> Response:
        signed, form = await kit.checked(request)
        pictures = getattr(body_double(), "pictures", None)
        if pictures is not None:
            try:
                step = int(str(form.get("step", "0")) or 0)
                pictures.redo(signed.member, step, str(form.get("words", "")))
            except ValueError:
                pass
        if request.headers.get("X-Requested-With") == "fetch":
            return session_state(request)
        return kit.redirect("/session")

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
