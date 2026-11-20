"""The wall (WL1): a page for the Cozyla frame, signed in as the household.

In the home pack, not the core: the core's standard modules never name the wall (CR21b).

The Themi Wall Plan is the design. This prompt is the module and the frame's sign-in:

- An admin presses Pair a frame on `/wall/frames` and gets a 6-digit code, good for 10
  minutes and once. The frame opens `/wall/pair` and types it, and gets its own cookie.
- A frame belongs to the household, not a person. Its cookie (`themi_wall`) is not a
  website session, so every other page answers it as signed out; it reaches only the wall.
- It doesn't run out with use. The admin page lists frames with when each was last seen,
  and Revoke signs one out at its next request.
- Five wrong codes in ten minutes stop pairing for ten minutes.
- The frame's token and the pairing code are kept only as hashes, never logged.
- A member's own session can open `/wall` too, for a look from a phone.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.core import keys
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.groups import YOUR_DAY
from themi.modules.web import MenuEntry
from themi.storage.db import Database
from themi_home.wall_view import WallView

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.web.kit import Kit

NAME = "wall"
CODE_TTL = timedelta(minutes=10)
MISSES_ALLOWED = 5
LOCKED_FOR = timedelta(minutes=10)
WALL_COOKIE = "themi_wall"
COOKIE_AGE = timedelta(days=400)  # the longest a browser keeps a cookie
DEFAULT_NAME = "Wall"
PARTS = ("top", "note", "today", "columns", "week", "smalls")  # refreshed on their own
TAP = "wall_tap"  # WL4: the category and executor of a tick on the wall
WHERE = "on the wall"  # as praise says it ("Ticked off on the wall: ...")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class WallDevice:
    id: int
    name: str
    csrf_token: str
    paired_at: datetime
    last_seen_at: datetime


class WallDevices:
    """The household's paired frames and the codes that pair them."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ----- pairing ---------------------------------------------------------------------

    def new_code(self, admin: Member) -> str:
        """A fresh 6-digit code; any earlier code still open stops working."""
        now = clock.now()
        code = f"{secrets.randbelow(10**6):06d}"
        with self.db.transaction():
            self.db.execute(
                "UPDATE wall_pairing_codes SET used_at = ? WHERE used_at IS NULL",
                (to_utc_iso(now),),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO wall_pairing_codes "
                "(code_hash, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_hash(code), admin.id, to_utc_iso(now), to_utc_iso(now + CODE_TTL)),
            )
        return code

    def locked(self) -> bool:
        since = to_utc_iso(clock.now() - LOCKED_FOR)
        misses = self.db.scalar("SELECT COUNT(*) FROM wall_pairing_misses WHERE at > ?", (since,))
        return int(misses or 0) >= MISSES_ALLOWED

    def pair(self, code: str, name: str = "") -> str | None:
        """The new frame's token, or None for a wrong, used or expired code (or while
        pairing is locked)."""
        if self.locked():
            return None
        now = clock.now()
        cleaned = "".join(ch for ch in code if ch.isdigit())
        with self.db.transaction():
            row = self.db.one(
                "SELECT code_hash, created_by, expires_at FROM wall_pairing_codes "
                "WHERE code_hash = ? AND used_at IS NULL",
                (_hash(cleaned),),
            )
            if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
                self.db.execute(
                    "INSERT INTO wall_pairing_misses (at) VALUES (?)", (to_utc_iso(now),)
                )
                return None
            self.db.execute(
                "UPDATE wall_pairing_codes SET used_at = ? WHERE code_hash = ?",
                (to_utc_iso(now), row["code_hash"]),
            )
            self.db.execute("DELETE FROM wall_pairing_misses")
            token = secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO wall_devices (name, token_hash, csrf_token, paired_by, paired_at, "
                "last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    name.strip()[:60] or DEFAULT_NAME,
                    _hash(token),
                    secrets.token_urlsafe(24),
                    row["created_by"],
                    to_utc_iso(now),
                    to_utc_iso(now),
                ),
            )
        return token

    # ----- frames ------------------------------------------------------------------------

    def device(self, token: str | None) -> WallDevice | None:
        """The frame this cookie belongs to, marked as seen now; None when it's unknown or
        revoked."""
        if not token:
            return None
        row = self.db.one(
            "SELECT * FROM wall_devices WHERE token_hash = ? AND revoked_at IS NULL",
            (_hash(token),),
        )
        if row is None:
            return None
        now = clock.now()
        self.db.execute(
            "UPDATE wall_devices SET last_seen_at = ? WHERE id = ?", (to_utc_iso(now), row["id"])
        )
        return _device({**row, "last_seen_at": to_utc_iso(now)})

    def all(self) -> list[WallDevice]:
        rows = self.db.query(
            "SELECT * FROM wall_devices WHERE revoked_at IS NULL ORDER BY paired_at"
        )
        return [_device(row) for row in rows]

    def revoke(self, device_id: int) -> bool:
        return (
            self.db.update(
                "UPDATE wall_devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (to_utc_iso(clock.now()), device_id),
            )
            > 0
        )

    @staticmethod
    def csrf_ok(device: WallDevice, submitted: str | None) -> bool:
        return bool(submitted) and hmac.compare_digest(device.csrf_token, submitted or "")


