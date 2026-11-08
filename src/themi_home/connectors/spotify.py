"""Spotify (BD5b): each person's own music, through Spotify's Web API.

- Sign-in: OAuth 2 authorization code with PKCE (no client secret), from Accounts. The
  refresh token is kept encrypted; access tokens (an hour) live in memory, and a refresh
  may hand back a new refresh token, which replaces the old.
- Scopes: reading and changing playback, the account (for Premium), and their playlists.
- Playback control needs Premium. The account's `product` is read at link time; without
  Premium, "play X" sends the item's link instead.
- With no device open, play answers 404 NO_ACTIVE_DEVICE; Themi says so once.

`SpotifyClient` is only the wire. `SpotifyLinks` keeps each person's link.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from themi import clock
from themi.accounts import Member
from themi.http import tls
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

ACCOUNTS_URL = "https://accounts.spotify.com"
API_URL = "https://api.spotify.com/v1"
SCOPES = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-private",
    "playlist-read-private",
)
STATE_TTL = timedelta(minutes=10)
EARLY = timedelta(minutes=5)
TIMEOUT = 15.0


@dataclass(frozen=True)
class SpotifyConfig:
    client_id: str
    accounts_url: str = ACCOUNTS_URL
    api_url: str = API_URL


class SpotifyError(Exception):
    """Spotify couldn't be reached or said no."""


class LinkRevoked(SpotifyError):
    """Their sign-in no longer works: linking again on Accounts fixes it."""


class NoDevice(SpotifyError):
    """No Spotify app is open on a phone, computer or speaker."""


class NeedsPremium(SpotifyError):
    """Playback control needs Spotify Premium."""


@dataclass(frozen=True)
class Tokens:
    access: Secret = field(repr=False)
    expires_at: datetime
    refresh: Secret | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Item:
    """Something to play: a playlist, album or track."""

    uri: str
    name: str
    kind: str  # playlist, album or track
    link: str  # open.spotify.com, for a free account


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    active: bool


def pkce_pair() -> tuple[str, str]:
    """A code verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class SpotifyClient:
    def __init__(
        self, config: SpotifyConfig, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.config = config
        self._http = httpx.AsyncClient(verify=tls(), transport=transport, timeout=TIMEOUT)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- signing in ----------------------------------------------------------------------

    def authorize_url(self, state: str, challenge: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
            "scope": " ".join(SCOPES),
        }
        return f"{self.config.accounts_url.rstrip('/')}/authorize?{urlencode(params)}"

    async def exchange(self, code: str, verifier: str, redirect_uri: str) -> Tokens:
        return await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.config.client_id,
                "code_verifier": verifier,
            }
        )

    async def refresh(self, refresh_token: Secret) -> Tokens:
        return await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.reveal(),
                "client_id": self.config.client_id,
            }
        )

    # ----- the account and playback --------------------------------------------------------

    async def me(self, access: Secret) -> dict[str, Any]:
        return await self._call("GET", "/me", access)

    async def search(self, access: Secret, query: str, *, mine: bool = False) -> list[Item]:
        """Playlists, then albums, then tracks. `mine`: their own playlists first."""
        found: list[Item] = []
        if mine:
            body = await self._call("GET", "/me/playlists?limit=50", access)
            words = set(query.lower().split()) - {"my", "the", "playlist"}
            for p in body.get("items") or []:
                if p and words and words <= set(str(p.get("name", "")).lower().split()):
                    found.append(_item(p, "playlist"))
        params = urlencode({"q": query, "type": "playlist,album,track", "limit": 3})
        body = await self._call("GET", f"/search?{params}", access)
        for kind in ("playlist", "album", "track"):
            for raw in (body.get(f"{kind}s") or {}).get("items") or []:
                if raw:
                    found.append(_item(raw, kind))
        return found

    async def playlists(self, access: Secret) -> list[Item]:
        """Their own library's playlists, as Spotify lists them (most recent first)."""
        body = await self._call("GET", "/me/playlists?limit=50", access)
        return [_item(p, "playlist") for p in body.get("items") or [] if p]

    async def devices(self, access: Secret) -> list[Device]:
        body = await self._call("GET", "/me/player/devices", access)
        return [
            Device(str(d["id"]), str(d.get("name", "")), bool(d.get("is_active")))
            for d in body.get("devices") or []
            if d.get("id") and not d.get("is_restricted")
        ]

    async def play(self, access: Secret, item: Item, device_id: str) -> None:
        body = {"uris": [item.uri]} if item.kind == "track" else {"context_uri": item.uri}
        await self._call("PUT", f"/me/player/play?device_id={device_id}", access, body)

    async def pause(self, access: Secret) -> None:
        await self._call("PUT", "/me/player/pause", access)

    async def next(self, access: Secret) -> None:
        await self._call("POST", "/me/player/next", access)

    async def volume(self, access: Secret, percent: int) -> None:
        await self._call("PUT", f"/me/player/volume?volume_percent={percent}", access)

    # ----- the wire ------------------------------------------------------------------------

    async def _token(self, form: dict[str, str]) -> Tokens:
        try:
            response = await self._http.post(
                f"{self.config.accounts_url.rstrip('/')}/api/token", data=form
            )
        except httpx.HTTPError as exc:
            raise SpotifyError(f"Spotify couldn't be reached ({type(exc).__name__})") from exc
        body = _json(response)
        if response.status_code in (400, 401):
            log.info("Spotify refused a token request: %s", body.get("error", ""))
            raise LinkRevoked("Spotify no longer accepts this sign-in; link it again.")
        if response.status_code != 200 or not body.get("access_token"):
            raise SpotifyError(f"Spotify's sign-in answered {response.status_code}")
        refresh = body.get("refresh_token")
        return Tokens(
            Secret(str(body["access_token"])),
            clock.now() + timedelta(seconds=int(body.get("expires_in", 3600))),
            Secret(str(refresh)) if refresh else None,
        )

    async def _call(
        self, method: str, path: str, access: Secret, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access.reveal()}"}
        try:
            response = await self._http.request(
                method, f"{self.config.api_url.rstrip('/')}{path}", headers=headers, json=body
            )
        except httpx.HTTPError as exc:
            raise SpotifyError(f"Spotify couldn't be reached ({type(exc).__name__})") from exc
        reason = str(_json(response).get("error", {}).get("reason", "")) if response.content else ""
        if response.status_code == 401:
            raise LinkRevoked("Spotify turned down the access token.")
        if response.status_code == 404 and (reason == "NO_ACTIVE_DEVICE" or "player" in path):
            raise NoDevice("No Spotify device is open.")
        if response.status_code == 403 and reason == "PREMIUM_REQUIRED":
            raise NeedsPremium("That needs Spotify Premium.")
        if response.status_code not in (200, 201, 202, 204):
            raise SpotifyError(f"Spotify answered {response.status_code} for {path}")
        return _json(response)


