"""The home pack's rows on the Accounts page (CR17a), one per module: Home Connect, LG
ThinQ (with the laundry settings), Roborock, Tuya and CatGenie under "Household
connections" (admins only, both the rows and their routes), and each person's own Spotify.

Each module adds its row with `ctx.accounts_section(template, order, values=, routes=)`.
The routes keep their old /family/... addresses (bookmarks, and the Home Connect callback
registered with Home Connect), and each lands back on /accounts with its row open.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from themi.accounts import AccountsError, Member
from themi.core import keys
from themi.web.accounts_page import back, household_models, render
from themi.web.kit import Kit
from themi_home.connectors.catgenie import CatGenieError
from themi_home.connectors.homeconnect import HomeConnectAccount, HomeConnectError
from themi_home.connectors.roborock import RoborockError
from themi_home.connectors.spotify import SpotifyError, SpotifyLinks
from themi_home.connectors.thinq import ThinqError
from themi_home.connectors.tuya import REGIONS, TuyaError

Values = Callable[[Member], dict[str, Any]]


def row_values(services: Any, name: str) -> Values:
    """A household row's values: what `<name>.html` reads as `household.<name>`."""
    read = ROWS[name]
    return lambda _member: {name: read(services)}


def spotify_values(services: Any) -> Values:
    """BD5b: their own Spotify link."""
    return lambda member: {"spotify": {"link": services.get(keys.music).links.link(member)}}


def _home_connect(services: Any) -> dict[str, Any] | None:
    account, dishwasher = services.maybe(keys.home_connect), services.maybe(keys.dishwasher)
    if account is None or dishwasher is None:
        return None
    states = {
        r["device_id"]: r["state"] for r in services.store.db.query("SELECT * FROM device_states")
    }
    return {
        "linked": account.linked(),
        "devices": [(d, states.get(d.id)) for d in dishwasher.devices()],
    }


def _thinq(services: Any) -> dict[str, Any] | None:
    watcher = services.maybe(keys.thinq)
    if watcher is None:
        return None
    states = watcher.states()
    return {
        "linked": watcher.account.linked(),
        "country": watcher.account.country() or "US",
        "pushes": watcher.push.connected(),
        "devices": [(d, states.get(d.id)) for d in watcher.devices()],
    }


def _roborock(services: Any) -> dict[str, Any] | None:
    watcher = services.maybe(keys.roborock)
    if watcher is None:
        return None
    states = watcher.states()
    return {
        "linked": watcher.account.linked(),
        "email": watcher.account.email() or "",
        "problem": watcher.account.problem(),
        "devices": [(d, states.get(d.id)) for d in watcher.devices()],
    }


def _tuya(services: Any) -> dict[str, Any] | None:
    watcher = services.maybe(keys.tuya)
    if watcher is None:
        return None
    states = watcher.states()
    return {
        "linked": watcher.account.linked(),
        "access_id": watcher.account.access_id() or "",
        "region": watcher.account.region() or "us",
        "regions": [(key, name) for key, (name, _) in REGIONS.items()],
        "problem": watcher.account.problem(),
        "devices": [(d, states.get(d.id), watcher.raw(d)) for d in watcher.devices()],
    }


def _catgenie(services: Any) -> dict[str, Any] | None:
    watcher = services.maybe(keys.catgenie)
    if watcher is None:
        return None
    states = watcher.states()
    chores = services.maybe(keys.litter_box)
    return {
        "linked": watcher.account.linked(),
        "problem": watcher.account.problem(),
        "devices": [
            (d, states.get(d.id), watcher.raw(d), chores.granules(d.id) if chores else None)
            for d in watcher.devices()
        ],
    }


ROWS: dict[str, Callable[[Any], dict[str, Any] | None]] = {
    "home_connect": _home_connect,
    "thinq": _thinq,
    "roborock": _roborock,
    "tuya": _tuya,
    "catgenie": _catgenie,
}


