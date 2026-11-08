"""CR21d: each module drops the old core columns its own first migration copied, right
after copying, so a Themi that jumps several releases at once keeps every value."""

from __future__ import annotations

from pathlib import Path

from themi import clock
from themi.storage import migrations
from themi.storage.db import Database
from themi_cozyla.cozyla_modules import CozylaChoresModule, CozylaTodosModule
from themi_home.chore_chart import ChoreChartModule

TRACKS = {
    "chore_chart": ChoreChartModule.migrations,
    "cozyla_todos": CozylaTodosModule.migrations,
    "cozyla_chores": CozylaChoresModule.migrations,
}
GONE = {
    "tasks": {"on_chart"},
    "lists": {"cozyla_list_id", "wall_name"},
    "list_items": {"cozyla_todo_id", "wall_title", "wall_done"},
    "routine_ticks": {"on_wall_at"},
}


def columns(db: Database, table: str) -> set[str]:
    return {c["name"] for c in db.query(f"PRAGMA table_info({table})")}


def old_database(path: Path) -> Database:
    """A database as it stood before CR20a: something in every column that moved."""
    db = Database(path)
    migrations.apply(db, [m for m in migrations.discover() if m.version < 150])
    now = clock.now().isoformat()
    db.execute(
        "INSERT INTO members (id, name, role, created_at, updated_at) "
        "VALUES (1, 'Erin', 'admin', ?, ?)",
        (now, now),
    )
    db.execute(
        "INSERT INTO tasks (id, title, kind, effort, assign_reason, created_at, on_chart) "
        "VALUES (7, 'Change the sheets', 'physical', 1, '', ?, 1)",
        (now,),
    )
    db.execute(
        "INSERT INTO lists (id, name, created_at, cozyla_list_id, wall_name) "
        "VALUES (3, 'Packing', ?, 'wall-list-1', 'Packing')",
        (now,),
    )
    db.execute(
        "INSERT INTO list_items (id, list_id, name, added_at, cozyla_todo_id, wall_title, "
        "wall_done) VALUES (5, 3, 'Tent', ?, 'todo-9', 'Tent', 0)",
        (now,),
    )
    db.execute(
        "INSERT INTO routines (id, member_id, name, starts, created_at) "
        "VALUES (2, 1, 'Morning', '07:00', ?)",
        (now,),
    )
    db.execute(
        "INSERT INTO routine_items (id, routine_id, title, created_at) "
        "VALUES (4, 2, 'Vitamins', ?)",
        (now,),
    )
    db.execute(
        "INSERT INTO routine_ticks (item_id, day, ticked_at, on_wall_at) "
        "VALUES (4, '2026-10-21', ?, ?)",
        (now, now),
    )
    return db


def test_an_old_database_upgraded_straight_to_the_newest_keeps_every_value(
    tmp_path: Path,
) -> None:
    db = old_database(tmp_path / "old.db")
    migrations.apply(db)  # the core first, as at every start...
    for track, folder in TRACKS.items():  # ...then each loaded module's own
        migrations.apply_track(db, track, folder)  # type: ignore[arg-type]
    for table, gone in GONE.items():
        assert not columns(db, table) & gone, table
    assert db.scalar("SELECT task_id FROM chart_tasks") == 7
    assert [tuple(r.values()) for r in db.query("SELECT * FROM wall_lists")] == [
        (3, "wall-list-1", "Packing")
    ]
    assert [tuple(r.values()) for r in db.query("SELECT * FROM wall_list_items")] == [
        (5, "todo-9", "Tent", 0)
    ]
    assert db.scalar("SELECT item_id FROM wall_seen_ticks WHERE day = '2026-10-21'") == 4
    assert db.scalar("SELECT name FROM list_items WHERE id = 5") == "Tent"  # the item stays


def test_a_module_not_loaded_leaves_its_columns(tmp_path: Path) -> None:
    db = old_database(tmp_path / "old.db")
    migrations.apply(db)
    migrations.apply_track(db, "chore_chart", TRACKS["chore_chart"])  # type: ignore[arg-type]
    assert "on_chart" not in columns(db, "tasks")
    assert GONE["lists"] <= columns(db, "lists")  # no wall here: its columns stay
    assert "on_wall_at" in columns(db, "routine_ticks")
    assert "telegram_user_id" in columns(db, "members")  # UNIQUE: stays, emptied (CR20a2)