def _item(raw: dict[str, Any], kind: str) -> Item:
    link = str((raw.get("external_urls") or {}).get("spotify") or "")
    return Item(str(raw["uri"]), str(raw.get("name", "")), kind, link)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json() if response.content else {}
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


class SpotifyLinks:
    """Each person's own Spotify sign-in: only theirs, used only for their music."""

    def __init__(self, db: Database, cipher: Cipher, client: SpotifyClient) -> None:
        self.db = db
        self.cipher = cipher
        self.client = client
        self._access: dict[int, Tokens] = {}

    @staticmethod
    def redirect_uri(base_url: str) -> str:
        return f"{base_url.rstrip('/')}/auth/spotify/callback"

    def link(self, member: Member) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT member_id, display_name, premium, linked_at FROM spotify_links "
            "WHERE member_id = ?",
            (member.id,),
        )

    def authorization_url(self, member: Member, redirect_uri: str) -> str:
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        self.db.execute(
            "INSERT INTO spotify_states (state_hash, member_id, verifier, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_hash(state), member.id, self.cipher.encrypt(Secret(verifier)),
             to_utc_iso(clock.now() + STATE_TTL)),
        )  # fmt: skip
        return self.client.authorize_url(state, challenge, redirect_uri)

    async def complete(self, member: Member, state: str, code: str, redirect_uri: str) -> bool:
        """Finish a link from Spotify's callback, for the member who started it (the state
        works once, and only for them). Returns whether the account has Premium."""
        now = clock.now()
        with self.db.transaction():
            row = self.db.one("SELECT * FROM spotify_states WHERE state_hash = ?", (_hash(state),))
            self.db.execute(
                "DELETE FROM spotify_states WHERE state_hash = ? OR expires_at <= ?",
                (_hash(state), to_utc_iso(now)),
            )
        if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
            raise SpotifyError("That link has expired or was already used; start again.")
        if row["member_id"] != member.id:
            raise SpotifyError("That link was started by someone else.")
        verifier = self.cipher.decrypt(row["verifier"]).reveal()
        tokens = await self.client.exchange(code, verifier, redirect_uri)
        if tokens.refresh is None:
            raise SpotifyError("Spotify didn't send a refresh token; try linking again.")
        me = await self.client.me(tokens.access)
        premium = str(me.get("product", "")) == "premium"
        self.db.execute(
            "INSERT INTO spotify_links (member_id, refresh_token, display_name, premium, "
            "linked_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT (member_id) DO UPDATE SET "
            "refresh_token = excluded.refresh_token, display_name = excluded.display_name, "
            "premium = excluded.premium, linked_at = excluded.linked_at",
            (member.id, self.cipher.encrypt(tokens.refresh), str(me.get("display_name") or ""),
             int(premium), to_utc_iso(now)),
        )  # fmt: skip
        self._access[member.id] = tokens
        return premium

    def unlink(self, member: Member) -> None:
        self.db.execute("DELETE FROM spotify_links WHERE member_id = ?", (member.id,))
        self._access.pop(member.id, None)

    async def with_token(self, member: Member, call: Any) -> Any:
        for attempt in range(2):
            access = await self._token(member, fresh=attempt > 0)
            try:
                return await call(access)
            except LinkRevoked:
                if attempt:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    async def _token(self, member: Member, *, fresh: bool = False) -> Secret:
        held = self._access.get(member.id)
        if not fresh and held and clock.now() < held.expires_at - EARLY:
            return held.access
        row = self.db.one(
            "SELECT refresh_token FROM spotify_links WHERE member_id = ?", (member.id,)
        )
        if row is None:
            raise LinkRevoked("Spotify isn't linked.")
        tokens = await self.client.refresh(self.cipher.decrypt(row["refresh_token"]))
        if tokens.refresh is not None:  # a new one replaces the old
            self.db.execute(
                "UPDATE spotify_links SET refresh_token = ? WHERE member_id = ?",
                (self.cipher.encrypt(tokens.refresh), member.id),
            )
        self._access[member.id] = tokens
        return tokens.access
