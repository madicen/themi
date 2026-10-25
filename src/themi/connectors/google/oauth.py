"""Google OAuth: signing in to the website, and linking Gmail accounts.

Authorization-code flow with PKCE (S256) and a single-use state, over `httpx`
against configurable endpoints, so tests point it at a local fake.

- Sign-in asks only for `openid email`. The verified address must be a
  member's sign-in address.
- Linking asks for Gmail (`gmail.modify`) and Calendar events, offline, with
  consent forced so Google returns a refresh token every time. Refresh tokens
  are stored encrypted; access tokens are kept only in memory.
- The state lives in `oauth_states` (hashed), with the PKCE verifier
  encrypted, for 10 minutes. A state works once, and the callback must come
  back to the redirect address it was issued for.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

Purpose = Literal["signin", "link"]

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"  # write events
# Find the family's "Themi" calendar by name, or make it if there isn't one.
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
CALENDAR_CREATE_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
CALENDAR_SCOPES = (CALENDAR_SCOPE, CALENDAR_LIST_SCOPE, CALENDAR_CREATE_SCOPE)
SIGNIN_SCOPES = ("openid", "email")
LINK_SCOPES = ("openid", "email", GMAIL_SCOPE, *CALENDAR_SCOPES)
STATE_TTL = timedelta(minutes=10)
TIMEOUT = 20.0


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: Secret = field(repr=False)
    auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url: str = "https://oauth2.googleapis.com/token"
    revoke_url: str = "https://oauth2.googleapis.com/revoke"
    userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    gmail_url: str = "https://gmail.googleapis.com"
    calendar_url: str = "https://www.googleapis.com"


class OAuthError(Exception):
    """Something to tell the person, in plain words."""


class TokenRevoked(OAuthError):
    """Google no longer accepts this token (revoked, expired or the password changed)."""


@dataclass(frozen=True)
class AccessToken:
    token: Secret = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class Grant:
    """What came back from a completed sign-in or linking flow."""

    purpose: Purpose
    member_id: int | None
    email: str
    email_verified: bool
    scopes: frozenset[str]
    access: AccessToken
    refresh_token: Secret | None = field(default=None, repr=False)


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class GoogleOAuth:
    def __init__(self, db: Database, cipher: Cipher, config: GoogleConfig) -> None:
        self.db = db
        self.cipher = cipher
        self.config = config

    # ----- starting -----------------------------------------------------------

    def authorization_url(
        self, purpose: Purpose, redirect_uri: str, member: Member | None = None
    ) -> str:
        if purpose == "link" and member is None:
            raise ValueError("linking an account needs the member it's for")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)  # 86 characters: within PKCE's 43-128
        now = clock.now()
        self.db.execute(
            "INSERT INTO oauth_states (state_hash, purpose, member_id, code_verifier, "
            "redirect_uri, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _hash(state),
                purpose,
                member.id if member else None,
                self.cipher.encrypt(verifier),
                redirect_uri,
                to_utc_iso(now),
                to_utc_iso(now + STATE_TTL),
            ),
        )
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SIGNIN_SCOPES if purpose == "signin" else LINK_SCOPES),
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        if purpose == "link":
            # Offline + consent: a refresh token every time, even for a re-link.
            params |= {"access_type": "offline", "prompt": "consent"}
        else:
            params["prompt"] = "select_account"
        return f"{self.config.auth_url}?{urlencode(params)}"

    # ----- finishing ----------------------------------------------------------

    def _claim_state(self, state: str) -> dict[str, Any]:
        now = clock.now()
        with self.db.transaction():
            row = self.db.one(
                "SELECT * FROM oauth_states WHERE state_hash = ? AND used_at IS NULL",
                (_hash(state),),
            )
            if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
                raise OAuthError("That sign-in attempt has expired or was already used.")
            self.db.execute(
                "UPDATE oauth_states SET used_at = ? WHERE state_hash = ?",
                (to_utc_iso(now), _hash(state)),
            )
        return row

    async def complete(self, state: str, code: str, redirect_uri: str) -> Grant:
        """Exchange the code from Google's callback. The state is used up either way."""
        row = self._claim_state(state)
        if row["redirect_uri"] != redirect_uri:
            raise OAuthError("That sign-in came back to the wrong address.")
        verifier = self.cipher.decrypt(row["code_verifier"]).reveal()
        try:
            body = await self._post(
                self.config.token_url,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret.reveal(),
                },
            )
        except TokenRevoked as exc:  # a bad code or PKCE verifier
            raise OAuthError(
                "Google turned that sign-in down. Starting again usually works."
            ) from exc
        access = self._access_token(body)
        info = await self._userinfo(access.token)
        refresh = body.get("refresh_token")
        return Grant(
            purpose=row["purpose"],
            member_id=row["member_id"],
            email=str(info.get("email", "")).strip().lower(),
            email_verified=info.get("email_verified") in (True, "true"),
            scopes=frozenset(str(body.get("scope", "")).split()),
            access=access,
            refresh_token=Secret(refresh) if refresh else None,
        )

    async def refresh(self, refresh_token: Secret) -> AccessToken:
        body = await self._post(
            self.config.token_url,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.reveal(),
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret.reveal(),
            },
        )
        return self._access_token(body)

    async def revoke(self, token: Secret) -> None:
        """Cancel a token at Google. A token Google already forgot counts as revoked."""
        try:
            await self._post(self.config.revoke_url, {"token": token.reveal()})
        except TokenRevoked:
            return

    def forget_expired_states(self) -> int:
        return self.db.update(
            "DELETE FROM oauth_states WHERE expires_at <= ?",
            (to_utc_iso(clock.now() - timedelta(days=1)),),
        )

    # ----- HTTP ---------------------------------------------------------------

    @staticmethod
    def _access_token(body: dict[str, Any]) -> AccessToken:
        token = body.get("access_token")
        if not token:
            raise OAuthError("Google didn't send an access token.")
        expires_in = int(body.get("expires_in", 3600))
        return AccessToken(Secret(str(token)), clock.now() + timedelta(seconds=expires_in))

    async def _userinfo(self, token: Secret) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(
                    self.config.userinfo_url,
                    headers={"Authorization": f"Bearer {token.reveal()}"},
                )
        except httpx.HTTPError as exc:
            raise OAuthError(
                "Google couldn't be reached. Trying again soon usually works."
            ) from exc
        if response.status_code != 200:
            raise OAuthError("Google didn't say which account this is.")
        return response.json()

    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            log.warning("Google OAuth request failed (%s)", type(exc).__name__)
            raise OAuthError(
                "Google couldn't be reached. Trying again soon usually works."
            ) from exc
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if response.status_code == 200:
            return body
        error = body.get("error", "") if isinstance(body, dict) else ""
        log.info("Google OAuth refused a request: HTTP %s %s", response.status_code, error)
        if error in ("invalid_grant", "invalid_token"):
            raise TokenRevoked("Google no longer accepts this sign-in. Linking again fixes it.")
        raise OAuthError("Google turned that down. Trying again from the start usually works.")
