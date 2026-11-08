"""Numbered SQL migrations, applied on startup.

Files live in `src/themi/storage/schema/` as `NNNN_short_name.sql`. Each
runs in its own transaction and is recorded in `schema_version`. A database
written by newer code (a version we don't know) is refused rather than
risking a downgrade.

CR6: migrations come in tracks. The core's are track "core" (the 144 files above, frozen
as the baseline: new feature tables don't go there). A module with tables has its own
track, named after it and numbered from 0001, applied after the core's in load order. A
module turned off keeps its tables; turned on again, its track carries on.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from themi import clock
from themi.storage.db import Database

FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(Exception):
    pass


class DatabaseTooNewError(MigrationError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def _default_dir() -> Traversable:
    return resources.files("themi.storage") / "schema"


def discover(directory: Path | Traversable | None = None) -> list[Migration]:
    folder = directory if directory is not None else _default_dir()
    found: list[Migration] = []
    for entry in folder.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        match = FILENAME.match(entry.name)
        if not match:
            raise MigrationError(f"bad migration filename: {entry.name}")
        found.append(Migration(int(match[1]), match[2], entry.read_text()))
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"migration versions must run 1..N without gaps: {versions}")
    return found


def split_statements(script: str) -> list[str]:
    """Split a script into complete statements (trigger bodies stay whole)."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip() and not all(
        part.strip().startswith("--") or not part.strip() for part in buffer.splitlines()
    ):
        raise MigrationError(f"incomplete statement at end of script: {buffer.strip()[:80]}")
    return statements


CORE = "core"

VERSION_TABLE = (
    "CREATE TABLE {name} (track TEXT NOT NULL DEFAULT 'core', version INTEGER NOT NULL, "
    "name TEXT NOT NULL, applied_at TEXT NOT NULL, PRIMARY KEY (track, version))"
)


def _ensure_version_table(db: Database) -> None:
    """The version table, with its `track` column (CR6). A database from before CR6 has
    the table without it: its rows are all the core's, so they move over as track core."""
    columns = [r["name"] for r in db.query("PRAGMA table_info(schema_version)")]
    if not columns:
        db.execute(VERSION_TABLE.format(name="schema_version"))
    elif "track" not in columns:
        with db.transaction():
            db.execute(VERSION_TABLE.format(name="schema_version_tracks"))
            db.execute(
                "INSERT INTO schema_version_tracks (track, version, name, applied_at) "
                "SELECT 'core', version, name, applied_at FROM schema_version"
            )
            db.execute("DROP TABLE schema_version")
            db.execute("ALTER TABLE schema_version_tracks RENAME TO schema_version")


def current_version(db: Database, track: str = CORE) -> int:
    _ensure_version_table(db)
    return db.scalar(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version WHERE track = ?", (track,)
    )


def latest_version() -> int:
    """The newest schema this Themi knows."""
    migrations = discover()
    return migrations[-1].version if migrations else 0


def apply(db: Database, migrations: list[Migration] | None = None, track: str = CORE) -> list[int]:
    """Apply a track's pending migrations in order. Returns the versions applied."""
    migrations = discover() if migrations is None else migrations
    latest_known = migrations[-1].version if migrations else 0
    current = current_version(db, track)
    if current > latest_known:
        what = "schema version" if track == CORE else f"{track}'s schema version"
        raise DatabaseTooNewError(
            f"database is at {what} {current}, but this Themi only knows up to "
            f"{latest_known}; upgrade Themi before using this database"
        )
    applied = []
    for migration in migrations:
        if migration.version <= current:
            continue
        try:
            with db.transaction():
                for statement in split_statements(migration.sql):
                    db.execute(statement)
                db.execute(
                    "INSERT INTO schema_version (track, version, name, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (track, migration.version, migration.name, clock.now().isoformat()),
                )
        except sqlite3.Error as exc:
            where = "" if track == CORE else f"{track} "
            raise MigrationError(
                f"{where}migration {migration.version:04d}_{migration.name} failed: {exc}"
            ) from exc
        applied.append(migration.version)
    return applied


def module_folder(migrations: str | Path) -> Path | Traversable:
    """A module's migrations: a package of SQL files ("themi_work.schema"), or a folder."""
    return migrations if isinstance(migrations, Path) else resources.files(migrations)


def apply_track(db: Database, track: str, migrations: str | Path) -> list[int]:
    """CR6: a module's own track, after the core's."""
    if track == CORE:
        raise MigrationError("a module can't use the core's track")
    return apply(db, discover(module_folder(migrations)), track)
