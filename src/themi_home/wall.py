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
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.core import keys
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.modules.groups import YOUR_DAY
from themi.modules.web import MenuEntry
from themi.storage.db import Database
from themi_home.wall_calendars import WallCalendars
from themi_home.wall_columns import TONES, BadLayout, WallColumns, moved
from themi_home.wall_view import THEME_COLOR, WallItem, WallSettings, WallView
from themi_home.wall_views import (
    WallViews,
    _recipe,
    dish_view,
    dishes_view,
    list_view,
    note_view,
)

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
PARTS = ("top", "note", "today", "columns", "week", "smalls", "night")  # refreshed on their own
TAP = "wall_tap"  # WL4: the category and executor of a tick on the wall
WHERE = "on the wall"  # as praise says it ("Ticked off on the wall: ...")
CLOSE_AFTER = 120  # WL5a: seconds without a touch before a view closes itself
LATER_TONIGHT = 21  # WL5b: "Later tonight" brings the note back at 9 pm
QUIET_ALERT_HOURS = 12  # an alert's "Got it": quiet for the rest of it, or this long
OP_WORDS = {"tomorrow": "tomorrow", "nextweek": "next week", "family": "a family to-do"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class WallDevice:
    id: int
    name: str
    csrf_token: str
    paired_at: datetime
    last_seen_at: datetime
    display: str | None = None


# F52a: how a frame's page says it's shown (the Themi-Wall-Display header), and what Wall
# frames says about it.
DISPLAY_HEADER = "Themi-Wall-Display"
DISPLAYS = {
    "fullscreen": "Full screen app",
    "fullscreen-api": "Full screen after a touch",
    "standalone": "In its own window, with Android's bars",
    "browser": "In a Chrome tab: see the guide",
}


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

    def device(self, token: str | None, display: str | None = None) -> WallDevice | None:
        """The frame this cookie belongs to, marked as seen now; None when it's unknown or
        revoked. A known `display` (F52a) is kept with it; anything else leaves it be."""
        if not token:
            return None
        row = self.db.one(
            "SELECT * FROM wall_devices WHERE token_hash = ? AND revoked_at IS NULL",
            (_hash(token),),
        )
        if row is None:
            return None
        now = clock.now()
        shown = display if display in DISPLAYS else row["display"]
        self.db.execute(
            "UPDATE wall_devices SET last_seen_at = ?, display = ? WHERE id = ?",
            (to_utc_iso(now), shown, row["id"]),
        )
        return _device({**row, "last_seen_at": to_utc_iso(now), "display": shown})

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
        row["display"],
    )


# ----- WL4: ticking things off ------------------------------------------------------------


class WallTaps:
    """A tap's change, run by the trust tiers (`wall_tap`, automatic: the person's own
    decision), as the person it was for. Payload: the item's key, who, and ticked or not."""

    def __init__(self, services: Services) -> None:
        self.services = services

    async def execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        by = self.services.store.get_member(int(payload["by"]))
        if "op" in payload:  # WL5b: a change made in a List view
            return await self._change(payload, by)
        key, done = str(payload["key"]), bool(payload["done"])
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

    async def _change(self, payload: dict[str, Any], by: Member) -> str:
        """Tomorrow, Next week, Give to, Make it a family to-do, Change the words, Add, and
        (on the grocery list) Bought."""
        op, text = str(payload["op"]), str(payload.get("text", "")).strip()
        if op == "bought":
            groceries = self.services.get(keys.groceries)
            groceries.finish(text, "bought")
            return f"{text} is off the grocery list."
        board = self.services.get(keys.taskboard)
        if op == "add":
            owner = payload.get("owner")
            doer = self.services.store.get_member(int(owner)) if owner else by
            task = await board.create(by, text, "errand", 1, assignee=doer)
            if not owner:  # the family list
                await board.reassign(task.id, None, shared=True)
            return f"Added {task.title}."
        task_id = int(payload["task"])
        today = clock.now().astimezone(self._tz()).date()
        if op == "tomorrow":
            return await board.reschedule(task_id, today + timedelta(days=1))
        if op == "nextweek":
            return await board.reschedule(task_id, today + timedelta(days=7))
        if op == "give":
            to = self.services.store.get_member(int(payload["to"]))
            task = await board.reassign(task_id, to)
            return f"{task.title} is {to.name}'s now."
        if op == "family":
            task = await board.reassign(task_id, None, shared=True)
            return f"{task.title} is on the family list now."
        if op == "words":
            task = await board.update(task_id, by, title=text)
            return f"It reads {task.title} now."
        raise ValueError(f"not a change the wall makes: {op}")

    def _tz(self) -> ZoneInfo:
        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


