"""The nightly backup, as a scheduler job.

It runs hourly but only backs up when the last good backup is more than 23
hours old, so a restart never skips a night or doubles one. Each attempt is
recorded in `backup_runs`. If backups keep failing and the last good one is
over two days old, the admins get one message a day about it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from themi import clock
from themi.accounts import AccountStore, Role
from themi.backup.snapshots import Backups
from themi.channels.outbox import Outbox, Priority
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

EVERY = timedelta(hours=23)
WARN_AFTER = timedelta(days=2)
FAILING_TEXT = (
    "Themi's nightly backups haven't worked since {since}. The server log has the details; "
    "`themi backup` on the server tries one by hand."
)


class BackupJob:
    def __init__(self, store: AccountStore, backups: Backups, outbox: Outbox | None) -> None:
        """`outbox` None: nobody is told about failures (a by-hand `themi backup`)."""
        self.store = store
        self.db = store.db
        self.backups = backups
        self.outbox = outbox

    def last_success(self) -> datetime | None:
        value = self.db.scalar("SELECT MAX(finished_at) FROM backup_runs WHERE status = 'ok'")
        return datetime.fromisoformat(value) if value else None

    async def run(self) -> str:
        """Scheduler job. Returns what happened, for the log."""
        last = self.last_success()
        if last is not None and clock.now() - last < EVERY:
            return "not due"
        return await self.backup_now()

    async def backup_now(self) -> str:
        run_id = self.db.execute(
            "INSERT INTO backup_runs (started_at) VALUES (?)", (to_utc_iso(clock.now()),)
        )
        try:
            snapshot = await self.backups.create(self.db)
            pruned = await self.backups.prune()
        except Exception as exc:
            log.exception("The nightly backup failed")
            self.db.execute(
                "UPDATE backup_runs SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
                (to_utc_iso(clock.now()), f"{type(exc).__name__}: {exc}"[:500], run_id),
            )
            await self._warn_if_stale()
            return "failed"
        self.db.execute(
            "UPDATE backup_runs SET status = 'ok', finished_at = ?, snapshot = ?, size = ?, "
            "pruned = ? WHERE id = ?",
            (to_utc_iso(clock.now()), snapshot.key, snapshot.size, len(pruned), run_id),
        )
        return f"saved {snapshot.key}"

    async def _warn_if_stale(self) -> None:
        if self.outbox is None:
            return
        last = self.last_success()
        first = self.db.scalar("SELECT MIN(started_at) FROM backup_runs")
        since = last or (datetime.fromisoformat(first) if first else clock.now())
        if clock.now() - since < WARN_AFTER:
            return
        when = since.date().isoformat() if last else "they started"
        for member in self.store.list_members():
            if member.role is not Role.ADMIN:
                continue
            await self.outbox.send(
                member,
                FAILING_TEXT.format(since=when),
                priority=Priority.NORMAL,
                kind="system",
                dedupe_key=f"backup-failing:{clock.now().date().isoformat()}",
            )
