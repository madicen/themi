"""RC8a: the recipe docs are recipe books, moved from the two fixed tables."""

from __future__ import annotations

from pathlib import Path

from themi import clock
from themi.storage import migrations
from themi.storage.db import Database


def _recipe(db: Database, key: str, source: str, book: str, now: str) -> int:
    db.execute(
        "INSERT INTO recipes (key, source, name, book, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (key, source, key, book, now, now),
    )
    return int(db.scalar("SELECT id FROM recipes WHERE key = ?", (key,)))


def test_the_migration_moves_both_docs_into_recipe_books_and_keeps_cooking_history(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "old.db")
    migrations.apply(db, [m for m in migrations.discover() if m.version < 187])
    now = clock.now().isoformat()
    db.execute(
        "INSERT INTO members (id, name, role, created_at, updated_at) "
        "VALUES (1, 'Michael', 'admin', ?, ?)",
        (now, now),
    )
    db.execute(
        "UPDATE cookbook SET doc_id = 'cook-doc', title = 'Madicen Family Cookbook', "
        "diet = 'vegan', guides_offered = 1, revision = 'r1', problem = NULL"
    )
    db.execute("UPDATE try_doc SET doc_id = 'try-doc', title = 'Recipes to try', revision = 'r9'")
    cooked = _recipe(db, "h.cookie", "doc", "cookbook", now)
    trying = _recipe(db, "try:h.pumpkin", "doc", "to_try", now)
    web = _recipe(db, "web:1", "web", "cookbook", now)
    db.execute(
        "INSERT INTO cooking_sessions (member_id, recipe_id, phase, started_at, last_tap_at) "
        "VALUES (1, ?, 'done', ?, ?), (1, ?, 'done', ?, ?)",
        (cooked, now, now, trying, now, now),
    )

    migrations.apply(db)

    books = db.query("SELECT * FROM recipe_books ORDER BY id")
    assert [(b["id"], b["key"], b["role"], b["doc_id"]) for b in books] == [
        (1, "cookbook", "main", "cook-doc"),
        (2, "to_try", "trying", "try-doc"),
    ]
    main = books[0]
    assert (main["title"], main["diet"], main["guides_offered"], main["revision"]) == (
        "Madicen Family Cookbook", "vegan", 1, "r1",
    )  # fmt: skip
    assert books[1]["revision"] == "r9"
    assert main["sub_recipe_sections"] == '["Ingredients"]'
    assert main["reference_sections"] == '["References"]'
    assert all(b["in_meal_ideas"] and b["found_unasked"] and b["save_button"] for b in books)
    by_id = {r["id"]: r["book_id"] for r in db.query("SELECT id, book_id FROM recipes")}
    assert by_id == {cooked: 1, trying: 2, web: None}  # a web recipe is in no doc yet
    assert db.scalar("SELECT COUNT(*) FROM cooking_sessions") == 2
    gone = db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('cookbook', 'try_doc')"
    )
    assert gone == []
