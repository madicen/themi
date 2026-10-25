from pathlib import Path

import pytest

from themi.storage import migrations, open_database
from themi.storage.db import Database
from themi.storage.migrations import (
    DatabaseTooNewError,
    Migration,
    MigrationError,
    apply,
    current_version,
    discover,
    split_statements,
)


def write(folder: Path, name: str, sql: str) -> None:
    (folder / name).write_text(sql)


def table_names(db: Database) -> set[str]:
    return {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_discover_orders_by_version(tmp_path: Path) -> None:
    write(tmp_path, "0002_second.sql", "CREATE TABLE b (x);")
    write(tmp_path, "0001_first.sql", "CREATE TABLE a (x);")
    write(tmp_path, "README.md", "not a migration")
    assert [(m.version, m.name) for m in discover(tmp_path)] == [(1, "first"), (2, "second")]


def test_discover_rejects_gaps_and_bad_names(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "")
    write(tmp_path, "0003_third.sql", "")
    with pytest.raises(MigrationError, match="without gaps"):
        discover(tmp_path)
    (tmp_path / "0003_third.sql").unlink()
    write(tmp_path, "2_Bad-Name.sql", "")
    with pytest.raises(MigrationError, match="bad migration filename"):
        discover(tmp_path)


def test_apply_runs_in_order_and_is_idempotent(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE a (x);\nINSERT INTO a VALUES (1);")
    write(tmp_path, "0002_second.sql", "CREATE TABLE b (x REFERENCES a(x));")
    db = Database(":memory:")
    assert apply(db, discover(tmp_path)) == [1, 2]
    assert apply(db, discover(tmp_path)) == []
    assert current_version(db) == 2
    assert {"a", "b", "schema_version"} <= table_names(db)


def test_apply_only_runs_new_migrations(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE a (x);")
    db = Database(":memory:")
    apply(db, discover(tmp_path))
    write(tmp_path, "0002_second.sql", "CREATE TABLE b (x);")
    assert apply(db, discover(tmp_path)) == [2]


def test_failed_migration_rolls_back_entirely(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE a (x);")
    write(tmp_path, "0002_broken.sql", "CREATE TABLE b (x);\nINSERT INTO missing VALUES (1);")
    db = Database(":memory:")
    with pytest.raises(MigrationError, match="0002_broken"):
        apply(db, discover(tmp_path))
    assert current_version(db) == 1
    assert "b" not in table_names(db)


def test_newer_database_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.sql", "CREATE TABLE a (x);")
    db = Database(":memory:")
    apply(db, discover(tmp_path))
    db.execute("INSERT INTO schema_version VALUES (7, 'from_the_future', '2027-01-01')")
    with pytest.raises(DatabaseTooNewError, match="schema version 7"):
        apply(db, discover(tmp_path))


def test_split_statements_keeps_trigger_bodies_whole() -> None:
    script = """
    -- a comment
    CREATE TABLE a (x);
    CREATE TRIGGER t AFTER INSERT ON a BEGIN
        UPDATE a SET x = x + 1;
        DELETE FROM a WHERE x > 10;
    END;
    INSERT INTO a VALUES (1);
    """
    statements = split_statements(script)
    assert len(statements) == 3
    assert statements[1].startswith("CREATE TRIGGER") and statements[1].endswith("END;")


def test_split_statements_rejects_unterminated_statement() -> None:
    with pytest.raises(MigrationError, match="incomplete"):
        split_statements("CREATE TABLE a (x)")


def test_bundled_migrations_apply_cleanly() -> None:
    bundled = discover()
    assert bundled and bundled[0] == Migration(1, "foundation", bundled[0].sql)
    db = open_database(":memory:")
    assert migrations.current_version(db) == bundled[-1].version
    assert {"meta", "app_secrets"} <= table_names(db)