def _device(row: dict) -> WallDevice:
    return WallDevice(
        row["id"],
        row["name"],
        row["csrf_token"],
        datetime.fromisoformat(row["paired_at"]),
        datetime.fromisoformat(row["last_seen_at"]),
    )


# ----- WL4: ticking things off ------------------------------------------------------------


class WallTaps:
    """A tap's change, run by the trust tiers (`wall_tap`, automatic: the person's own
    decision), as the person it was for. Payload: the item's key, who, and ticked or not."""

    def __init__(self, services: Services) -> None:
        self.services = services

    async def execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        key, done = str(payload["key"]), bool(payload["done"])
        by = self.services.store.get_member(int(payload["by"]))
        kind, _, rest = key.partition("-")
        if kind == "task":
            board = self.services.get(keys.taskboard)
            if done:
                return await board.complete(int(rest), by, ticked_on=WHERE)
            task = await board.reopen(int(rest))
            return f"{task.title} is open again."
        if kind == "step":
            routines = self.services.get(keys.routines)
            item_id, _, day = rest.partition("-")
            item = routines.item(int(item_id))
            if item is None:
                return "That step isn't in the routine any more."
            if done:
                routines.tick(item, date.fromisoformat(day))
                return f"Ticked {item.title}."
            routines.untick(item, date.fromisoformat(day))
            return f"Unticked {item.title}."
        raise ValueError(f"not something on the wall: {key}")


# ----- the website ---------------------------------------------------------------------


