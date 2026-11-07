"""Their own music on Spotify (BD5b): "play my focus playlist", "pause the music".

Playing is a side effect, so it goes through the trust tiers: a "music" category,
automatic to start (done, then told). A person's own link only ever plays to their own
account. Without Premium, Themi can't control playback, so "play X" sends the item's
link instead. With no Spotify app open, one line says to open it and ask again; nothing
retries in a loop.

During a body double session, what played is kept on the session row (`music`), as is a
built-in loop they start on the session page, for BD5c's suggestions.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from themi.accounts import Member
from themi.autonomy.engine import ExecutionContext
from themi.connectors.spotify import (
    Item,
    LinkRevoked,
    NeedsPremium,
    NoDevice,
    SpotifyError,
    SpotifyLinks,
)
from themi.core import keys
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "music"
PLAY = "music.play"
PAUSE = "music.pause"
NEXT = "music.next"  # F34i: the session page's Next
NO_DEVICE_TEXT = (
    "Spotify isn't open anywhere I can reach. Open it on your phone or speaker, then ask again."
)
NOT_LINKED_TEXT = "Spotify isn't linked for you yet: it's on the website's Accounts page."
NOTHING_FOUND_TEXT = "I couldn't find {query!r} on Spotify."
FREE_TEXT = "Here it is on Spotify: {link}"
PLAYING_TEXT = "Playing {name} on {device}."
PAUSED_TEXT = "Paused."
MINE = re.compile(r"\bmy\b", re.IGNORECASE)


class Music:
    def __init__(self, services: Services, links: SpotifyLinks) -> None:
        self.services = services
        self.links = links
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.provide(keys.music, self)
        s.autonomy.executors.register(PLAY)(self._execute_play)
        s.autonomy.executors.register(PAUSE)(self._execute_pause)
        s.autonomy.executors.register(NEXT)(self._execute_next)
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
        item: Item | None = None
        try:
            if payload.get("uri"):  # BD5c's offer: something that played before
                uri = str(payload["uri"])
                kind = uri.split(":")[1] if uri.count(":") >= 2 else "playlist"
                link = f"https://open.spotify.com/{kind}/{uri.rsplit(':', 1)[-1]}"
                item = Item(uri, str(payload.get("name") or uri), kind, link)
            else:
                item = await self.find(member, query)
            if item is None:
                return NOTHING_FOUND_TEXT.format(query=query)
            if not self.premium(member):
                self.note_session(member, item.uri, item.name)
                return FREE_TEXT.format(link=item.link or item.uri)
            devices = await self.links.with_token(member, self.links.client.devices)
            if not devices:
                return NO_DEVICE_TEXT
            device = next((d for d in devices if d.active), devices[0])
            chosen = item
            await self.links.with_token(
                member, lambda access: self.links.client.play(access, chosen, device.id)
            )
        except NoDevice:
            return NO_DEVICE_TEXT
        except NeedsPremium:
            self.db.execute(
                "UPDATE spotify_links SET premium = 0 WHERE member_id = ?", (member.id,)
            )
            return FREE_TEXT.format(link=item.link or item.uri) if item else NO_DEVICE_TEXT
        except LinkRevoked:
            return NOT_LINKED_TEXT
        self.note_session(member, item.uri, item.name)
        return PLAYING_TEXT.format(name=item.name, device=device.name or "your Spotify")

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
