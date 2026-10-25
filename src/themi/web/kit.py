"""Shared plumbing for the website's pages: sessions, CSRF, rendering, messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from themi.accounts import Member
from themi.localtime import to_local
from themi.web.auth import COOKIE_NAME, SESSION_TTL, Session, WebAuth

HERE = Path(__file__).parent
FLASH_COOKIE = "themi_flash"


class NotSignedIn(Exception):
    pass


class AdminsOnly(Exception):
    pass


@dataclass
class SiteContext:
    app: Any  # themi.app.App (typed loosely to keep this module import-light)
    base_url: str
    secure_cookies: bool


class Kit:
    def __init__(self, ctx: SiteContext) -> None:
        self.ctx = ctx
        self.app = ctx.app
        self.auth = WebAuth(ctx.app.store)
        self.templates = Jinja2Templates(directory=str(HERE / "templates"))
        self.templates.env.filters["local_time"] = self.local_time

    def timezone(self) -> str:
        family = self.app.store.get_family()
        return family.timezone if family else "UTC"

    def local_time(self, moment: str | datetime | None) -> str:
        if moment is None:
            return ""
        value = datetime.fromisoformat(moment) if isinstance(moment, str) else moment
        return to_local(value, self.timezone()).strftime("%a %d %b, %I:%M %p").replace(" 0", " ")

    # ----- sessions and CSRF ------------------------------------------------------

    def current(self, request: Request) -> Session:
        session = self.auth.session(request.cookies.get(COOKIE_NAME))
        if session is None:
            raise NotSignedIn
        return session

    def admin(self, request: Request) -> Session:
        session = self.current(request)
        if not session.member.is_admin:
            raise AdminsOnly
        return session

    async def checked(self, request: Request, *, admin: bool = False) -> tuple[Session, dict]:
        """The session and form for a POST, after checking its CSRF token (and role)."""
        session = self.admin(request) if admin else self.current(request)
        form = dict(await request.form())
        submitted = form.get("csrf") or request.headers.get("X-CSRF-Token")
        if not WebAuth.csrf_ok(session, str(submitted) if submitted else None):
            raise PermissionError("missing or wrong CSRF token")
        return session, form

    def signed_in(self, member: Member, to: str = "/") -> RedirectResponse:
        """Start a session for `member` and send them on to `to`."""
        response = RedirectResponse(to, status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            self.auth.start_session(member),
            max_age=int(SESSION_TTL.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=self.ctx.secure_cookies,
        )
        return response

    @property
    def google_signin(self) -> bool:
        return self.app.services.google is not None

    # ----- rendering ----------------------------------------------------------------

    def page(self, request: Request, name: str, status: int = 200, **values: Any) -> HTMLResponse:
        values.setdefault("google_signin", self.google_signin)
        response = self.templates.TemplateResponse(request, name, values, status_code=status)
        response.headers["Cache-Control"] = "no-store"
        return response

    def with_flash(
        self, request: Request, name: str, session: Session, **values: Any
    ) -> HTMLResponse:
        """Render a signed-in page, with any one-off message from the previous POST."""
        raw = request.cookies.get(FLASH_COOKIE)
        flash = unquote(raw) if raw else None
        response = self.page(
            request, name, flash=flash, member=session.member, csrf=session.csrf_token, **values
        )
        if flash:
            response.delete_cookie(FLASH_COOKIE)
        return response

    def redirect(self, url: str, message: str | None = None) -> RedirectResponse:
        response = RedirectResponse(url, status_code=303)
        if message:
            # Quoted: cookies can't carry newlines or most punctuation as-is.
            response.set_cookie(
                FLASH_COOKIE,
                quote(message),
                max_age=60,
                httponly=True,
                samesite="lax",
                secure=self.ctx.secure_cookies,
            )
        return response