def routes(kit: Kit) -> APIRouter:
    from themi.web.kit import NotSignedIn

    router = APIRouter()
    devices: WallDevices = kit.app.services.get(WallDevices)

    def frame(request: Request) -> WallDevice | None:
        return devices.device(request.cookies.get(WALL_COOKIE))

    def pair_page(request: Request, status: int = 200, error: str = "") -> HTMLResponse:
        return kit.page(request, "wall/pair.html", status, error=error)

    def viewer(request: Request) -> str | None:
        """The CSRF token of whoever is looking (a paired frame, or a member signed in on
        their phone), or None when nobody is."""
        device = frame(request)
        if device is not None:
            return device.csrf_token
        try:
            return kit.current(request).csrf_token
        except NotSignedIn:
            return None

    def gone() -> Response:
        """A part asked for by a frame that's been signed out: back to pairing."""
        return Response(status_code=401, headers={"HX-Redirect": "/wall/pair"})

    @router.get("/wall", response_class=HTMLResponse)
    def wall(request: Request) -> Response:
        csrf = viewer(request)
        if csrf is None:
            return RedirectResponse("/wall/pair", status_code=303)
        screen = WallView(kit.app.services).screen()
        return kit.page(request, "wall/home.html", screen=screen, csrf=csrf)

    @router.get("/wall/part/{part}", response_class=HTMLResponse)
    def wall_part(request: Request, part: str) -> Response:
        """One part of the screen, for the page's poll (WL2)."""
        if part not in PARTS:
            return Response(status_code=404)
        if viewer(request) is None:
            return gone()
        screen = WallView(kit.app.services).screen()
        return kit.page(request, f"wall/_{part}.html", screen=screen)

    @router.post("/wall/tap", response_class=HTMLResponse)
    async def tap(request: Request) -> Response:
        """WL4: tick or untick something showing on the wall. A Together item asks who did
        it first. Answers with the columns, already changed."""
        csrf = viewer(request)
        if csrf is None:
            return gone()
        form = await request.form()
        submitted = str(form.get("csrf") or request.headers.get("X-CSRF-Token") or "")
        if not submitted or not hmac.compare_digest(csrf, submitted):
            raise PermissionError("missing or wrong CSRF token")
        view = WallView(kit.app.services)
        key = str(form.get("key", ""))
        found = view.find(key) if not form.get("cancel") else None
        if found is None or not found[1].tappable:
            return columns(request, view)
        column, item = found
        people = {m.id: m for m in view.people()}
        if column.member_id is not None:
            by = people.get(column.member_id)
        elif item.done:  # unticking a shared one: whoever ticked it doesn't matter
            by = next(iter(people.values()), None)
        else:
            raw = str(form.get("by", ""))
            by = people.get(int(raw)) if raw.isdigit() else None
            if by is None:
                return columns(request, view, ask=key)
        if by is None:
            return columns(request, view)
        summary = f"{'Untick' if item.done else 'Tick off'} {item.title} {WHERE}"
        payload = {"key": key, "by": by.id, "done": not item.done}
        await kit.app.services.autonomy.stage(TAP, by, summary, payload, TAP, requested=True)
        return columns(request, view)

    def columns(request: Request, view: WallView, ask: str = "") -> HTMLResponse:
        return kit.page(request, "wall/_columns.html", screen=view.screen(ask))

    @router.get("/wall/pair", response_class=HTMLResponse)
    def pair_form(request: Request) -> Response:
        if frame(request) is not None:
            return RedirectResponse("/wall", status_code=303)
        return pair_page(request)

    @router.post("/wall/pair")
    async def pair(request: Request) -> Response:
        if devices.locked():
            return pair_page(
                request, 429, "Too many wrong codes. Wait ten minutes, then ask for a new one."
            )
        form = await request.form()
        token = devices.pair(str(form.get("code", "")), str(form.get("name", "")))
        if token is None:
            return pair_page(
                request,
                400,
                "That code didn't work. Codes last ten minutes and work once: "
                "ask for a new one on the Wall frames page.",
            )
        response = RedirectResponse("/wall", status_code=303)
        response.set_cookie(
            WALL_COOKIE,
            token,
            max_age=int(COOKIE_AGE.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=kit.ctx.secure_cookies,
        )
        return response

    @router.get("/wall/frames", response_class=HTMLResponse)
    def frames(request: Request) -> HTMLResponse:
        session = kit.admin(request)
        return kit.with_flash(request, "wall/frames.html", session, frames=devices.all())

    @router.post("/wall/frames/code", response_class=HTMLResponse)
    async def new_code(request: Request) -> HTMLResponse:
        session, _ = await kit.checked(request, admin=True)
        code = devices.new_code(session.member)
        return kit.with_flash(
            request,
            "wall/frames.html",
            session,
            frames=devices.all(),
            code=f"{code[:3]} {code[3:]}",
            minutes=int(CODE_TTL.total_seconds() // 60),
        )

    @router.post("/wall/frames/{device_id:int}/revoke")
    async def revoke(request: Request, device_id: int) -> Response:
        await kit.checked(request, admin=True)
        done = devices.revoke(device_id)
        return kit.redirect(
            "/wall/frames", "Signed that frame out." if done else "That frame was already gone."
        )

    return router


class WallModule(Module):
    """WL1: the wall page for the Cozyla frame, and the frame's own sign-in."""

    name = NAME
    title = "Wall"
    group = YOUR_DAY
    summary = (
        "A page for the frame on the wall: today's timeline, each of you and what you share, "
        "and the week ahead."
    )
    cost = "Free"
    migrations = Path(__file__).parent / "wall_schema"
    website = "Pair the frame on Wall frames (/wall/frames), then open /wall/pair on it."

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(WallDevices(ctx.services.store.db))
        ctx.executor(TAP, WallTaps(ctx.services).execute)
        ctx.web(
            routes,
            MenuEntry(
                "/wall/frames",
                "Wall frames",
                "Pair the frame on the wall, or sign one out",
                "Admin",
                20,
                admin_only=True,
            ),
        )
