"""Roborock: the robot vacuum, through the unofficial `python-roborock` library (V1).

Roborock publishes no developer API. `python-roborock` (Apache-2.0, the library behind Home
Assistant's Roborock integration; 7.15.1, read 2026-11-01) signs in with the Roborock app
account by a code emailed to it, then reaches each robot over the LAN when it answers
there and through Roborock's cloud MQTT otherwise; it picks by itself. The S8 MaxV Ultra
is `roborock.vacuum.a97`, a V1-protocol vacuum, which the library supports.

The library is optional (`themi[roborock]`) and brings its own HTTP and MQTT, so Themi
keeps it behind two small seams: `RoborockLogin` (the sign-in) and `RoborockSession` (the
robots, once signed in). `library.py` is the real one; tests use `tests/fakes/roborock.py`.

`RoborockAccount` keeps the family's one sign-in: the email, and the login data the library
returns (its tokens and the keys it talks to the robots with), encrypted, never logged.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from themi import clock
from themi.accounts import Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)


class RoborockError(Exception):
    """Roborock couldn't be reached or said no; the job tries again later."""


class LoginExpired(RoborockError):
    """The sign-in no longer works: linking again on the Accounts page fixes it."""


class BadCode(RoborockError):
    """The emailed code was wrong or too old."""


class RobotOffline(RoborockError):
    """The robot isn't reachable right now."""


@dataclass(frozen=True)
class VacuumDevice:
    duid: str  # Roborock's device id
    name: str  # as named in the Roborock app
    model: str  # "roborock.vacuum.a97" for the S8 MaxV Ultra


class RoborockSession(Protocol):
    """The family's robots, signed in."""

    async def devices(self) -> list[VacuumDevice]: ...

    async def status(self, duid: str) -> dict[str, Any]:
        """The robot's status as it reports it (get_status: `state`, `error_code`,
        `dock_error_status`, `battery`, `dss`, ...), read now. `events.read_status` reads it."""
        ...

    async def consumables(self, duid: str) -> dict[str, int]:
        """The parts' counters (get_consumable: `filter_work_time`, ...), read now."""
        ...

    async def room(self, duid: str) -> str | None:
        """The room the robot is in, by the Roborock app's room names, from its map."""
        ...

    async def resolve(self, duid: str, code: int) -> None:
        """Clear an alert, as "Resolved" in the Roborock app (a dock's water alert stays
        until it's cleared, even once the tank's refilled)."""
        ...

    async def send_home(self, duid: str) -> None:
        """Send it back to its dock (`app_charge`)."""
        ...

    async def close(self) -> None: ...


class RoborockLogin(Protocol):
    """Signing in to the Roborock app account."""

    async def request_code(self, email: str) -> None:
        """Roborock emails a code to the account."""
        ...

    async def code_login(self, email: str, code: str) -> dict[str, Any]:
        """The code traded for the library's login data (JSON-safe; secret)."""
        ...

    async def open(self, email: str, login: dict[str, Any]) -> RoborockSession: ...


class RoborockAccount:
    """The family's Roborock sign-in. Admins link it; its robots share it."""

    def __init__(self, db: Database, cipher: Cipher, login: RoborockLogin) -> None:
        self.db = db
        self.cipher = cipher
        self.login = login
        self._session: RoborockSession | None = None

    def linked(self) -> bool:
        return self._row() is not None

    def email(self) -> str | None:
        row = self._row()
        return str(row["email"]) if row else None

    def problem(self) -> str | None:
        """Why the robots can't be read, when the sign-in stopped working."""
        row = self._row()
        return str(row["problem"]) if row and row["problem"] else None

    async def send_code(self, email: str) -> str:
        email = email.strip().lower()
        if "@" not in email:
            raise RoborockError("Enter the email address the Roborock app signs in with.")
        await self.login.request_code(email)
        return email

    async def link(self, member: Member, email: str, code: str) -> list[VacuumDevice]:
        """Trade the code for the login data, list the robots with it, then keep it."""
        email, code = email.strip().lower(), code.strip()
        if not code:
            raise BadCode("Enter the code Roborock emailed.")
        login = await self.login.code_login(email, code)
        session = await self.login.open(email, login)
        try:
            found = await session.devices()
        except BaseException:
            await session.close()
            raise
        self.db.execute(
            "INSERT INTO roborock_account (id, email, login, problem, linked_by, linked_at) "
            "VALUES (1, ?, ?, NULL, ?, ?) ON CONFLICT(id) DO UPDATE SET email = excluded.email, "
            "login = excluded.login, problem = NULL, linked_by = excluded.linked_by, "
            "linked_at = excluded.linked_at",
            (email, self.cipher.encrypt(Secret(json.dumps(login))), member.id, _now()),
        )
        await self.close()
        self._session = session
        return found

    async def unlink(self) -> None:
        self.db.execute("DELETE FROM roborock_account")
        self.db.execute("DELETE FROM devices WHERE provider = 'roborock'")
        await self.close()

    async def session(self) -> RoborockSession:
        """The signed-in session, opened from the stored login when needed."""
        if self._session is None:
            row = self._row()
            if row is None:
                raise LoginExpired("Roborock isn't linked.")
            if row["problem"]:
                raise LoginExpired(str(row["problem"]))
            login = json.loads(self.cipher.decrypt(row["login"]).reveal())
            self._session = await self.login.open(str(row["email"]), login)
        return self._session

    def expired(self, why: str) -> bool:
        """The sign-in stopped working: kept as the problem until linked again. True the
        first time (so an admin hears once)."""
        row = self._row()
        if row is None or row["problem"]:
            return False
        self.db.execute("UPDATE roborock_account SET problem = ? WHERE id = 1", (why,))
        return True

    async def close(self) -> None:
        if self._session is not None:
            session, self._session = self._session, None
            try:
                await session.close()
            except Exception:
                log.exception("Closing the Roborock session failed")

    def _row(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM roborock_account WHERE id = 1")


def _now() -> str:
    return to_utc_iso(clock.now())