def home_connect_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    store = app.store

    # ----- Home Connect (H1) ----------------------------------------------------------------

    @router.post("/family/home-connect/link")
    async def link_home_connect(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        account = app.services.maybe(keys.home_connect)
        if account is None:
            return kit.redirect(back("home-connect"), "Home Connect isn't set up on this server.")
        redirect = HomeConnectAccount.redirect_uri(kit.ctx.base_url)
        return RedirectResponse(
            account.authorization_url(session.member, redirect), status_code=303
        )

    @router.get("/auth/home-connect/callback")
    async def home_connect_callback(
        request: Request, state: str = "", code: str = "", error: str = ""
    ) -> Response:
        account, dishwasher = (
            app.services.maybe(keys.home_connect),
            app.services.maybe(keys.dishwasher),
        )
        to = back("home-connect")
        if account is None or dishwasher is None:
            return kit.redirect(to, "Home Connect isn't set up on this server.")
        if error or not state or not code:
            return kit.redirect(to, "Home Connect wasn't linked, so nothing changed.")
        try:
            member_id = await account.complete(
                state, code, HomeConnectAccount.redirect_uri(kit.ctx.base_url)
            )
            added = await dishwasher.add_appliances(store.get_member(member_id))
        except (HomeConnectError, AccountsError) as exc:
            return kit.redirect(to, f"Home Connect wasn't linked: {exc}")
        names = ", ".join(d.name for d in added)
        return kit.redirect(
            to, f"Linked Home Connect. Found {names}." if names else "Linked Home Connect."
        )

    @router.post("/family/home-connect/unlink")
    async def unlink_home_connect(request: Request) -> Response:
        await kit.checked(request, admin=True)
        if app.services.maybe(keys.home_connect) is not None:
            app.services.maybe(keys.home_connect).unlink()
        return kit.redirect(
            back("home-connect"),
            "Unlinked Home Connect. Removing Themi in the Home Connect app's settings finishes it.",
        )

    return router


def thinq_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    store = app.store

    # ----- LG ThinQ (30) ----------------------------------------------------------------

    @router.post("/family/thinq/link")
    async def link_thinq(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.thinq)
        to = back("thinq")
        if watcher is None:
            return kit.redirect(to, "LG ThinQ isn't set up on this server.")
        try:
            added = await watcher.link(
                session.member, str(form.get("token", "")), str(form.get("country", ""))
            )
        except (ThinqError, AccountsError) as exc:
            return kit.redirect(to, f"LG ThinQ wasn't linked: {exc}")
        names = ", ".join(d.name for d in added)
        return kit.redirect(to, f"Linked LG ThinQ. Found {names}." if names else "Linked LG ThinQ.")

    @router.post("/family/thinq/unlink")
    async def unlink_thinq(request: Request) -> Response:
        await kit.checked(request, admin=True)
        if app.services.maybe(keys.thinq) is not None:
            await app.services.maybe(keys.thinq).unlink()
        return kit.redirect(
            back("thinq"), "Unlinked LG ThinQ. Deleting the token on LG's site finishes it."
        )

    @router.post("/family/thinq/devices/{device_id}")
    async def map_thinq_device(request: Request, device_id: int) -> Response:
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.thinq)
        to = back("thinq")
        if watcher is None or device_id not in {d.id for d in watcher.devices()}:
            return kit.redirect(to, "That appliance isn't one of LG ThinQ's.")
        appliance = str(form.get("appliance", "")) or None
        if appliance not in (None, "washer", "dryer"):
            return kit.redirect(to, "An LG appliance is the washer, the dryer, or neither.")
        device = store.set_device_appliance(session.member, device_id, appliance)
        return kit.redirect(to, f"{device.name}: {appliance or 'not used'}.")

    @router.post("/family/laundry")
    async def save_laundry(request: Request) -> Response:
        """How long a wet load stays fresh, and how long a rewash takes (31)."""
        session, form = await kit.checked(request, admin=True)
        to = back("thinq")
        try:
            hours = float(str(form.get("fresh_hours", "")))
            minutes = int(str(form.get("rinse_minutes", "")))
        except ValueError:
            return kit.redirect(to, "The fresh hours and rewash minutes are numbers.")
        laundry = household_models(app).get("thinq")
        if laundry is None:
            return kit.redirect(to, "The washer and dryer aren't set up.")
        try:
            store.save_household(
                session.member, laundry, laundry_fresh_hours=hours, laundry_rinse_minutes=minutes
            )
        except AccountsError as exc:
            return kit.redirect(to, f"Not saved: {exc}.")
        return kit.redirect(to, "Laundry settings saved.")

    return router


