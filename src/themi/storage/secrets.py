"""Secrets at rest: Fernet encryption and a value wrapper that never prints itself.

Every credential Themi stores (refresh tokens, device keys, AI keys) is
encrypted with the server's secret key before it reaches the database. In
memory it travels as a `Secret`, whose `str`/`repr` are masked so a stray log
line or exception can't leak it.
"""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, NoReturn

from cryptography.fernet import Fernet, InvalidToken

from themi import clock

if TYPE_CHECKING:
    from themi.storage.db import Database

MASK = "********"


class Secret:
    """A sensitive string. Call `reveal()` only at the point of use."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("Secret wraps a str")
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return MASK

    def __repr__(self) -> str:
        return f"Secret('{MASK}')"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    def __hash__(self) -> int:
        raise TypeError("Secret is not hashable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Secret cannot be pickled")


class SecretKeyError(ValueError):
    """The configured secret key is missing or malformed."""


class DecryptionError(Exception):
    """Ciphertext could not be decrypted with the configured key."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


class Cipher:
    def __init__(self, key: str | Secret) -> None:
        raw = key.reveal() if isinstance(key, Secret) else key
        try:
            self._fernet = Fernet(raw.strip().encode())
        except (ValueError, TypeError) as exc:
            raise SecretKeyError(
                "THEMI_SECRET_KEY is not a valid key; generate one with `themi keygen`"
            ) from exc

    def encrypt(self, value: str | Secret) -> bytes:
        raw = value.reveal() if isinstance(value, Secret) else value
        return self._fernet.encrypt(raw.encode())

    def decrypt(self, token: bytes) -> Secret:
        try:
            return Secret(self._fernet.decrypt(token).decode())
        except InvalidToken as exc:
            raise DecryptionError(
                "could not decrypt a stored secret: wrong THEMI_SECRET_KEY or corrupted data"
            ) from exc


class SecretStore:
    """Named, encrypted values in the `app_secrets` table."""

    def __init__(self, db: Database, cipher: Cipher) -> None:
        self._db = db
        self._cipher = cipher

    def put(self, name: str, value: str | Secret) -> None:
        self._db.execute(
            "INSERT INTO app_secrets (name, ciphertext, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET ciphertext = excluded.ciphertext, "
            "updated_at = excluded.updated_at",
            (name, self._cipher.encrypt(value), clock.now().isoformat()),
        )

    def get(self, name: str) -> Secret | None:
        row = self._db.one("SELECT ciphertext FROM app_secrets WHERE name = ?", (name,))
        return self._cipher.decrypt(row["ciphertext"]) if row else None

    def delete(self, name: str) -> None:
        self._db.execute("DELETE FROM app_secrets WHERE name = ?", (name,))

    def names(self) -> list[str]:
        return [r["name"] for r in self._db.query("SELECT name FROM app_secrets ORDER BY name")]
