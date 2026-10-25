"""Polling each linked Gmail account, and announcing new mail.

- First run: the inbox's last `INITIAL_SYNC_DAYS` days. The profile's history
  id is read before listing, so nothing that arrives meanwhile is missed.
- After that: `history.list` from the stored history id. The stored id moves
  only once every page has been read, so an interrupted sync resumes from where
  it last finished; mail already stored is never announced twice.
- A history id Gmail no longer has (about a week old) means a fresh first run.
- Every account is polled on its own: an error, rate limit or dead token for
  one never holds up the others. Errors back off; Gmail's Retry-After is honoured.
- A token Google no longer accepts disables the account and tells its owner,
  once, through the outbox. Linking it again clears that.

Each new message is stored in `emails` and passed to every `listeners`
callback as an `EmailReceived` (triage subscribes in prompt 23).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from themi import clock
from themi.accounts import AccountStore, LinkedAccount
from themi.channels.outbox import Outbox, Priority
from themi.connectors.gmail.client import (
    GmailAuthError,
    GmailClient,
    GmailError,
    HistoryExpired,
    RateLimited,
)
from themi.connectors.gmail.parse import GmailMessage, parse_message
from themi.connectors.google import GoogleAccounts, TokenRevoked
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

INITIAL_SYNC_DAYS = 7
INITIAL_SYNC_LIMIT = 200
POLL_EVERY = timedelta(minutes=3)
ERROR_BACKOFF = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
)
RELINK_ALERT = (
    "Themi can't read {address} any more: Google stopped accepting its link. Sending "
    "/link gmail and choosing that address again would fix it, whenever it suits."
)


@dataclass(frozen=True)
class EmailReceived:
    account: LinkedAccount
    email_id: int  # row in `emails`
    message: GmailMessage
    initial: bool  # found by a first sync (older mail), not newly arrived

    @property
    def member_id(self) -> int:
        return self.account.member_id


EmailListener = Callable[[EmailReceived], Awaitable[None]]


class GmailSync:
    def __init__(self, store: AccountStore, google: GoogleAccounts, outbox: Outbox) -> None:
        self.store = store
        self.db = store.db
        self.google = google
        self.outbox = outbox
        self.listeners: list[EmailListener] = []

    def client(self, account_id: int) -> GmailClient:
        return GmailClient(
            self.google.oauth.config.gmail_url,
            lambda: self.google.access_token(account_id),
            lambda: self.google.forget_access_token(account_id),
        )

    # ----- scheduling ---------------------------------------------------------

    def due_accounts(self) -> list[LinkedAccount]:
        now = to_utc_iso(clock.now())
        rows = self.db.query(
            "SELECT id FROM linked_accounts WHERE provider = 'gmail' AND watched = 1 "
            "AND enabled = 1 AND (poll_after IS NULL OR poll_after <= ?) ORDER BY id",
            (now,),
        )
        return [self.store.get_linked_account(r["id"]) for r in rows]

    async def poll_all(self) -> int:
        """Scheduler job: sync every account that's due. Returns new messages found."""
        found = 0
        for account in self.due_accounts():
            found += await self.poll(account)
        return found

    async def poll(self, account: LinkedAccount) -> int:
        """Sync one account; never raises. Returns how many new messages it found."""
        try:
            found = await self._sync(account)
        except (TokenRevoked, GmailAuthError):
            await self._lost_access(account)
            return 0
        except RateLimited as exc:
            wait = timedelta(seconds=exc.retry_after) if exc.retry_after else None
            self._back_off(account, wait)
            log.info("Gmail rate-limited account %s; waiting", account.id)
            return 0
        except GmailError as exc:
            self._back_off(account)
            log.warning("Syncing Gmail account %s failed: %s", account.id, exc)
            return 0
        except Exception:
            self._back_off(account)
            log.exception("Syncing Gmail account %s failed unexpectedly", account.id)
            return 0
        self.db.execute(
            "UPDATE linked_accounts SET last_synced_at = ?, poll_after = ?, poll_failures = 0 "
            "WHERE id = ?",
            (to_utc_iso(clock.now()), to_utc_iso(clock.now() + POLL_EVERY), account.id),
        )
        return found

    def _back_off(self, account: LinkedAccount, wait: timedelta | None = None) -> None:
        failures = self.db.scalar(
            "SELECT poll_failures FROM linked_accounts WHERE id = ?", (account.id,)
        )
        delay = wait if wait is not None else ERROR_BACKOFF[min(failures, len(ERROR_BACKOFF) - 1)]
        self.db.execute(
            "UPDATE linked_accounts SET poll_failures = poll_failures + 1, poll_after = ? "
            "WHERE id = ?",
            (to_utc_iso(clock.now() + max(delay, POLL_EVERY)), account.id),
        )

    async def _lost_access(self, account: LinkedAccount) -> None:
        self.store.set_linked_account_enabled(account.id, False)
        already = self.db.scalar(
            "SELECT alerted_at FROM linked_accounts WHERE id = ?", (account.id,)
        )
        if already:
            return
        self.db.execute(
            "UPDATE linked_accounts SET alerted_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), account.id),
        )
        member = self.store.get_member(account.member_id)
        await self.outbox.send(
            member,
            RELINK_ALERT.format(address=account.address),
            priority=Priority.NORMAL,
            kind="system",  # once per loss: `alerted_at` is cleared only by linking again
        )
        log.warning("Lost access to Gmail account %s; told its owner", account.id)

    # ----- syncing ------------------------------------------------------------

    async def _sync(self, account: LinkedAccount) -> int:
        history_id = self.db.scalar(
            "SELECT history_id FROM linked_accounts WHERE id = ?", (account.id,)
        )
        if history_id is None:
            return await self._initial(account)
        try:
            return await self._incremental(account, history_id)
        except HistoryExpired:
            log.info("Gmail history for account %s expired; resyncing", account.id)
            return await self._initial(account)

    async def _initial(self, account: LinkedAccount) -> int:
        client = self.client(account.id)
        start = str((await client.profile())["historyId"])
        ids: list[str] = []
        page: str | None = None
        while len(ids) < INITIAL_SYNC_LIMIT:
            batch, page = await client.list_messages(
                f"newer_than:{INITIAL_SYNC_DAYS}d", page_token=page
            )
            ids.extend(batch)
            if not page:
                break
        found = 0
        for message_id in reversed(ids[:INITIAL_SYNC_LIMIT]):  # oldest first
            found += await self._take(account, client, message_id, initial=True)
        self._set_history(account, start)
        return found

    async def _incremental(self, account: LinkedAccount, history_id: str) -> int:
        client = self.client(account.id)
        found, page, latest = 0, None, history_id
        while True:
            result = await client.history(history_id, page_token=page)
            for message_id in result.added:
                found += await self._take(account, client, message_id, initial=False)
            latest = result.history_id
            page = result.next_page
            if not page:
                break
        self._set_history(account, latest)
        return found

    def _set_history(self, account: LinkedAccount, history_id: str) -> None:
        self.db.execute(
            "UPDATE linked_accounts SET history_id = ? WHERE id = ?", (history_id, account.id)
        )

    async def _take(
        self, account: LinkedAccount, client: GmailClient, message_id: str, *, initial: bool
    ) -> int:
        if self.db.one(
            "SELECT 1 FROM emails WHERE account_id = ? AND gmail_id = ?", (account.id, message_id)
        ):
            return 0
        raw = await client.get_message(message_id)
        if raw is None:  # deleted before we got to it
            return 0
        message = parse_message(raw)
        email_id = self._store(account, message)
        if email_id is None:
            return 0
        event = EmailReceived(account, email_id, message, initial)
        for listener in self.listeners:
            try:
                await listener(event)
            except Exception:
                log.exception("An EmailReceived listener failed for email %s", email_id)
        return 1

    def _store(self, account: LinkedAccount, m: GmailMessage) -> int | None:
        before = self.db.scalar("SELECT total_changes()")
        email_id = self.db.execute(
            "INSERT OR IGNORE INTO emails (account_id, gmail_id, thread_id, message_id_header, "
            "from_address, from_name, to_addresses, subject, snippet, body_text, labels, "
            "attachments, received_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                account.id,
                m.id,
                m.thread_id,
                m.message_id_header or None,
                m.from_address,
                m.from_name,
                json.dumps(list(m.to)),
                m.subject,
                m.snippet,
                m.text,
                json.dumps(list(m.label_ids)),
                json.dumps(
                    [
                        {"filename": a.filename, "mime_type": a.mime_type, "size": a.size}
                        for a in m.attachments
                    ]
                ),
                to_utc_iso(m.received_at),
                to_utc_iso(clock.now()),
            ),
        )
        if self.db.scalar("SELECT total_changes()") == before:
            return None  # stored by a concurrent poll
        return email_id

    # ----- reading back -------------------------------------------------------

    def email(self, email_id: int) -> dict | None:
        return self.db.one("SELECT * FROM emails WHERE id = ?", (email_id,))

    def last_synced(self, account_id: int) -> datetime | None:
        value = self.db.scalar(
            "SELECT last_synced_at FROM linked_accounts WHERE id = ?", (account_id,)
        )
        return datetime.fromisoformat(value) if value else None
