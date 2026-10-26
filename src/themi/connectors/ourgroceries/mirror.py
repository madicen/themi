"""Mirror Themi's grocery list into OurGroceries.

Themi's `grocery_list` is the source of truth. Each row starts with
`mirror_state = 'pending'`, and `GroceryMirror.sync()` (the `groceries.mirror`
job) makes OurGroceries match it. Matching is by name, ignoring case, so a crash
between "added" and "recorded" never adds twice.

- needed: added, unless it's there already; if it's there crossed off (bought
  before), it's brought back rather than added a second time;
- bought: crossed off, as the family does when they buy something;
- removed: taken off the list.

A failure is logged and the row retried later, backing off from 1 minute to an
hour. It never blocks the local list: adding, buying and showing items only
touch the database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.connectors.ourgroceries.client import GroceryListClient, MirrorError, RemoteItem
from themi.localtime import to_utc_iso
from themi.storage.db import Database

log = logging.getLogger(__name__)

MAX_BACKOFF = timedelta(hours=1)


def _key(name: str) -> str:
    return " ".join(name.split()).lower()


def backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), MAX_BACKOFF)


class GroceryMirror:
    def __init__(self, db: Database, client: GroceryListClient) -> None:
        self.db = db
        self.client = client

    def due(self) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM grocery_list WHERE mirror_state = 'pending' "
            "AND (mirror_after IS NULL OR mirror_after <= ?) ORDER BY id",
            (to_utc_iso(clock.now()),),
        )

    async def sync(self) -> int:
        """Scheduler job: push pending rows. Returns how many now match."""
        rows = self.due()
        if not rows:
            return 0
        try:
            remote = await self.client.items()
        except MirrorError as exc:
            log.warning("OurGroceries mirror waits: %s", exc)
            for row in rows:
                self._failed(row, str(exc))
            return 0
        on_list: dict[str, RemoteItem] = {}  # not crossed off
        crossed: dict[str, RemoteItem] = {}
        for item in remote:
            (crossed if item.crossed_off else on_list).setdefault(_key(item.value), item)
        done = 0
        for row in rows:
            key = _key(row["name"])
            try:
                if row["status"] == "needed":
                    if key in on_list:
                        pass
                    elif key in crossed:
                        await self.client.set_crossed_off(crossed[key].id, False)
                        on_list[key] = crossed.pop(key)
                    else:
                        await self.client.add(row["name"])
                elif key in on_list:
                    item = on_list.pop(key)
                    if row["status"] == "bought":
                        await self.client.set_crossed_off(item.id, True)
                        crossed[key] = item
                    else:
                        await self.client.remove(item.id)
            except MirrorError as exc:
                log.warning("OurGroceries mirror of %r waits: %s", row["name"], exc)
                self._failed(row, str(exc))
                continue
            self.db.execute(
                "UPDATE grocery_list SET mirror_state = 'done', mirror_error = NULL, "
                "mirror_after = NULL WHERE id = ? AND status = ?",
                (row["id"], row["status"]),  # unless it changed meanwhile
            )
            done += 1
        return done

    def _failed(self, row: dict[str, Any], error: str) -> None:
        attempts = row["mirror_attempts"] + 1
        retry: datetime = clock.now() + backoff(attempts)
        self.db.execute(
            "UPDATE grocery_list SET mirror_attempts = ?, mirror_after = ?, mirror_error = ? "
            "WHERE id = ?",
            (attempts, to_utc_iso(retry), error[:300], row["id"]),
        )
