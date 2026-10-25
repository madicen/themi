"""Where Themi's events go, and writing them there idempotently.

- The target is a calendar called "Themi" (configurable) on an admin's linked
  account: the one chosen on the Family page, or else the first admin's first
  linked account that granted the calendar scopes. It's found by name in the
  calendar list, or made if missing, and remembered in `calendars`.
- `upsert()` writes an event under a deterministic id. It updates first; if
  the event doesn't exist it inserts, and if the insert collides (an event
  with that id was deleted) it updates again, which restores it.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from themi.accounts import AccountStore, LinkedAccount, Role
from themi.connectors.gcal.client import CalendarClient, CalendarConflict, CalendarNotFound
from themi.connectors.google import CALENDAR_SCOPES, GoogleAccounts

log = logging.getLogger(__name__)

DEFAULT_NAME = "Themi"


class CalendarSetupError(Exception):
    """No account can hold the family calendar yet; something to tell an admin."""


@dataclass(frozen=True)
class CalendarTarget:
    account: LinkedAccount
    calendar_id: str


def event_id(source: str, source_id: int, family_seed: str) -> str:
    """A stable Google Calendar event id: lowercase base32hex characters (0-9, a-v).

    The family seed keeps two installs that share a calendar from colliding.
    """
    salt = hashlib.sha256(family_seed.encode()).hexdigest()[:10]
    return f"themi{salt}{source[0]}{source_id}"


class CalendarSync:
    def __init__(self, store: AccountStore, google: GoogleAccounts) -> None:
        self.store = store
        self.db = store.db
        self.google = google

    def client(self, account_id: int) -> CalendarClient:
        return CalendarClient(
            self.google.oauth.config.calendar_url,
            lambda: self.google.access_token(account_id),
            lambda: self.google.forget_access_token(account_id),
        )

    # ----- settings -----------------------------------------------------------

    def settings(self) -> tuple[int | None, str]:
        row = self.db.one("SELECT calendar_account_id, calendar_name FROM family WHERE id = 1")
        if row is None:
            return None, DEFAULT_NAME
        return row["calendar_account_id"], row["calendar_name"] or DEFAULT_NAME

    def eligible_accounts(self) -> list[LinkedAccount]:
        """Admins' linked accounts, in order; the ones allowed to hold the calendar."""
        admins = [m for m in self.store.list_members() if m.role is Role.ADMIN]
        return [a for m in admins for a in self.store.linked_accounts(m.id)]

    def account(self) -> LinkedAccount | None:
        """The account events go to, if one can take them."""
        chosen, _ = self.settings()
        accounts = [a for a in self.eligible_accounts() if a.enabled]
        if chosen is not None:
            accounts = [a for a in accounts if a.id == chosen]
        ready = [a for a in accounts if a.allows(*CALENDAR_SCOPES)]
        return ready[0] if ready else None

    def problem(self) -> str | None:
        """Why events can't be written right now, in words for an admin."""
        if self.account() is not None:
            return None
        chosen, _ = self.settings()
        accounts = [a for a in self.eligible_accounts() if chosen is None or a.id == chosen]
        if not accounts:
            return "No admin has linked a Google account yet, so there's no calendar to write to."
        if not any(a.enabled for a in accounts):
            return f"Google stopped accepting {accounts[0].address}; linking it again fixes it."
        return (
            f"{accounts[0].address} was linked before Themi asked for calendar access. "
            "Linking it again (My accounts) adds it."
        )

    def choose(self, account_id: int | None, name: str) -> None:
        name = " ".join(name.split())[:100] or DEFAULT_NAME
        if account_id is not None and account_id not in {a.id for a in self.eligible_accounts()}:
            raise ValueError("the calendar can only live on an admin's linked account")
        self.db.execute(
            "UPDATE family SET calendar_account_id = ?, calendar_name = ? WHERE id = 1",
            (account_id, name),
        )

    # ----- the calendar -------------------------------------------------------

    async def target(self) -> CalendarTarget:
        account = self.account()
        if account is None:
            raise CalendarSetupError(self.problem() or "no calendar account")
        _, name = self.settings()
        known = self.db.one(
            "SELECT calendar_id FROM calendars WHERE account_id = ? AND name = ?",
            (account.id, name),
        )
        if known:
            return CalendarTarget(account, known["calendar_id"])
        client = self.client(account.id)
        found = next(
            (
                c["id"]
                for c in await client.calendars()
                if str(c.get("summary", "")).strip().lower() == name.lower()
                and c.get("accessRole") in ("owner", "writer")
            ),
            None,
        )
        created = found is None
        if found is None:
            family = self.store.get_family()
            made = await client.create_calendar(name, family.timezone if family else "UTC")
            found = str(made["id"])
            log.info("Made the %r calendar on linked account %s", name, account.id)
        self.db.execute(
            "INSERT OR REPLACE INTO calendars (account_id, name, calendar_id, created_by_themi) "
            "VALUES (?, ?, ?, ?)",
            (account.id, name, found, int(created)),
        )
        return CalendarTarget(account, found)

    # ----- events -------------------------------------------------------------

    async def upsert(
        self, account_id: int, calendar_id: str, event_id: str, event: dict[str, Any]
    ) -> None:
        client = self.client(account_id)
        body = {**event, "id": event_id, "status": "confirmed"}
        try:
            await client.update_event(calendar_id, event_id, body)
            return
        except CalendarNotFound:
            pass
        try:
            await client.insert_event(calendar_id, body)
        except CalendarConflict:
            await client.update_event(calendar_id, event_id, body)

    async def delete(self, account_id: int, calendar_id: str, event_id: str) -> None:
        await self.client(account_id).delete_event(calendar_id, event_id)
