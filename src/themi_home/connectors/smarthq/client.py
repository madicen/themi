"""SmartHQ: the family's GE range, through the unofficial `gehomesdk` library (OV2).

GE has a developer API, but access isn't open; `gehomesdk` (MIT, the library behind Home
Assistant's `ge_home`; 2026.8.0, run against the family's CHS950P2M9S1 in OV1) signs in
with the SmartHQ app account and keeps a websocket open to GE's cloud, which pushes every
change. A SmartHQ account may ask for a code it emails during sign-in.

Themi keeps the library behind two small seams, as it does Roborock's: `SmartHQLogin` (the
sign-in) and `SmartHQSession` (the range, once signed in), both speaking raw ERDs (see
`events`). `library.py` is the real one (`themi[smarthq]`); tests use
`tests/fakes/smarthq.py`.

`SmartHQAccount` keeps the family's one sign-in: the email, the region, the password
(Michael's decision, 2026-11-15: GE's own API stays the later swap) and the refresh token
the library rotates, the last two encrypted and never logged. A reconnect uses the refresh
token, so it doesn't ask for a new emailed code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

REGIONS = ("US", "EU")


class SmartHQError(Exception):
    """SmartHQ couldn't be reached or said no; Themi tries again later."""


class SignInLost(SmartHQError):
    """The sign-in stopped working: linking again on the Accounts page fixes it."""


class BadCode(SmartHQError):
    """The emailed code was wrong or too old."""


class RangeOffline(SmartHQError):
    """The range isn't reachable right now (its WiFi, or GE's cloud)."""


@dataclass(frozen=True)
class Range:
    mac: str  # SmartHQ's appliance id
    model: str  # "CHS950P2M9S1"


@dataclass(frozen=True)
class SignIn:
    """A sign-in's first step: done (`token`), or waiting on the code SmartHQ emailed."""

    token: str | None = None  # the refresh token
    code_sent: bool = False


class SmartHQSession(Protocol):
    """The family's range, signed in. Reads come from what the range last pushed."""

    async def ranges(self) -> list[Range]: ...

    async def erds(self, mac: str) -> dict[str, str]:
        """Every ERD the range last sent, by code ("0x5101") as raw hex."""
        ...

    async def write(self, mac: str, erd: str, value: str) -> None:
        """Send one ERD's raw hex. The range answers by pushing its new state (or not)."""
        ...

    def refresh_token(self) -> str | None:
        """The newest refresh token (the library rotates it)."""
        ...

    async def close(self) -> None: ...


class SmartHQLogin(Protocol):
    """Signing in to the SmartHQ app account."""

    async def sign_in(self, email: str, password: str, region: str) -> SignIn: ...

    async def submit_code(self, email: str, code: str) -> str:
        """The emailed code traded for a refresh token."""
        ...

    async def open(self, email: str, region: str, refresh_token: str) -> SmartHQSession: ...

    async def settle(self, seconds: float) -> None:
        """Give the range time to answer a write (the real one waits on `themi.clock`; the
        fake moves its frozen clock on)."""
        ...


class SmartHQAccount:
    """The family's SmartHQ sign-in. Admins link it; the range's two ovens share it."""

    def __init__(self, db: Database, cipher: Cipher, login: SmartHQLogin) -> None:
        self.db = db
        self.cipher = cipher
        self.login = login
        self._session: SmartHQSession | None = None
        self._pending: dict[str, tuple[str, Secret]] = {}  # email -> region, password

    def linked(self) -> bool:
        return self._row() is not None

    def email(self) -> str | None:
        row = self._row()
        return str(row["email"]) if row else None

    def problem(self) -> str | None:
        row = self._row()
        return str(row["problem"]) if row and row["problem"] else None

    async def sign_in(self, member: Member, email: str, password: str, region: str) -> SignIn:
        """The first step. Returns `code_sent` when SmartHQ emailed a code to finish with."""
        email, region = _email(email), _region(region)
        if not password:
            raise SmartHQError("Enter the SmartHQ password.")
        step = await self.login.sign_in(email, password, region)
        if step.token is None:
            self._pending[email] = (region, Secret(password))
        else:
            await self._keep(member, email, region, Secret(password), step.token)
        return step

    async def submit_code(self, member: Member, email: str, code: str) -> None:
        email, code = _email(email), code.strip()
        if email not in self._pending:
            raise BadCode("That sign-in has ended; start again.")
        if not code:
            raise BadCode("Enter the code SmartHQ emailed.")
        token = await self.login.submit_code(email, code)
        region, password = self._pending.pop(email)
        await self._keep(member, email, region, password, token)

    async def _keep(
        self, member: Member, email: str, region: str, password: Secret, token: str
    ) -> None:
        session = await self.login.open(email, region, token)
        try:
            await session.ranges()  # the sign-in works before it's kept
        except BaseException:
            await session.close()
            raise
        self.db.execute(
            "INSERT INTO smarthq_account (id, email, region, password, refresh_token, problem, "
            "linked_by, linked_at) VALUES (1, ?, ?, ?, ?, NULL, ?, ?) ON CONFLICT(id) DO "
            "UPDATE SET email = excluded.email, region = excluded.region, "
            "password = excluded.password, refresh_token = excluded.refresh_token, "
            "problem = NULL, linked_by = excluded.linked_by, linked_at = excluded.linked_at",
            (
                email,
                region,
                self.cipher.encrypt(password),
                self.cipher.encrypt(Secret(session.refresh_token() or token)),
                member.id,
                _now(),
            ),
        )
        await self.close()
        self._session = session

    async def unlink(self) -> None:
        self.db.execute("DELETE FROM smarthq_account")
        self.db.execute("DELETE FROM ovens")
        await self.close()

    async def session(self) -> SmartHQSession:
        """The signed-in session, opened from the stored refresh token when needed."""
        if self._session is None:
            row = self._row()
            if row is None:
                raise SignInLost("The range isn't linked.")
            if row["problem"]:
                raise SignInLost(str(row["problem"]))
            token = self.cipher.decrypt(row["refresh_token"]).reveal()
            self._session = await self.login.open(str(row["email"]), str(row["region"]), token)
        return self._session

    def keep_token(self) -> None:
        """The library handed out a new refresh token: keep it, so a restart can reconnect."""
        if self._session is None:
            return
        token = self._session.refresh_token()
        row = self._row()
        if token is None or row is None:
            return
        if self.cipher.decrypt(row["refresh_token"]).reveal() != token:
            self.db.execute(
                "UPDATE smarthq_account SET refresh_token = ? WHERE id = 1",
                (self.cipher.encrypt(Secret(token)),),
            )

    def lost(self, why: str) -> bool:
        """The sign-in stopped working: kept as the problem until linked again. True the
        first time (so an admin hears once)."""
        row = self._row()
        if row is None or row["problem"]:
            return False
        self.db.execute("UPDATE smarthq_account SET problem = ? WHERE id = 1", (why,))
        return True

    async def close(self) -> None:
        if self._session is not None:
            session, self._session = self._session, None
            try:
                await session.close()
            except Exception:
                log.exception("Closing the SmartHQ session failed")

    def _row(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM smarthq_account WHERE id = 1")


def _email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email:
        raise SmartHQError("Enter the email address the SmartHQ app signs in with.")
    return email


def _region(region: str) -> str:
    region = (region or "US").strip().upper()
    if region not in REGIONS:
        raise SmartHQError("The region is US or EU.")
    return region


def _now() -> str:
    return to_utc_iso(clock.now())
