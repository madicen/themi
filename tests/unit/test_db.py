import threading

import pytest

from themi.storage.db import Database


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    return database


def test_execute_returns_row_id_and_query_returns_dicts(db: Database) -> None:
    first = db.execute("INSERT INTO items (name) VALUES (?)", ("soap",))
    second = db.execute("INSERT INTO items (name) VALUES (:name)", {"name": "oil"})
    assert (first, second) == (1, 2)
    assert db.query("SELECT name FROM items ORDER BY id") == [{"name": "soap"}, {"name": "oil"}]
    assert db.one("SELECT name FROM items WHERE id = 2") == {"name": "oil"}
    assert db.one("SELECT name FROM items WHERE id = 99") is None
    assert db.scalar("SELECT COUNT(*) FROM items") == 2


def test_transaction_commits(db: Database) -> None:
    with db.transaction():
        db.execute("INSERT INTO items (name) VALUES ('a')")
        db.execute("INSERT INTO items (name) VALUES ('b')")
    assert db.scalar("SELECT COUNT(*) FROM items") == 2
    assert not db.in_transaction


def test_transaction_rolls_back_on_exception(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction():
        db.execute("INSERT INTO items (name) VALUES ('a')")
        raise RuntimeError("boom")
    assert db.scalar("SELECT COUNT(*) FROM items") == 0
    assert not db.in_transaction


def test_nested_transaction_rolls_back_only_inner_block(db: Database) -> None:
    with db.transaction():
        db.execute("INSERT INTO items (name) VALUES ('outer')")
        with pytest.raises(ValueError), db.transaction():
            db.execute("INSERT INTO items (name) VALUES ('inner')")
            raise ValueError
        db.execute("INSERT INTO items (name) VALUES ('after')")
    assert [r["name"] for r in db.query("SELECT name FROM items ORDER BY id")] == [
        "outer",
        "after",
    ]


def test_outer_failure_discards_committed_savepoints(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction():
        with db.transaction():
            db.execute("INSERT INTO items (name) VALUES ('inner')")
        raise RuntimeError
    assert db.scalar("SELECT COUNT(*) FROM items") == 0


def test_transactions_from_threads_do_not_interleave(db: Database) -> None:
    db.execute("CREATE TABLE counter (n INTEGER NOT NULL)")
    db.execute("INSERT INTO counter VALUES (0)")

    def bump() -> None:
        for _ in range(50):
            with db.transaction():
                n = db.scalar("SELECT n FROM counter")
                db.execute("UPDATE counter SET n = ?", (n + 1,))

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert db.scalar("SELECT n FROM counter") == 200


def test_foreign_keys_are_enforced(db: Database) -> None:
    db.execute("CREATE TABLE notes (item_id INTEGER NOT NULL REFERENCES items(id))")
    with pytest.raises(Exception, match="FOREIGN KEY"):
        db.execute("INSERT INTO notes VALUES (42)")
