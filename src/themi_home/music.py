"""Their own music on Spotify (BD5b): "play my focus playlist", "pause the music".

Playing is a side effect, so it goes through the trust tiers: a "music" category,
automatic to start (done, then told). A person's own link only ever plays to their own
account. Without Premium, Themi can't control playback, so "play X" sends the item's
link instead. With no Spotify app open, one line says to open it and ask again; nothing
retries in a loop.

During a body double session, what played is kept on the session row (`music`), as is a
built-in loop they start on the session page, for BD5c's suggestions.

The pages' choice of their music (the session page's "My Spotify", the cook screen's
"Spotify playlists") starts with their liked songs (the default, kept as `LIKED`), then
their playlists. A Shuffle toggle beside it plays the chosen one in order or at random; it's
kept per person (`SpotifyPlayback`) and used by every Play, from the pages or from chat.
"""

from __future__ import annotations

import contextlib
import logging
import random
import re
from typing import TYPE_CHECKING, Any, ClassVar

from themi.accounts import Member
from themi.accounts.preferences import Preferences
from themi.autonomy.engine import ExecutionContext
from themi.core import keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi_home.connectors.spotify import (
    Device,
    Item,
    LinkRevoked,
    MissingScope,
    NeedsPremium,
    NoDevice,
    SpotifyError,
    SpotifyLinks,
)

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "music"
PLAY = "music.play"
PAUSE = "music.pause"
NEXT = "music.next"  # F34i: the session page's Next
SHUFFLE = "music.shuffle"  # F47a: the pages' Shuffle toggle
PHONE_NOT_LISTED_TEXT = (
    "Spotify isn't open on your phone right now. Open it there, then tap Play again."
)
NO_DEVICE_TEXT = (
    "Spotify isn't open anywhere I can reach. Open it on your phone or speaker, then ask again."
)
NOT_LINKED_TEXT = "Spotify isn't linked for you yet: it's on the website's Accounts page."
NOTHING_FOUND_TEXT = "I couldn't find {query!r} on Spotify."
FREE_TEXT = "Here it is on Spotify: {link}"
PLAYING_TEXT = "Playing {name} on {device}."
PAUSED_TEXT = "Paused."
LIKED = "spotify:liked"  # their liked songs, shuffled
LIKED_NAME = "Liked songs"
LIKED_LINK = "https://open.spotify.com/collection/tracks"
NO_LIKED_TEXT = "There aren't any liked songs on your Spotify yet."
SHUFFLE_ON_TEXT = "Shuffle on: songs play in a random order."
SHUFFLE_OFF_TEXT = "Shuffle off: songs play in order."
RELINK_TEXT = (
    "To play your liked songs, Spotify needs asking again: on the website's Accounts page, "
    "unlink Spotify and link it again."
)
# Spotify device types someone plays to on purpose: a tap from a phone leaves these playing
CHOSEN_KINDS = {"speaker", "tv", "avr", "stb", "audiodongle", "castaudio", "castvideo",
                "automobile", "gameconsole"}  # fmt: skip
MINE = re.compile(r"\bmy\b", re.IGNORECASE)