# ----- the website ---------------------------------------------------------------------


def _day(value: str) -> date:
    """A day from a view's address; today's date for nonsense (the view then shows nothing
    it shouldn't, since each looks the day up itself)."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return clock.now().date()


def routes(kit: Kit) -> APIRouter:
    from themi.web.kit import NotSignedIn

    router = APIRouter()
    devices: WallDevices = kit.app.services.get(WallDevices)

    def frame(request: Request) -> WallDevice | None:
        return devices.device(request.cookies.get(WALL_COOKIE), request.headers.get(DISPLAY_HEADER))

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
        return kit.page(
            request, "wall/home.html", screen=screen, csrf=csrf, theme_color=THEME_COLOR
        )

    @router.get("/wall/part/{part}", response_class=HTMLResponse)
    def wall_part(request: Request, part: str) -> Response:
        """One part of the screen, for the page's poll (WL2)."""
        if part not in PARTS:
            return Response(status_code=404)
        if viewer(request) is None:
            return gone()
        screen = WallView(kit.app.services).screen()
        return kit.page(request, f"wall/_{part}.html", screen=screen)

    async def posted(request: Request) -> dict[str, str] | None:
        """A POST's form after its CSRF check (the frame's token or a member's session's);
        None when nobody is looking any more."""
        csrf = viewer(request)
        if csrf is None:
            return None
        form = {k: str(v) for k, v in (await request.form()).items()}
        submitted = form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
        if not submitted or not hmac.compare_digest(csrf, submitted):
            raise PermissionError("missing or wrong CSRF token")
        return form

    @router.post("/wall/tap", response_class=HTMLResponse)
    async def tap(request: Request) -> Response:
        """WL4: tick or untick something showing on the wall. A Together item asks who did
        it first. Answers with the columns, already changed; a tap in a Person view (WL5a,
        `view=person/<id>`, with its unfolded routine as `open`) or the Together view (WL9d,
        `view=together`) answers with that view and has the columns refresh."""
        form = await posted(request)
        if form is None:
            return gone()
        view = WallView(kit.app.services)
        key = form.get("key", "")
        whose = form.get("view", "").removeprefix("person/")
        if whose.isdigit():
            item = WallViews(view).find(int(whose), key)
            by = next((m for m in view.people() if m.id == int(whose)), None)
            if item is not None and item.tappable and by is not None:
                await stage(by, key, item)
            opened = form.get("open", "")
            response = person_view(
                request, view, int(whose), int(opened) if opened.isdigit() else 0
            )
            response.headers["HX-Trigger"] = "wall-refresh"
            return response
        if whose == "together":
            return await together_tap(request, view, form)
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
            raw = form.get("by", "")
            by = people.get(int(raw)) if raw.isdigit() else None
            if by is None:
                return columns(request, view, ask=key)
        if by is not None:
            await stage(by, key, item)
        return columns(request, view)

    async def together_tap(request: Request, view: WallView, form: dict[str, str]) -> Response:
        """WL9d: a tap on the Together page. An open one asks who did it (as the column does);
        a done one is unticked."""
        key = form.get("key", "")
        item = WallViews(view).find_together(key) if not form.get("cancel") else None
        people = {m.id: m for m in view.people()}
        asking = ""
        if item is not None and item.tappable:
            raw = form.get("by", "")
            by = (
                next(iter(people.values()), None)
                if item.done
                else people.get(int(raw))
                if raw.isdigit()
                else None
            )
            if by is None and not item.done:
                asking = key
            elif by is not None:
                await stage(by, key, item)
        response = together_page(request, view, asking)
        response.headers["HX-Trigger"] = "wall-refresh"
        return response

    def together_page(request: Request, view: WallView, asking: str = "") -> HTMLResponse:
        found = WallViews(view).together(asking)
        return sheet(request, "_view_together.html", view=found)

    async def stage(by: Member, key: str, item: WallItem) -> None:
        summary = f"{'Untick' if item.done else 'Tick off'} {item.title} {WHERE}"
        payload = {"key": key, "by": by.id, "done": not item.done}
        await kit.app.services.autonomy.stage(TAP, by, summary, payload, TAP, requested=True)

    def columns(request: Request, view: WallView, ask: str = "") -> HTMLResponse:
        return kit.page(request, "wall/_columns.html", screen=view.screen(ask))

    @router.post("/wall/week/calendar", response_class=HTMLResponse)
    async def week_calendar(request: Request) -> Response:
        """F55f (idea #239): a calendar's chip turns it off in the week ahead, or on again.
        Answers with the week, already changed."""
        form = await posted(request)
        if form is None:
            return gone()
        view = WallView(kit.app.services)
        key = form.get("calendar", "")
        if key in {c.key for c in view.week_calendars()}:
            WallCalendars(kit.app.services.store.db).toggle(key)
            view = WallView(kit.app.services)
        return kit.page(request, "wall/_week.html", screen=view.screen())

    # ----- WL5a: the views -------------------------------------------------------------

    def sheet(request: Request, template: str, **values: Any) -> HTMLResponse:
        return kit.page(request, f"wall/{template}", close_after=CLOSE_AFTER, **values)

    def person_view(
        request: Request, view: WallView, member_id: int, opened: int = 0
    ) -> HTMLResponse:
        found = WallViews(view).person(member_id, opened)
        if found is None:
            return HTMLResponse("")
        return sheet(request, "_view_person.html", person=found)

    @router.get("/wall/view/event", response_class=HTMLResponse)
    def event_view(
        request: Request, day: str = "", m: int = 0, c: str = "", e: str = ""
    ) -> Response:
        if viewer(request) is None:
            return gone()
        found = WallViews(WallView(kit.app.services)).event(_day(day), m, c, e)
        return sheet(request, "_view_event.html", event=found) if found else HTMLResponse("")

    @router.post("/wall/view/event/send", response_class=HTMLResponse)
    async def send_event(request: Request) -> Response:
        form = await posted(request)
        if form is None:
            return gone()
        views = WallViews(WallView(kit.app.services))
        query = request.query_params  # the event, as its view's address names it
        day = _day(query.get("day", ""))
        m = int(query["m"]) if query.get("m", "").isdigit() else 0
        found = views.event(day, m, query.get("c", ""), query.get("e", ""))
        to = next(
            (p for p, _ in (found.send_to if found else ()) if str(p) == form.get("to")), None
        )
        if found is None or to is None:
            return HTMLResponse("")
        sent = await views.send_event(found, day, kit.app.store.get_member(to))
        return sheet(request, "_view_event.html", event=replace(found, sent=sent))

    @router.get("/wall/view/day/{day}", response_class=HTMLResponse)
    def day_view(request: Request, day: str) -> Response:
        if viewer(request) is None:
            return gone()
        found = WallViews(WallView(kit.app.services)).day(_day(day))
        return sheet(request, "_view_day.html", view=found) if found else HTMLResponse("")

    @router.get("/wall/view/weather", response_class=HTMLResponse)
    def weather_view(request: Request) -> Response:
        if viewer(request) is None:
            return gone()
        found = WallViews(WallView(kit.app.services)).weather()
        return sheet(request, "_view_weather.html", view=found) if found else HTMLResponse("")

    @router.get("/wall/view/person/{member_id:int}", response_class=HTMLResponse)
    def person(request: Request, member_id: int, open: int = 0) -> Response:
        if viewer(request) is None:
            return gone()
        return person_view(request, WallView(kit.app.services), member_id, open)

    @router.get("/wall/view/together", response_class=HTMLResponse)
    def together(request: Request) -> Response:
        if viewer(request) is None:
            return gone()
        return together_page(request, WallView(kit.app.services))

    # ----- WL6: an app on the frame ----------------------------------------------------

    @router.get("/wall/manifest.webmanifest")
    def manifest() -> JSONResponse:
        """Added to the frame's home screen, /wall opens as its own app: full screen,
        portrait, no browser bars. Nothing private in it."""
        from themi.web.kit import asset

        def icon(name: str, size: int) -> dict[str, str]:
            return {
                "src": asset(f"home/icons/{name}", kit.static_folders),
                "sizes": f"{size}x{size}",
                "type": "image/png",
                "purpose": "any maskable",
            }

        return JSONResponse(
            {
                "name": "Themi Wall",
                "short_name": "Wall",
                "id": "/wall",
                "start_url": "/wall",
                "scope": "/wall",
                "display": "fullscreen",
                "display_override": ["fullscreen", "standalone"],
                "orientation": "portrait",
                "background_color": "#e8ece6",
                "theme_color": "#e8ece6",
                "icons": [icon("icon-192.png", 192), icon("icon-512.png", 512)],
            },
            media_type="application/manifest+json",
        )

    @router.get("/wall/sw.js")
    def service_worker() -> Response:
        """The frame's last good screen, for when Themi can't be reached (WL6)."""
        from themi.web.kit import static_file

        body = static_file("home/wall-sw.js", kit.static_folders).read_text()
        return Response(
            body,
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/wall", "Cache-Control": "no-cache"},
        )

    # ----- WL5b: List, Dish and Note --------------------------------------------------

    def views() -> WallViews:
        return WallViews(WallView(kit.app.services))

    def list_sheet(request: Request, which: str, opened: int = 0, said: str = "") -> Response:
        found = list_view(views(), which, opened, said)
        if found is None:
            return HTMLResponse("")
        response = sheet(request, "_view_list.html", view=found)
        if said:
            response.headers["HX-Trigger"] = "wall-refresh"
        return response

    @router.get("/wall/view/list/{which:path}", response_class=HTMLResponse)
    def list_page(request: Request, which: str, open: int = 0) -> Response:
        if viewer(request) is None:
            return gone()
        return list_sheet(request, which, open)

    @router.post("/wall/view/list/{which:path}", response_class=HTMLResponse)
    async def list_change(request: Request, which: str) -> Response:
        form = await posted(request)
        if form is None:
            return gone()
        found = list_view(views(), which)
        if found is None:
            return HTMLResponse("")
        op, text = form.get("op", ""), form.get("text", "").strip()[:200]
        people = {m.id: m for m in WallView(kit.app.services).people()}
        row = next((r for r in found.rows if str(r.id) == form.get("id")), None)
        whose = which.removeprefix("todo/")
        owner = people.get(int(whose)) if whose.isdigit() else None
        by = owner or next(iter(people.values()), None)
        if by is None:
            return HTMLResponse("")
        payload: dict[str, Any] = {"op": op, "by": by.id}
        if op == "add" and text:
            if found.groceries:  # the grocery list's own way in, through its own category
                outcome = await stage_groceries(by, [text])
                return list_sheet(request, which, said=outcome)
            payload.update(text=text, owner=owner.id if owner else None)
            summary = f"Add {text} to {found.title} {WHERE}"
        elif row is None:
            return list_sheet(request, which)
        elif op == "bought" and found.groceries:
            payload["text"] = row.title.lower()
            summary = f"{row.title} bought, {WHERE}"
        elif op in ("tomorrow", "nextweek", "family") and not found.groceries:
            payload["task"] = row.id
            summary = f"{row.title}: {OP_WORDS[op]} {WHERE}"
        elif op == "give" and form.get("to", "").isdigit() and int(form["to"]) in people:
            payload.update(task=row.id, to=int(form["to"]))
            summary = f"Give {row.title} to {people[int(form['to'])].name} {WHERE}"
        elif op == "words" and text and not found.groceries:
            payload.update(task=row.id, text=text)
            summary = f"Reword {row.title} as {text} {WHERE}"
        else:
            return list_sheet(request, which, row.id)
        outcome = await kit.app.services.autonomy.stage(
            TAP, by, summary, payload, TAP, requested=True
        )
        return list_sheet(request, which, said=outcome.message)

    async def stage_groceries(by: Member, names: list[str]) -> str:
        from themi_home.groceries import CATEGORY, EXECUTOR, list_summary

        outcome = await kit.app.services.autonomy.stage(
            CATEGORY, by, list_summary(names), {"items": names}, EXECUTOR, requested=True
        )
        return outcome.message

    def dishes(request: Request, item_id: int = 0, said: str = "") -> HTMLResponse:
        """WL9b: Things to cook, with `item_id` unfolded (its ingredients, Start cooking)."""
        found = dishes_view(views(), item_id, said)
        return sheet(request, "_view_dishes.html", view=found) if found else HTMLResponse("")

    @router.get("/wall/view/dishes", response_class=HTMLResponse)
    def dishes_page(request: Request) -> Response:
        if viewer(request) is None:
            return gone()
        return dishes(request)

    @router.get("/wall/view/dish/{item_id:int}", response_class=HTMLResponse)
    def dish_page(request: Request, item_id: int) -> Response:
        if viewer(request) is None:
            return gone()
        return dishes(request, item_id)

    @router.post("/wall/view/dish/{item_id:int}/add", response_class=HTMLResponse)
    async def dish_add(request: Request, item_id: int) -> Response:
        """Add the rest to Groceries: the ingredients not ticked as in the house, and not
        already on the list, once each, through the grocery list's own category."""
        if await posted(request) is None:
            return gone()
        found = dish_view(views(), item_id)
        if found is None:
            return HTMLResponse("")
        have = set((await request.form()).getlist("have"))
        groceries = kit.app.services.maybe(keys.groceries)
        rest = [
            name
            for name in found.ingredients
            if name not in have and (groceries is None or not groceries.is_needed(name))
        ]
        people = WallView(kit.app.services).people()
        said = "Everything's in the house or on the list already."
        if rest and people:
            said = await stage_groceries(people[0], rest)
        return dishes(request, item_id, said)

    @router.post("/wall/view/dish/{item_id:int}/cook", response_class=HTMLResponse)
    async def dish_cook(request: Request, item_id: int) -> Response:
        """Start cooking: a cooking session for whoever's cooking. Its cook screen opens on
        their phone (the frame isn't anyone's own sign-in)."""
        form = await posted(request)
        if form is None:
            return gone()
        found = dish_view(views(), item_id)
        cooking = kit.app.services.maybe(keys.cooking)
        people = {m.id: m for m in WallView(kit.app.services).people()}
        cook = people.get(int(form.get("by", "0") or 0))
        recipe = _recipe(views(), found.name) if found else None
        if found is None or cooking is None or cook is None or recipe is None:
            return HTMLResponse("")
        await cooking.start(cook, recipe)
        said = f"Started {recipe.name}. The cook screen is on {cook.name}'s phone."
        return dishes(request, item_id, said)

    @router.get("/wall/view/note", response_class=HTMLResponse)
    def note_page(request: Request) -> Response:
        if viewer(request) is None:
            return gone()
        found = note_view(views())
        return sheet(request, "_view_note.html", view=found) if found else HTMLResponse("")

    @router.post("/wall/view/note", response_class=HTMLResponse)
    async def note_answer(request: Request) -> Response:
        """They're in (asks who; Both of us), Later tonight (back at 9 pm), In the morning
        (off the wall until then: the morning message has it), Got it (an alert)."""
        form = await posted(request)
        if form is None:
            return gone()
        view = WallView(kit.app.services)
        note = view.note()
        found = note_view(views())
        if note is None or found is None:
            return HTMLResponse("")
        answer = form.get("answer", "")
        now = view.now()
        people = {m.id: m for m in view.people()}
        if answer == "done" and note.task_id is not None:
            if note.both and not form.get("by"):
                return sheet(request, "_view_note.html", view=replace(found, asking=True))
            raw = form.get("by", "")
            by = (
                next(iter(people.values()), None)
                if raw == "both"
                else people.get(int(raw))
                if raw.isdigit()
                else people.get(note.assignee or 0)
            )
            if by is None:
                return sheet(request, "_view_note.html", view=found)
            await stage(by, note.key, WallItem(note.key, note.text.split(" is still")[0]))
            said = "Thank you, both." if raw == "both" else f"Thank you, {by.name}."
        elif answer == "later":
            later = now.replace(hour=LATER_TONIGHT, minute=0, second=0, microsecond=0)
            view.quiet(note.key, later if later > now else now + timedelta(hours=1))
            said = f"I'll leave it for now. The note comes back around {LATER_TONIGHT - 12} pm."
        elif answer == "morning":
            morning = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            view.quiet(note.key, morning)
            said = "Morning it is. It'll be in the morning message, not on the wall tonight."
        elif answer == "ok":
            view.quiet(note.key, now + timedelta(hours=QUIET_ALERT_HOURS))
            said = "Got it."
        else:
            return sheet(request, "_view_note.html", view=found)
        response = sheet(request, "_view_note.html", view=replace(found, said=said))
        response.headers["HX-Trigger"] = "wall-refresh"
        return response

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

    def wall_columns() -> WallColumns:
        return WallColumns(kit.app.services.store.db)

    def frames_page(request: Request, session: Any, **values: Any) -> HTMLResponse:
        members = kit.app.services.store.list_members()
        return kit.with_flash(
            request,
            "wall/frames.html",
            session,
            frames=devices.all(),
            displays=DISPLAYS,
            columns=wall_columns().layout(members),
            chosen=bool(wall_columns().chosen()),
            calendars=list(WallCalendars(kit.app.services.store.db).known(members).values()),
            hidden_calendars=WallCalendars(kit.app.services.store.db).hidden(),
            tones=TONES,
            **values,
        )

    @router.get("/wall/frames", response_class=HTMLResponse)
    def frames(request: Request) -> HTMLResponse:
        return frames_page(request, kit.admin(request))

    @router.post("/wall/frames/code", response_class=HTMLResponse)
    async def new_code(request: Request) -> HTMLResponse:
        session, _ = await kit.checked(request, admin=True)
        code = devices.new_code(session.member)
        return frames_page(
            request,
            session,
            code=f"{code[:3]} {code[3:]}",
            minutes=int(CODE_TTL.total_seconds() // 60),
        )

    @router.post("/wall/frames/columns")
    async def save_columns(request: Request) -> Response:
        """F53: People on the wall. Save keeps the colours; Up or Down moves a column (and
        keeps the colours on the form too); Put them back goes back to the defaults."""
        session, form = await kit.checked(request, admin=True)
        back = "/wall/frames#columns"
        if form.get("reset"):
            wall_columns().reset()
            return kit.redirect(back, "The wall's columns are back as they were.")
        members = kit.app.services.store.list_members()
        order = [k for k in str(form.get("order", "")).split(",") if k]
        tones = {k: str(form[f"tone_{k}"]) for k in order if f"tone_{k}" in form}
        said = "Saved the colours."
        move = str(form.get("move", ""))
        key, _, way = move.rpartition(":")
        if key and way in ("up", "down"):
            order = moved(order, key, -1 if way == "up" else 1)
            said = "Moved."
        try:
            wall_columns().save(session.member, members, order, tones)
        except BadLayout as exc:
            return kit.redirect(back, f"{exc} Nothing changed.")
        return kit.redirect(back, f"{said} The wall shows it at its next refresh.")

    @router.post("/wall/frames/calendars")
    async def save_calendars(request: Request) -> Response:
        """F55f: the calendars shown in the week ahead; the ones not ticked are off there."""
        session, _ = await kit.checked(request, admin=True)
        shown = {str(v) for v in (await request.form()).getlist("shown")}
        members = kit.app.services.store.list_members()
        calendars = WallCalendars(kit.app.services.store.db)
        calendars.save((k for k in calendars.known(members) if k not in shown), session.member)
        return kit.redirect(
            "/wall/frames#calendars", "Saved. The wall shows it at its next refresh."
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
    household = WallSettings  # WL6: when the wall goes quiet for the night
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
