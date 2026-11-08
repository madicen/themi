"""SP7b: what Themi keeps for passkeys: each admin's passkeys, their recovery code, and the
challenges of ceremonies under way. The WebAuthn checks themselves are the website's
(`themi.web.passkey_pages`, with py_webauthn); this is only storage.

Passkeys are for admins. Family members sign in with the link /site sends, as before.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from themi import clock
from themi.accounts.models import Member
from themi.accounts.store import AccountStore
from themi.localtime import to_utc_iso

CHALLENGE_FOR = timedelta(minutes=5)
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _plain(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())


@dataclass(frozen=True)
class Passkey:
    id: int
    member_id: int
    credential_id: bytes
    public_key: bytes
    sign_count: int
    name: str
    created_at: str
    last_used_at: str | None


class Passkeys:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db

    # ----- passkeys -------------------------------------------------------------------

    def add(self, member: Member, credential_id: bytes, public_key: bytes, count: int, name: str):
        self.db.execute(
            "INSERT INTO passkeys (member_id, credential_id, public_key, sign_count, name, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (member.id, credential_id, public_key, count, name, to_utc_iso(clock.now())),
        )

    def of(self, member: Member) -> list[Passkey]:
        rows = self.db.query("SELECT * FROM passkeys WHERE member_id = ? ORDER BY id", (member.id,))
        return [Passkey(**{k: row[k] for k in Passkey.__dataclass_fields__}) for row in rows]

    def find(self, credential_id: bytes) -> Passkey | None:
        row = self.db.one("SELECT * FROM passkeys WHERE credential_id = ?", (credential_id,))
        return Passkey(**{k: row[k] for k in Passkey.__dataclass_fields__}) if row else None

    def used(self, passkey: Passkey, count: int) -> None:
        self.db.execute(
            "UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ?",
            (count, to_utc_iso(clock.now()), passkey.id),
        )

    def remove(self, member: Member, passkey_id: int) -> bool:
        return (
            self.db.execute(
                "DELETE FROM passkeys WHERE id = ? AND member_id = ?", (passkey_id, member.id)
            )
            > 0
        )

    def any(self) -> bool:
        return self.db.scalar("SELECT 1 FROM passkeys LIMIT 1") is not None

    # ----- recovery codes ---------------------------------------------------------------

    def new_recovery_code(self, member: Member) -> str:
        """A new code for `member` (the old one stops working). Shown once."""
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(16))
        code = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
        self.db.execute(
            "INSERT INTO recovery_codes (member_id, code_hash, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(member_id) DO UPDATE SET code_hash = excluded.code_hash, "
            "created_at = excluded.created_at",
            (member.id, _hash(_plain(code)), to_utc_iso(clock.now())),
        )
        return code

    def has_recovery_code(self, member: Member) -> bool:
        return (
            self.db.scalar("SELECT 1 FROM recovery_codes WHERE member_id = ?", (member.id,))
            is not None
        )

    def use_recovery_code(self, code: str) -> Member | None:
        """The member whose code this is, if any; the code is gone after."""
        with self.db.transaction():
            row = self.db.one(
                "SELECT member_id FROM recovery_codes WHERE code_hash = ?", (_hash(_plain(code)),)
            )
            if row is None:
                return None
            self.db.execute("DELETE FROM recovery_codes WHERE member_id = ?", (row["member_id"],))
        member = self.store.get_member(row["member_id"])
        return member if member.is_admin else None

    # ----- challenges ---------------------------------------------------------------------

    def start(self, purpose: str, challenge: bytes, member: Member | None = None) -> str:
        """Keep a ceremony's challenge; returns the token that finds it again."""
        token = secrets.token_urlsafe(24)
        now = clock.now()
        self.db.execute("DELETE FROM passkey_challenges WHERE expires_at < ?", (to_utc_iso(now),))
        self.db.execute(
            "INSERT INTO passkey_challenges (token_hash, member_id, purpose, challenge, "
            "expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                _hash(token),
                member.id if member else None,
                purpose,
                challenge,
                to_utc_iso(now + CHALLENGE_FOR),
            ),
        )
        return token

    def finish(self, token: str | None, purpose: str, member: Member | None = None) -> bytes | None:
        """The challenge `token` found, used up; None when there's none, it's for something
        else or someone else, or it ran out."""
        if not token:
            return None
        with self.db.transaction():
            row = self.db.one(
                "SELECT * FROM passkey_challenges WHERE token_hash = ?", (_hash(token),)
            )
            self.db.execute("DELETE FROM passkey_challenges WHERE token_hash = ?", (_hash(token),))
        if row is None or row["purpose"] != purpose:
            return None
        if member is not None and row["member_id"] != member.id:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= clock.now():
            return None
        return bytes(row["challenge"])
