"""SQLite storage, migrations and secrets at rest."""

from __future__ import annotations

from pathlib import Path

from themi.storage import migrations
from themi.storage.db import Database


def open_database(path: str | Path) -> Database:
    """Open the database and bring its schema up to date."""
    db = Database(path)
    migrations.apply(db)
    return db
