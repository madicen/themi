"""Website sign-in: one-time links and server-side sessions.

- A login link is single-use and expires after 10 minutes. Opening it shows a
  Continue button; only pressing that signs you in. Telegram fetches link
  previews, and a plain GET that signed people in would burn the link.
- Sessions live in the database; the cookie only carries a random token
  (HttpOnly, SameSite=Lax, Secure when the site is served over HTTPS).
- Every session has its own CSRF token, which every POST must echo back.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from themi import clock
from themi.accounts import AccountStore, Member
from themi.localtime import to_utc_iso

LINK_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=30)
COOKIE_NAME = "themi_session"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    member: Member
    csrf_token: str
    expires_at: datetime


class WebAuth:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db

    # ----- login links --------------------------------------------------------

    def create_link_token(self, member: Member) -> str:
        token = secrets.token_urlsafe(32)
        now = clock.now()
        self.db.execute(
            "INSERT INTO login_links (token_hash, member_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_hash(token), member.id, to_utc_iso(now), to_utc_iso(now + LINK_TTL)),
        )
        return token

    def link_is_valid(self, token: str) -> bool:
        row = self.db.one(
            "SELECT expires_at FROM login_links WHERE token_hash = ? AND used_at IS NULL",
            (_hash(token),),
        )
        return row is not None and datetime.fromisoformat(row["expires_at"]) > clock.now()

    def consume_link(self, token: str) -> Member | None:
        """Use a link once. Returns its member, or None if it's unknown, used or expired."""
        now = clock.now()
        with self.db.transaction():
            row = self.db.one(
                "SELECT member_id, expires_at FROM login_links "
                "WHERE token_hash = ? AND used_at IS NULL",
                (_hash(token),),
            )
            if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
                return None
            self.db.execute(
                "UPDATE login_links SET used_at = ? WHERE token_hash = ?",
                (to_utc_iso(now), _hash(token)),
            )
        return self.store.get_member(row["member_id"])

    # ----- sessions -------------------------------------------------------------

    def start_session(self, member: Member) -> str:
        """Returns the cookie value."""
        token = secrets.token_urlsafe(32)
        now = clock.now()
        self.db.execute(
            "INSERT INTO web_sessions (token_hash, member_id, csrf_token, created_at, "
            "last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                _hash(token),
                member.id,
                secrets.token_urlsafe(24),
                to_utc_iso(now),
                to_utc_iso(now),
                to_utc_iso(now + SESSION_TTL),
            ),
        )
        return token

    def session(self, cookie: str | None) -> Session | None:
        if not cookie:
            return None
        row = self.db.one("SELECT * FROM web_sessions WHERE token_hash = ?", (_hash(cookie),))
        if row is None:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        now = clock.now()
        if expires <= now:
            self.db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (_hash(cookie),))
            return None
        # Sliding expiry: an active session stays signed in.
        new_expiry = now + SESSION_TTL
        self.db.execute(
            "UPDATE web_sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
            (to_utc_iso(now), to_utc_iso(new_expiry), _hash(cookie)),
        )
        return Session(self.store.get_member(row["member_id"]), row["csrf_token"], new_expiry)

    def end_session(self, cookie: str | None) -> None:
        if cookie:
            self.db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (_hash(cookie),))

    @staticmethod
    def csrf_ok(session: Session, submitted: str | None) -> bool:
        return bool(submitted) and hmac.compare_digest(session.csrf_token, submitted or "")
