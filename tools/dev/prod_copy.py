"""`make dev-prod` (D4, Michael's idea #136): dev on a copy of the family's real data.

The copy comes from the Pi over ssh (SQLite's backup into memory, so nothing is written
there), or from an encrypted backup with this computer's `.env` backup settings and key.
It lands in `data/dev-prod/`, apart from `data/dev/`.

Dev must never reach the family, so the copy is cleaned before it runs:
- every encrypted column is emptied: Gmail, Keep, ThinQ, Roborock and Home Connect links,
  household secrets and AI keys. A table whose row is nothing without its secret loses
  the row; Gmail links stay (their mail is useful) but are switched off;
- website sessions, sign-in links, invites and paired Safeway helpers are deleted;
- members 1 and 2 become the simulator's Erin and Husband; anyone else isn't paired.
The dev process also never gets the real secret key (it has its own, in the copy's
folder), so anything missed stays unreadable. Dev's own GEMINI_API_KEY goes on the
Gemini backends, as `make dev` does.

The copy holds the family's messages and email. `data/` is never committed, and
`make dev-reset` deletes it.
"""

from __future__ import annotations

import asyncio
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.fixtures.family import ERIN_TELEGRAM_ID, HUSBAND_TELEGRAM_ID
from themi import clock
from themi.accounts import SYSTEM, AccountStore
from themi.ai.settings import AISettingsStore
from themi.settings import Settings
from themi.storage import open_database
from themi.storage.secrets import Secret

COPY_KEY = "dev_prod_copy"  # in `meta`: where the copy came from, and when
SQLITE_HEADER = b"SQLite format 3\x00"
# Run in the Pi's container: a consistent copy, read-only, out through stdout.
DUMP = (
    "import os,sqlite3,sys;"
    's=sqlite3.connect("file:"+os.environ["THEMI_DB_PATH"]+"?mode=ro",uri=True);'
    'm=sqlite3.connect(":memory:");s.backup(m);sys.stdout.buffer.write(m.serialize())'
)
# Rows that let someone in, or something pair: gone from the copy.
SIGN_IN_COLUMNS = ("token_hash", "code_hash", "state_hash")
KEPT_LINKS = "linked_accounts"  # Gmail: switched off, so its mail stays
NOT_SECRET = frozenset({"embedding_cache"})  # vectors, not keys: kept, saving model calls

Run = Callable[..., subprocess.CompletedProcess[bytes]]


def from_pi(host: str, dest: Path, run: Run = subprocess.run) -> None:
    """The Pi's database, copied over ssh into `dest`."""
    remote = f"cd ~/themi && docker compose exec -T themi python -c '{DUMP}'"
    done = run(["ssh", "-o", "BatchMode=yes", host, remote], capture_output=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"Couldn't copy from {host}: {done.stderr.decode(errors='replace')}")
    if not done.stdout.startswith(SQLITE_HEADER):
        raise SystemExit(f"What came from {host} isn't a database: {done.stdout[:200]!r}")
    _fresh(dest)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(done.stdout)
    part.chmod(0o600)
    part.rename(dest)


def from_backup(name: str, dest: Path) -> None:
    """A snapshot from the encrypted backups ("latest" or a name from `themi backup
    --list`), with this computer's `.env` backup settings and secret key."""
    from themi.backup import Backups

    settings = Settings.load()
    if settings.backup is None:
        raise SystemExit("Backups aren't set up in .env (THEMI_BACKUP_*).")
    _fresh(dest)
    backups = Backups(settings.backup, settings.cipher())
    asyncio.run(backups.restore(name, dest, dry_run=False))


def _fresh(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for path in dest.parent.glob(f"{dest.name}*"):
        path.unlink()


def clean(path: Path, source: str = "") -> None:
    """Make the copy safe for dev (the module's docstring says what goes)."""
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys = OFF")
        for table in _tables(db):
            columns = db.execute(f'PRAGMA table_info("{table}")').fetchall()
            names = {c[1] for c in columns}
            if table in NOT_SECRET:
                continue
            if names & set(SIGN_IN_COLUMNS):
                db.execute(f'DELETE FROM "{table}"')
                continue
            for _, column, kind, not_null, _, _ in columns:
                if kind.upper() != "BLOB":
                    continue
                if not not_null:
                    db.execute(f'UPDATE "{table}" SET "{column}" = NULL')
                elif table == KEPT_LINKS:
                    db.execute(f'UPDATE "{table}" SET "{column}" = X\'\', enabled = 0, watched = 0')
                else:
                    db.execute(f'DELETE FROM "{table}"')
        _pair_with_the_simulator(db)
        db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (COPY_KEY, f"{source or 'a copy'}, {clock.now().isoformat(timespec='minutes')}"),
        )
        db.commit()
    finally:
        db.close()


def _tables(db: sqlite3.Connection) -> list[str]:
    """Ordinary tables: not SQLite's own, and not full-text search tables or theirs."""
    rows = db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    virtual = [n for n, sql in rows if (sql or "").upper().startswith("CREATE VIRTUAL")]
    return [
        name
        for name, _ in rows
        if not name.startswith("sqlite_")
        and not any(name == v or name.startswith(f"{v}_") for v in virtual)
    ]


def _pair_with_the_simulator(db: sqlite3.Connection) -> None:
    ids = [r[0] for r in db.execute("SELECT id FROM members ORDER BY id").fetchall()]
    db.execute("UPDATE members SET telegram_user_id = NULL")
    for member_id, telegram_id in zip(ids, (ERIN_TELEGRAM_ID, HUSBAND_TELEGRAM_ID), strict=False):
        db.execute("UPDATE members SET telegram_user_id = ? WHERE id = ?", (telegram_id, member_id))


def put_dev_key(settings: Settings, gemini_key: str) -> int:
    """Dev's Gemini key on every Gemini backend in the copy. Returns how many."""
    if not gemini_key:
        return 0
    store = AccountStore(open_database(settings.db_path), settings.cipher())
    try:
        ai = AISettingsStore(store.db, settings.cipher())
        backends = [
            b for m in store.list_members() for b in ai.backends(m.id) if b.kind == "gemini"
        ]
        for backend in backends:
            ai.update_backend(SYSTEM, backend.id, api_key=Secret(gemini_key))
        return len(backends)
    finally:
        store.db.close()


def copied_from(settings: Settings) -> str | None:
    store = AccountStore(open_database(settings.db_path), settings.cipher())
    try:
        row: Any = store.db.one("SELECT value FROM meta WHERE key = ?", (COPY_KEY,))
        return str(row["value"]) if row else None
    finally:
        store.db.close()