def roborock_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    # ----- Roborock (V1) ------------------------------------------------------------------

    @router.post("/family/roborock/code")
    async def roborock_code(request: Request) -> Response:
        """The first step: Roborock emails a code to the app account."""
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.roborock)
        to = back("roborock")
        if watcher is None:
            return kit.redirect(to, "The vacuum isn't set up on this server.")
        try:
            email = await watcher.send_code(str(form.get("email", "")))
        except RoborockError as exc:
            return kit.redirect(to, f"No code was sent: {exc}")
        return render(  # the address stays out of the URL
            kit,
            request,
            session,
            f"Roborock emailed a code to {email}.",
            roborock_code_sent=email,
            opened="roborock",
        )

    @router.post("/family/roborock/link")
    async def link_roborock(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.roborock)
        to = back("roborock")
        if watcher is None:
            return kit.redirect(to, "The vacuum isn't set up on this server.")
        try:
            added = await watcher.link(
                session.member, str(form.get("email", "")), str(form.get("code", ""))
            )
        except (RoborockError, AccountsError) as exc:
            return kit.redirect(to, f"Roborock wasn't linked: {exc}")
        names = ", ".join(d.name for d in added)
        return kit.redirect(to, f"Linked Roborock. Found {names}." if names else "Linked Roborock.")

    @router.post("/family/roborock/unlink")
    async def unlink_roborock(request: Request) -> Response:
        await kit.checked(request, admin=True)
        if app.services.maybe(keys.roborock) is not None:
            await app.services.maybe(keys.roborock).unlink()
        return kit.redirect(back("roborock"), "Unlinked Roborock.")

    return router


def tuya_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app
    store = app.store

    # ----- Tuya, for the feeders (32) ---------------------------------------------------

    @router.post("/family/tuya/link")
    async def link_tuya(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.tuya)
        to = back("tuya")
        if watcher is None:
            return kit.redirect(to, "The feeders aren't set up on this server.")
        try:
            added = await watcher.link(
                session.member,
                str(form.get("access_id", "")),
                str(form.get("secret", "")),
                str(form.get("region", "")),
            )
        except (TuyaError, AccountsError) as exc:
            return kit.redirect(to, f"Tuya wasn't linked: {exc}")
        if not watcher.devices():
            return kit.redirect(
                to,
                "Linked Tuya, but it sees no devices yet: link the SmartLife app account to "
                "the cloud project (Devices, Link App Account), then link here again.",
            )
        names = ", ".join(d.name for d in added)
        return kit.redirect(to, f"Linked Tuya. Found {names}." if names else "Linked Tuya.")

    @router.post("/family/tuya/unlink")
    async def unlink_tuya(request: Request) -> Response:
        await kit.checked(request, admin=True)
        if app.services.maybe(keys.tuya) is not None:
            await app.services.maybe(keys.tuya).unlink()
        return kit.redirect(
            back("tuya"), "Unlinked Tuya. Deleting the cloud project on Tuya's site finishes it."
        )

    @router.post("/family/tuya/devices/{device_id}")
    async def map_tuya_device(request: Request, device_id: int) -> Response:
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.tuya)
        to = back("tuya")
        if watcher is None or device_id not in {d.id for d in watcher.devices()}:
            return kit.redirect(to, "That device isn't one of Tuya's.")
        appliance = str(form.get("appliance", "")) or None
        if appliance not in (None, "feeder"):
            return kit.redirect(to, "A Tuya device is a feeder, or not used.")
        device = store.set_device_appliance(session.member, device_id, appliance)
        return kit.redirect(to, f"{device.name}: {appliance or 'not used'}.")

    return router