class Music:
    def __init__(self, services: Services, links: SpotifyLinks) -> None:
        self.services = services
        self.links = links
        self.db = services.store.db
        self.rng = random.Random()  # a shuffled start, and liked songs' order

    def install(self) -> None:
        s = self.services
        s.provide(keys.music, self)
        s.autonomy.executors.register(PLAY)(self._execute_play)
        s.autonomy.executors.register(PAUSE)(self._execute_pause)
        s.autonomy.executors.register(NEXT)(self._execute_next)
        s.autonomy.executors.register(SHUFFLE)(self._execute_shuffle)
        for t in (play_music, pause_music):
            s.tools.register(t)

    def premium(self, member: Member) -> bool | None:
        """None when they haven't linked Spotify."""
        link = self.links.link(member)
        return None if link is None else bool(link["premium"])

    async def find(self, member: Member, query: str) -> Item | None:
        found = await self.links.with_token(
            member,
            lambda access: self.links.client.search(access, query, mine=bool(MINE.search(query))),
        )
        return found[0] if found else None

    async def _execute_play(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        member = ctx.member
        query = str(payload.get("query", ""))
        uri = str(payload.get("uri") or "")
        item: Item | None = None
        shuffle = shuffled(self.services.store, member)
        try:
            if uri == LIKED:
                item = Item(LIKED, LIKED_NAME, "liked", LIKED_LINK)
            elif uri:  # BD5c's offer: something that played before
                kind = uri.split(":")[1] if uri.count(":") >= 2 else "playlist"
                link = f"https://open.spotify.com/{kind}/{uri.rsplit(':', 1)[-1]}"
                count = int(payload.get("count") or 0)
                item = Item(uri, str(payload.get("name") or uri), kind, link, count)
            else:
                item = await self.find(member, query)
            if item is None:
                return NOTHING_FOUND_TEXT.format(query=query)
            if not self.premium(member):
                self.note_session(member, item.uri, item.name)
                return FREE_TEXT.format(link=item.link or item.uri)
            tracks: list[str] = []
            if item.kind == "liked":
                rng = self.rng
                tracks = await self.links.with_token(
                    member, lambda access: self.links.client.liked(access, rng, shuffle=shuffle)
                )
                if not tracks:
                    return NO_LIKED_TEXT
            devices = await self.links.with_token(member, self.links.client.devices)
            if not devices:
                return NO_DEVICE_TEXT
            device = pick_device(devices, from_phone=bool(payload.get("from_phone")))
            if device is None:
                return PHONE_NOT_LISTED_TEXT
            chosen = item
            client = self.links.client
            start = self.rng.randrange(item.count) if shuffle and item.count > 1 else None
            await self.links.with_token(
                member,
                lambda access: client.play_tracks(access, tracks, device.id) if tracks
                else client.play(access, chosen, device.id, start=start),
            )  # fmt: skip
            await self._set_shuffle(member, shuffle, device.id)
        except NoDevice:
            return NO_DEVICE_TEXT
        except MissingScope:
            return RELINK_TEXT
        except NeedsPremium:
            self.db.execute(
                "UPDATE spotify_links SET premium = 0 WHERE member_id = ?", (member.id,)
            )
            return FREE_TEXT.format(link=item.link or item.uri) if item else NO_DEVICE_TEXT
        except LinkRevoked:
            return NOT_LINKED_TEXT
        self.note_session(member, item.uri, item.name)
        name = "your liked songs" if item.kind == "liked" else item.name
        return PLAYING_TEXT.format(name=name, device=device.name or "your Spotify")

    async def _set_shuffle(self, member: Member, on: bool, device_id: str) -> None:
        """Spotify's own shuffle, to match the toggle: what plays next keeps to it. A
        refusal here leaves the music playing; it's only the order."""
        try:
            await self.links.with_token(
                member, lambda access: self.links.client.shuffle(access, on, device_id)
            )
        except SpotifyError as exc:
            log.info(
                "Spotify didn't take shuffle for member %s (%s)", member.id, type(exc).__name__
            )

    async def _execute_shuffle(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        """The toggle, while something plays: Spotify's shuffle now (it's already saved for
        the next Play, so nothing playing is fine)."""
        on = bool(payload.get("on"))
        said = SHUFFLE_ON_TEXT if on else SHUFFLE_OFF_TEXT
        with contextlib.suppress(SpotifyError):  # nothing playing: the next Play keeps to it
            await self.links.with_token(
                ctx.member, lambda access: self.links.client.shuffle(access, on)
            )
        return said

    async def _execute_pause(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        try:
            await self.links.with_token(ctx.member, self.links.client.pause)
        except NoDevice:
            return "Nothing's playing on Spotify."
        except NeedsPremium:
            return "Pausing from here needs Spotify Premium."
        except LinkRevoked:
            return NOT_LINKED_TEXT
        return PAUSED_TEXT

    async def playlists(self, member: Member) -> list[Item]:
        """F34i: their own playlists, or [] when Spotify isn't linked or doesn't answer."""
        if self.premium(member) is None:
            return []
        try:
            found = await self.links.with_token(member, self.links.client.playlists)
        except Exception as exc:  # no playlists then: the built-in loops are still there
            log.info("No playlists for member %s (%s)", member.id, type(exc).__name__)
            return []
        return list(found)

    async def _execute_next(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        try:
            await self.links.with_token(ctx.member, self.links.client.next)
        except NoDevice:
            return "Nothing's playing on Spotify."
        except NeedsPremium:
            return "Skipping from here needs Spotify Premium."
        except LinkRevoked:
            return NOT_LINKED_TEXT
        return "Next one."

    def note_session(self, member: Member, music: str, name: str) -> None:
        """What's playing, on the body double session going on (BD5c learns from it)."""
        if self.services.maybe(keys.body_double) is not None:
            self.services.get(keys.body_double).note_music(member, music, name)


def pick_device(devices: list[Device], *, from_phone: bool = False) -> Device | None:
    """Where to play: the active device, else the first. From a phone (bug 2026-11-18), a
    speaker, TV or the like already playing; else the phone itself (when Spotify lists
    exactly one); never a computer that was last used. None: Spotify isn't open on the
    phone (iOS drops it from the list soon after it stops playing)."""
    active = next((d for d in devices if d.active), None)
    if not from_phone:
        return active or devices[0]
    if active is not None and active.kind.lower() in {*CHOSEN_KINDS, "smartphone"}:
        return active
    phones = [d for d in devices if d.kind.lower() == "smartphone"]
    return phones[0] if len(phones) == 1 else None


class SpotifyPlayback(Preferences):
    """F47a: how their Spotify plays from Themi. Its own, off the settings form (a checkbox
    there that the form didn't show would be unticked on every save)."""

    module: ClassVar[str] = "spotify"
    spotify_shuffle: bool = False  # the chosen playlist in a random order


def shuffled(store: Any, member: Member) -> bool:
    return store.preferences(member.id, SpotifyPlayback).spotify_shuffle


def set_shuffle(store: Any, member: Member, on: bool) -> None:
    store.save_preferences(member, member.id, SpotifyPlayback, spotify_shuffle=on)


def choices(playlists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pages' choice of their music: liked songs first (the default), then their
    playlists. [] stays [] (no Spotify)."""
    if not playlists:
        return []
    return [{"uri": LIKED, "name": LIKED_NAME, "link": LIKED_LINK}, *playlists]


def _music(ctx: ToolContext) -> Music:
    music = ctx.services.maybe(keys.music)
    if music is None:
        raise ToolFailed(
            "Spotify isn't set up on this server (SPOTIFY_CLIENT_ID). The session page's "
            "built-in sounds work without it: choose_session_sound."
        )
    return music


@tool(
    "play_music",
    "Play something on their own Spotify when they ask ('play my focus playlist', 'put on "
    "some lofi while I work', 'play Abbey Road'), in a session or not. query: what they "
    "named, in their words. The built-in sounds of the session page (rain, brown noise) "
    "are choose_session_sound.",
    {"query": {"type": "string"}},
)
async def play_music(ctx: ToolContext, args: dict[str, Any]) -> str:
    music = _music(ctx)
    query = " ".join(str(args.get("query", "")).split())[:200]
    if not query:
        raise ToolFailed("Say what to play.")
    if music.premium(ctx.member) is None:
        raise ToolDeclined(NOT_LINKED_TEXT)
    outcome = await ctx.services.autonomy.stage(
        CATEGORY, ctx.member, f"Play {query} on Spotify", {"query": query}, PLAY,
        interactive=True, requested=True,
    )  # fmt: skip
    ctx.replies.append(outcome.message)
    ctx.asked.append(outcome.message)  # done as they asked, and said: the turn ends (P2b)
    return outcome.message


@tool(
    "pause_music",
    "Pause their Spotify when they ask ('pause the music', 'stop the music').",
    {},
)
async def pause_music(ctx: ToolContext, args: dict[str, Any]) -> str:
    music = _music(ctx)
    if music.premium(ctx.member) is None:
        raise ToolDeclined(NOT_LINKED_TEXT)
    outcome = await ctx.services.autonomy.stage(
        CATEGORY, ctx.member, "Pause Spotify", {}, PAUSE, interactive=True, requested=True
    )
    ctx.replies.append(outcome.message)
    ctx.asked.append(outcome.message)  # done as they asked, and said: the turn ends (P2b)
    return outcome.message


def install(services: Services, links: SpotifyLinks | None) -> None:
    if links is not None:
        Music(services, links).install()


__all__ = ["Music", "SpotifyError", "install"]
