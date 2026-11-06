"""Fresh, fully migrated in-memory databases, fast.

Running every migration costs a few hundred milliseconds, which thousands of tests
can't afford. Each test process migrates one template once and every test gets a
copy of it (SQLite's backup), so tests stay isolated without paying for the
migrations again. Tests of the migrations themselves still build databases by hand.
"""

from __future__ import annotations

from functools import cache

from themi.storage import open_database
from themi.storage.db import Database


@cache
def _template() -> Database:
    return open_database(":memory:")


def migrated_db() -> Database:
    """A new in-memory database at the latest schema, sharing nothing with any other."""
    db = Database(":memory:")
    db.copy_from(_template())
    return db
