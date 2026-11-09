"""SP7a: claiming a new Themi on its website, instead of `themi init` in a terminal.

While there's no family, Themi makes a one-time code when it starts, says it in its log
and writes it to `claim-code` next to the database (readable only by its owner). Whoever
enters it on the website names the household and becomes its first admin. Without the
code, whoever reached a public site first could take it over.

A few wrong tries lock the code for a while. Once used, it's gone.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from themi import clock
from themi.accounts.models import Member, Role
from themi.accounts.store import SYSTEM, AccountsError, AccountStore, InvalidValue
from themi.localtime import to_utc_iso

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: read off a log, typed by hand
CODE_FILE = "claim-code"
WRONG_TRIES = 5
LOCKED_FOR = timedelta(minutes=10)


class ClaimError(Exception):
    """What to tell the person, in plain words."""


def _hash(code: str) -> str:
    return hashlib.sha256(_plain(code).encode()).hexdigest()


def _plain(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())


class Claim:
    def __init__(self, store: AccountStore) -> None:
        self.store = store
        self.db = store.db

    def needed(self) -> bool:
        return self.store.get_family() is None

    def make(self, folder: Path) -> str:
        """A new code (any older one stops working), written to `folder/claim-code`."""
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        code = f"{code[:4]}-{code[4:]}"
        self.db.execute(
            "INSERT INTO claim (id, code_hash, created_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET code_hash = excluded.code_hash, "
            "created_at = excluded.created_at, used_at = NULL, used_by = NULL, "
            "wrong_tries = 0, locked_until = NULL",
            (_hash(code), to_utc_iso(clock.now())),
        )
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / CODE_FILE
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(code + "\n")
        return code

    def check(self, code: str) -> None:
        """Raises ClaimError unless `code` is the one waiting. A wrong one counts."""
        row = self.db.one("SELECT * FROM claim WHERE id = 1")
        if row is None or row["used_at"] is not None or not self.needed():
            raise ClaimError("This Themi has been claimed already. Sign in instead.")
        now = clock.now()
        if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now:
            raise ClaimError("Too many wrong codes. Wait ten minutes, then try again.")
        if hmac.compare_digest(row["code_hash"], _hash(code)):
            return
        tries = row["wrong_tries"] + 1
        locked = to_utc_iso(now + LOCKED_FOR) if tries >= WRONG_TRIES else None
        self.db.execute(
            "UPDATE claim SET wrong_tries = ?, locked_until = ? WHERE id = 1",
            (0 if locked else tries, locked),
        )
        raise ClaimError(
            "That isn't the code. It's in Themi's log, and in the claim-code file next to its data."
        )

    def claim(
        self,
        code: str,
        household: str,
        timezone: str,
        name: str,
        folder: Path | None,
        template: str = "family",
    ) -> Member:
        """Use the code: the household (on `template`) and its first admin. `folder`:
        where the code's file is, to delete it."""
        from themi.accounts.setup import _timezone

        household, name = household.strip(), name.strip()
        if not household or not name:
            raise ClaimError("Give this Themi a name, and say your own.")
        try:
            timezone = _timezone(timezone.strip())
        except InvalidValue as exc:
            raise ClaimError(str(exc)) from exc
        self.check(code)
        try:
            with self.db.transaction():
                self.store.create_family(household, timezone, template)
                admin = self.store.create_member(SYSTEM, name, Role.ADMIN)
                self.db.execute(
                    "UPDATE claim SET used_at = ?, used_by = ? WHERE id = 1",
                    (to_utc_iso(clock.now()), admin.id),
                )
        except AccountsError as exc:
            raise ClaimError(str(exc)) from exc
        if folder is not None:
            (folder / CODE_FILE).unlink(missing_ok=True)
        return admin

    # ----- the key Themi made ---------------------------------------------------------

    def claimant(self) -> int | None:
        return self.db.scalar("SELECT used_by FROM claim WHERE id = 1 AND used_at IS NOT NULL")

    def key_saved(self) -> bool:
        return self.db.scalar("SELECT key_saved_at FROM claim WHERE id = 1") is not None

    def note_key_saved(self) -> None:
        self.db.execute(
            "UPDATE claim SET key_saved_at = ? WHERE id = 1", (to_utc_iso(clock.now()),)
        )
