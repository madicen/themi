"""Encrypted database snapshots in S3-compatible storage, kept for 30 days.

A snapshot is the live database copied with SQLite's online backup, gzipped,
then encrypted with the server's secret key (Fernet: AES with an HMAC, so a
tampered or wrong-key file is refused rather than half-restored). Without
THEMI_SECRET_KEY a snapshot is unreadable, so that key must be kept somewhere
safe away from the server.

Names sort by time: `<prefix>themi-20261025T031500Z.sqlite.gz.enc`.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from themi import clock
from themi.backup.s3 import S3Client, S3Config, S3Object
from themi.storage.db import Database
from themi.storage.migrations import latest_version
from themi.storage.secrets import Cipher

log = logging.getLogger(__name__)

NAME = re.compile(r"themi-(\d{8}T\d{6}Z)\.sqlite\.gz\.enc$")
COUNTED_TABLES = ("members", "tasks", "rules", "memory_facts", "emails", "pantry_items")


class BackupError(Exception):
    """Something to tell whoever is running the backup or restore, in plain words."""


@dataclass(frozen=True)
class BackupConfig:
    s3: S3Config
    prefix: str = "themi/"
    keep_days: int = 30


@dataclass(frozen=True)
class Snapshot:
    key: str
    taken_at: datetime
    size: int


@dataclass(frozen=True)
class RestoreReport:
    snapshot: Snapshot
    schema_version: int
    integrity: str
    counts: dict[str, int] = field(default_factory=dict)
    restored_to: Path | None = None
    previous_moved_to: Path | None = None


def snapshot_from(obj: S3Object) -> Snapshot | None:
    match = NAME.search(obj.key)
    if match is None:
        return None
    taken = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return Snapshot(obj.key, taken, obj.size)


def to_prune(snapshots: list[Snapshot], now: datetime, keep_days: int) -> list[Snapshot]:
    """Snapshots older than `keep_days`, but never the newest one, whatever its age."""
    if not snapshots:
        return []
    newest = max(snapshots, key=lambda s: s.taken_at)
    cutoff = now - timedelta(days=keep_days)
    return [s for s in snapshots if s.taken_at < cutoff and s is not newest]


def seal(db: Database, cipher: Cipher) -> bytes:
    """The database, consistent, compressed and encrypted."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "snapshot.db"
        db.backup_to(copy)
        return cipher.encrypt_bytes(gzip.compress(copy.read_bytes(), compresslevel=6))


def unseal(data: bytes, cipher: Cipher) -> bytes:
    try:
        return gzip.decompress(cipher.decrypt_bytes(data))
    except (OSError, EOFError) as exc:
        raise BackupError("the snapshot decrypted but isn't a compressed database") from exc


def inspect(path: Path) -> tuple[int, str, dict[str, int]]:
    """Schema version, integrity check result and some row counts of a database file."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        try:
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_version"
            ).fetchone()[0]
        except sqlite3.Error:
            version = 0
        counts = {}
        for table in COUNTED_TABLES:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                continue
        return version, integrity, counts
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"the snapshot isn't a readable database ({exc})") from exc
    finally:
        conn.close()


class Backups:
    def __init__(
        self, config: BackupConfig, cipher: Cipher, client: S3Client | None = None
    ) -> None:
        self.config = config
        self.cipher = cipher
        self.client = client or S3Client(config.s3)

    async def snapshots(self) -> list[Snapshot]:
        found = [snapshot_from(o) for o in await self.client.list(self.config.prefix)]
        return sorted((s for s in found if s is not None), key=lambda s: s.taken_at)

    async def create(self, db: Database) -> Snapshot:
        data = await asyncio.to_thread(seal, db, self.cipher)
        now = clock.now().astimezone(UTC)
        key = f"{self.config.prefix}themi-{now.strftime('%Y%m%dT%H%M%SZ')}.sqlite.gz.enc"
        await self.client.put(key, data)
        log.info("Backed up the database to %s (%d bytes)", key, len(data))
        return Snapshot(key, now.replace(microsecond=0), len(data))

    async def prune(self) -> list[Snapshot]:
        old = to_prune(await self.snapshots(), clock.now(), self.config.keep_days)
        for snapshot in old:
            await self.client.delete(snapshot.key)
        if old:
            log.info("Pruned %d snapshots older than %d days", len(old), self.config.keep_days)
        return old

    async def find(self, name: str) -> Snapshot:
        snapshots = await self.snapshots()
        if not snapshots:
            raise BackupError("there are no snapshots in the backup storage yet")
        if name == "latest":
            return snapshots[-1]
        for snapshot in snapshots:
            if (
                snapshot.key == name
                or snapshot.key.endswith(f"/{name}")
                or snapshot.key.endswith(name)
            ):
                return snapshot
        raise BackupError(f"no snapshot called {name!r} (`themi backup --list` shows them)")

    async def restore(self, name: str, target: Path, *, dry_run: bool) -> RestoreReport:
        """Fetch, decrypt and check a snapshot; unless `dry_run`, put it in place of `target`.

        The current database (if any) is moved aside, never deleted. Themi must be stopped
        first: a running server keeps the old file open.
        """
        snapshot = await self.find(name)
        data = unseal(await self.client.get(snapshot.key), self.cipher)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".restoring", delete=False) as f:
            f.write(data)
            staged = Path(f.name)
        try:
            version, integrity, counts = inspect(staged)
            if integrity != "ok":
                raise BackupError(f"the snapshot failed SQLite's integrity check: {integrity}")
            if version > latest_version():
                raise BackupError(
                    f"the snapshot is from a newer Themi (schema {version}, this one knows "
                    f"{latest_version()}); upgrade first, then restore"
                )
            report = RestoreReport(snapshot, version, integrity, counts)
            if dry_run:
                return report
            moved = None
            if target.exists():
                stamp = clock.now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
                moved = target.with_name(f"{target.name}.before-restore-{stamp}")
                target.rename(moved)
            for suffix in ("-wal", "-shm"):  # the old file's journal must not replay onto the new
                Path(f"{target}{suffix}").unlink(missing_ok=True)
            staged.rename(target)
            return RestoreReport(snapshot, version, integrity, counts, target, moved)
        finally:
            staged.unlink(missing_ok=True)