def catgenie_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    # ----- CatGenie, for the litter box (CG1a) -----------------------------------------

    @router.post("/family/catgenie/code")
    async def catgenie_code(request: Request) -> Response:
        """The first step: PetNovations texts a code to the app account's phone."""
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.catgenie)
        to = back("catgenie")
        if watcher is None:
            return kit.redirect(to, "The litter box isn't set up on this server.")
        try:
            phone = await watcher.send_code(str(form.get("phone", "")))
        except CatGenieError as exc:
            return kit.redirect(to, f"No code was sent: {exc}")
        return render(  # the number stays out of the URL
            kit,
            request,
            session,
            f"PetNovations was asked to text a code to {phone}.",
            catgenie_code_sent=phone,
            opened="catgenie",
        )

    @router.post("/family/catgenie/link")
    async def link_catgenie(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        watcher = app.services.maybe(keys.catgenie)
        to = back("catgenie")
        if watcher is None:
            return kit.redirect(to, "The litter box isn't set up on this server.")
        try:
            added = await watcher.link(
                session.member, str(form.get("phone", "")), str(form.get("code", ""))
            )
        except (CatGenieError, AccountsError) as exc:
            return kit.redirect(to, f"CatGenie wasn't linked: {exc}")
        if not watcher.devices():
            return kit.redirect(to, "Linked CatGenie, but the account has no litter box on it yet.")
        names = ", ".join(d.name for d in added)
        return kit.redirect(to, f"Linked CatGenie. Found {names}." if names else "Linked CatGenie.")

    @router.post("/family/catgenie/granules/{device_id}")
    async def catgenie_granules(request: Request, device_id: int) -> Response:
        """CG1b: every how many cleans the granules want topping up (blank: never asked)."""
        _session, form = await kit.checked(request, admin=True)
        watcher, chores = app.services.maybe(keys.catgenie), app.services.maybe(keys.litter_box)
        to = back("catgenie")
        if watcher is None or chores is None:
            return kit.redirect(to, "The litter box isn't set up on this server.")
        device = next((d for d in watcher.devices() if d.id == device_id), None)
        if device is None:
            return kit.redirect(to, "That isn't one of the litter boxes.")
        every = str(form.get("every", "")).strip()
        if not every:
            chores.set_granules(device.id, None)
            return kit.redirect(to, f"{device.name}: no granule reminders.")
        if not every.isdigit() or int(every) <= 0:
            return kit.redirect(to, "Not saved: the number of cleans must be a whole number.")
        chores.set_granules(device.id, int(every))
        return kit.redirect(
            to, f"{device.name}: a granule top-up every {int(every)} cleans, counted from now."
        )

    @router.post("/family/catgenie/unlink")
    async def unlink_catgenie(request: Request) -> Response:
        await kit.checked(request, admin=True)
        if app.services.maybe(keys.catgenie) is not None:
            await app.services.maybe(keys.catgenie).unlink()
        return kit.redirect(back("catgenie"), "Unlinked CatGenie.")

    return router


def spotify_routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    # ----- Spotify (BD5b): each person's own --------------------------------------------------

    @router.post("/accounts/spotify/link")
    async def link_spotify(request: Request) -> Response:
        session, _ = await kit.checked(request)
        music = app.services.maybe(keys.music)
        if music is None:
            return kit.redirect(back("spotify"), "Spotify isn't set up on this server.")
        redirect = SpotifyLinks.redirect_uri(kit.ctx.base_url)
        return RedirectResponse(
            music.links.authorization_url(session.member, redirect), status_code=303
        )

    @router.get("/auth/spotify/callback")
    async def spotify_callback(
        request: Request, state: str = "", code: str = "", error: str = ""
    ) -> Response:
        session = kit.current(request)  # only for whoever started it
        music = app.services.maybe(keys.music)
        to = back("spotify")
        if music is None:
            return kit.redirect(to, "Spotify isn't set up on this server.")
        if error or not state or not code:
            return kit.redirect(to, "Spotify wasn't linked, so nothing changed.")
        try:
            premium = await music.links.complete(
                session.member, state, code, SpotifyLinks.redirect_uri(kit.ctx.base_url)
            )
        except SpotifyError as exc:
            return kit.redirect(to, f"Spotify wasn't linked: {exc}")
        if premium:
            return kit.redirect(to, "Linked Spotify. Ask Themi to play something.")
        return kit.redirect(
            to, "Linked Spotify. Without Premium, Themi sends links to play instead of playing."
        )

    @router.post("/accounts/spotify/unlink")
    async def unlink_spotify(request: Request) -> Response:
        session, _ = await kit.checked(request)
        if app.services.maybe(keys.music) is not None:
            app.services.maybe(keys.music).links.unlink(session.member)
        return kit.redirect(back("spotify"), "Unlinked Spotify.")

    return router
