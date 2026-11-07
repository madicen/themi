"""CR6: migration tracks: the core's, and one per module that has tables."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.modules import bare_services
from tests.fixtures.family import SeededFamily
from themi.backup.snapshots import inspect
from themi.modules import Module, ModuleContext
from themi.storage import migrations, open_database
from themi.storage.db import Database
from themi.storage.migrations import (
    DatabaseTooNewError,
    MigrationError,
    apply,
    apply_track,
    current_version,
    discover,
)


def write(folder: Path, name: str, sql: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(sql)
    return folder


def tables(db: Database) -> set[str]:
    return {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}


def before_cr6(path: Path) -> Database:
    """A database as Themi left it before CR6: no track column."""
    db = Database(path)
    db.execute(
        "CREATE TABLE schema_version ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    for m in discover():
        for statement in migrations.split_statements(m.sql):
            db.execute(statement)
        db.execute("INSERT INTO schema_version VALUES (?, ?, ?)", (m.version, m.name, "2026-11-01"))
    return db


def test_a_database_from_before_cr6_upgrades_with_nothing_else_changed(tmp_path: Path) -> None:
    db = before_cr6(tmp_path / "old.db")
    before = tables(db)
    rows = db.query("SELECT version, name, applied_at FROM schema_version ORDER BY version")
    assert apply(db) == []  # nothing new to run
    assert tables(db) == before
    after = db.query("SELECT track, version, name, applied_at FROM schema_version ORDER BY version")
    assert [r["track"] for r in after] == ["core"] * len(rows)
    assert [(r["version"], r["name"], r["applied_at"]) for r in after] == [
        (r["version"], r["name"], r["applied_at"]) for r in rows
    ]
    assert current_version(db) == migrations.latest_version()


def test_a_fresh_database(tmp_path: Path) -> None:
    db = open_database(tmp_path / "new.db")
    assert current_version(db) == migrations.latest_version()
    columns = [r["name"] for r in db.query("PRAGMA table_info(schema_version)")]
    assert columns == ["track", "version", "name", "applied_at"]


def test_a_module_track_is_its_own(tmp_path: Path) -> None:
    db = open_database(tmp_path / "t.db")
    folder = write(tmp_path / "work", "0001_projects.sql", "CREATE TABLE work_projects (x);")
    assert apply_track(db, "work", folder) == [1]
    assert current_version(db, "work") == 1
    assert current_version(db) == migrations.latest_version()  # the core's is untouched
    write(folder, "0002_more.sql", "ALTER TABLE work_projects ADD COLUMN y;")
    assert apply_track(db, "work", folder) == [2]  # resumed
    assert apply_track(db, "work", folder) == []


def test_two_modules_can_both_start_at_0001(tmp_path: Path) -> None:
    db = open_database(tmp_path / "t.db")
    a = write(tmp_path / "a", "0001_first.sql", "CREATE TABLE a_things (x);")
    b = write(tmp_path / "b", "0001_first.sql", "CREATE TABLE b_things (x);")
    assert apply_track(db, "a", a) == [1] and apply_track(db, "b", b) == [1]
    assert {"a_things", "b_things"} <= tables(db)


def test_a_track_from_newer_code_is_refused(tmp_path: Path) -> None:
    db = open_database(tmp_path / "t.db")
    folder = write(tmp_path / "work", "0001_projects.sql", "CREATE TABLE work_projects (x);")
    db.execute(
        "INSERT INTO schema_version (track, version, name, applied_at) "
        "VALUES ('work', 5, 'future', 'x')"
    )
    with pytest.raises(DatabaseTooNewError, match="work's schema version 5"):
        apply_track(db, "work", folder)


def test_a_module_cannot_use_the_core_track(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="core's track"):
        apply_track(open_database(tmp_path / "t.db"), "core", tmp_path)


def test_a_failing_module_migration_names_its_track(tmp_path: Path) -> None:
    db = open_database(tmp_path / "t.db")
    folder = write(tmp_path / "work", "0001_broken.sql", "CREATE TABLE (;")
    with pytest.raises(MigrationError, match="work migration 0001_broken failed"):
        apply_track(db, "work", folder)


def make_module(name: str, folder: Path | None, seen: list[set[str]]) -> Module:
    class M(Module):
        def install(self, ctx: ModuleContext) -> None:
            seen.append(tables(ctx.services.store.db))

    M.name = name
    M.migrations = folder
    return M()


def test_the_loader_applies_a_track_before_its_module_installs(
    family: SeededFamily, tmp_path: Path
) -> None:
    folder = write(tmp_path / "work", "0001_projects.sql", "CREATE TABLE work_projects (x);")
    seen: list[set[str]] = []
    ModuleContext(bare_services(family.store)).load(make_module("work", folder, seen))
    assert "work_projects" in seen[0]
    assert current_version(family.db, "work") == 1


def test_a_module_turned_off_keeps_its_tables_and_on_again_carries_on(
    family: SeededFamily, tmp_path: Path
) -> None:
    folder = write(tmp_path / "work", "0001_projects.sql", "CREATE TABLE work_projects (x);")
    seen: list[set[str]] = []
    ModuleContext(bare_services(family.store)).load(make_module("work", folder, seen))
    family.db.execute("INSERT INTO work_projects VALUES (1)")
    ModuleContext(bare_services(family.store)).load(make_module("other", None, seen))  # off
    assert family.db.scalar("SELECT COUNT(*) FROM work_projects") == 1
    write(folder, "0002_more.sql", "ALTER TABLE work_projects ADD COLUMN y;")
    ModuleContext(bare_services(family.store)).load(make_module("work", folder, seen))
    assert current_version(family.db, "work") == 2
    assert family.db.scalar("SELECT COUNT(*) FROM work_projects") == 1


def test_a_snapshot_reports_the_core_schema_before_and_after_cr6(tmp_path: Path) -> None:
    old = before_cr6(tmp_path / "old.db")
    old.close()
    assert inspect(tmp_path / "old.db")[0] == migrations.latest_version()
    new = open_database(tmp_path / "new.db")
    folder = write(tmp_path / "work", "0001_projects.sql", "CREATE TABLE work_projects (x);")
    for n in range(2, 300):  # a module track far past the core's number
        write(folder, f"{n:04d}_step.sql", "SELECT 1;")
    apply_track(new, "work", folder)
    new.close()
    assert inspect(tmp_path / "new.db")[0] == migrations.latest_version()
