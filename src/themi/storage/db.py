"""Thread-safe SQLite access.

The Telegram poller, scheduler and website share one connection, so every
call takes the same re-entrant lock. A `transaction()` holds the lock for its
whole body; nested transactions become savepoints.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

Params = Sequence[Any] | dict[str, Any]


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        in_memory = self.path == ":memory:"
        if not in_memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: autocommit unless we open a transaction ourselves.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0
        with self._lock:
            if not in_memory:
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")

    def execute(self, sql: str, params: Params = ()) -> int:
        """Run one write statement; returns the last inserted row id (0 if none)."""
        with self._lock:
            return self._conn.execute(sql, params).lastrowid or 0

    def executemany(self, sql: str, rows: Sequence[Params]) -> int:
        """Run a statement for each row; returns the number of rows changed."""
        with self._lock:
            return self._conn.executemany(sql, rows).rowcount

    def query(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: Params = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def scalar(self, sql: str, params: Params = ()) -> Any:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return row[0] if row is not None else None

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """All-or-nothing block. Other threads wait until it finishes."""
        with self._lock:
            if self._depth == 0:
                self._conn.execute("BEGIN IMMEDIATE")
                begin, commit, rollback = None, "COMMIT", "ROLLBACK"
            else:
                name = f"sp_{self._depth}"
                begin, commit, rollback = (
                    f"SAVEPOINT {name}",
                    f"RELEASE {name}",
                    f"ROLLBACK TO {name}; RELEASE {name}",
                )
            if begin:
                self._conn.execute(begin)
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                for statement in rollback.split("; "):
                    self._conn.execute(statement)
                raise
            else:
                self._depth -= 1
                self._conn.execute(commit)

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
