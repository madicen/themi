"""Sync Themi's grocery list with OurGroceries, both ways (G1).

Each sync (the `groceries.mirror` job, every minute) reads the configured list
and compares it with what it saw last time (`ourgroceries_seen`), so it can
tell what the family did in the app since:

- added, or un-crossed: needed on Themi's list, marked as from OurGroceries;
- crossed off: bought (the family crosses things off when they buy them);
- deleted: removed.

Then Themi's own changes go out, as before. Each changed row starts with
`mirror_state = 'pending'`, and the sync makes OurGroceries match it:

- needed: added, unless it's there already; if it's there crossed off (bought
  before), it's brought back rather than added a second time;
- bought: crossed off;
- removed: taken off the list.

A row that's still pending wins over a change in the app: Themi's is the newer.
The first sync of a list brings it in whole: items not crossed off as needed,
crossed-off ones as bought when they were crossed off, so they never look new.

Matching is by the OurGroceries item id once known, else by name, so a crash
between "added" and "recorded" never adds twice. A failure is logged and
retried later, backing off from 1 minute to an hour. It never blocks the local
list: adding, buying and showing items only touch the database.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import InvalidValue
from themi.connectors.ourgroceries.client import GroceryListClient, MirrorError, RemoteItem
from themi.core.groceries import item_name
from themi.localtime import to_utc_iso
from themi.storage.db import Database

log = logging.getLogger(__name__)

MAX_BACKOFF = timedelta(hours=1)


def _key(name: str) -> str:
    try:
        return item_name(name)
    except InvalidValue:
        return " ".join(name.split()).lower()


def _name(item: RemoteItem) -> str | None:
    """How Themi stores the item's name, or None if it can't (all emoji, say)."""
    try:
        return item_name(item.value)
    except InvalidValue:
        log.info("OurGroceries item %r has no name Themi can keep; skipped", item.value[:60])
        return None


def backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), MAX_BACKOFF)


class GroceryMirror:
    def __init__(
        self,
        db: Database,
        client: GroceryListClient,
        bought: Callable[[str], object] | None = None,
    ) -> None:
        self.db = db
        self.client = client
        # Crossing off in the app: by default the row is just marked bought. The app passes
        # the pantry's, so the item goes back to plenty, as with the website's "Got it".
        self.bought = bought
        self._read_failures = 0
        self._read_after: datetime | None = None

    def due(self) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM grocery_list WHERE mirror_state = 'pending' "
            "AND (mirror_after IS NULL OR mirror_after <= ?) ORDER BY id",
            (to_utc_iso(clock.now()),),
        )

    async def sync(self) -> int:
        """Scheduler job: bring in the app's changes, then send Themi's. Returns how many of
        Themi's changes now match."""
        if self._read_after is not None and clock.now() < self._read_after:
            return 0
        try:
            remote = await self.client.items()
        except MirrorError as exc:
            log.warning("OurGroceries sync waits: %s", exc)
            self._read_failures += 1
            self._read_after = clock.now() + backoff(self._read_failures)
            for row in self.due():
                self._failed(row, str(exc))
            return 0
        self._read_failures, self._read_after = 0, None
        seen = self._seen()
        if seen is None:
            self._import(remote)
        else:
            self._pull(remote, seen)
        current = {item.id: item for item in remote}
        done = await self._push(current)
        self._remember(current.values())
        return done

    # ----- what the app changed --------------------------------------------------------

    def _seen(self) -> dict[str, RemoteItem] | None:
        list_name = self.client.list_name
        if not self.db.one("SELECT 1 FROM ourgroceries_sync WHERE list_name = ?", (list_name,)):
            return None
        return {
            r["remote_id"]: RemoteItem(r["remote_id"], r["value"], bool(r["crossed_off"]))
            for r in self.db.query(
                "SELECT * FROM ourgroceries_seen WHERE list_name = ?", (list_name,)
            )
        }

    def _remember(self, items: Iterable[RemoteItem]) -> None:
        list_name = self.client.list_name
        self.db.execute("DELETE FROM ourgroceries_seen WHERE list_name = ?", (list_name,))
        for item in items:
            self.db.execute(
                "INSERT INTO ourgroceries_seen (list_name, remote_id, value, crossed_off) "
                "VALUES (?, ?, ?, ?)",
                (list_name, item.id, item.value, int(item.crossed_off)),
            )
        self.db.execute(
            "INSERT INTO ourgroceries_sync (list_name, synced_at) VALUES (?, ?) "
            "ON CONFLICT(list_name) DO UPDATE SET synced_at = excluded.synced_at",
            (list_name, to_utc_iso(clock.now())),
        )

    def _import(self, remote: list[RemoteItem]) -> None:
        """The first sync of this list: bring it in whole."""
        list_name = self.client.list_name
        # Another list's snapshot would make a later switch back look like a pile of deletes.
        self.db.execute("DELETE FROM ourgroceries_seen WHERE list_name != ?", (list_name,))
        self.db.execute("DELETE FROM ourgroceries_sync WHERE list_name != ?", (list_name,))
        self.db.execute("UPDATE grocery_list SET remote_id = NULL WHERE status = 'needed'")
        handled: set[str] = set()
        for item in sorted(remote, key=lambda i: i.crossed_off):  # the active copy first
            name = _name(item)
            if name is None or name in handled:
                continue
            handled.add(name)
            row = self._needed(item, name)
            if item.crossed_off:
                if row is None and not self._known(item):
                    when = item.crossed_at or clock.now()
                    self._insert(name, item, "bought", when)
                # Needed in Themi but crossed off there: Themi's wins, so it's un-crossed below.
            elif row is not None:
                self._attach(row, item)
            else:
                self._insert(name, item, "needed", clock.now())
        # Themi's needed items that aren't on this list go onto it.
        self.db.execute(
            "UPDATE grocery_list SET mirror_state = 'pending', mirror_attempts = 0, "
            "mirror_after = NULL WHERE status = 'needed' AND remote_id IS NULL "
            "AND mirror_state = 'done'"
        )

    def _pull(self, remote: list[RemoteItem], seen: dict[str, RemoteItem]) -> None:
        pending = {
            r["name"]
            for r in self.db.query("SELECT name FROM grocery_list WHERE mirror_state = 'pending'")
        }  # Themi changed these since: its change wins
        current = {item.id: item for item in remote}
        for item in remote:
            name = _name(item)
            if name is None or name in pending:
                continue
            before = seen.get(item.id)
            row = self._needed(item, name)
            if not item.crossed_off:
                if row is not None:
                    self._attach(row, item)  # also learns the id of an item Themi added
                elif before is None or before.crossed_off:
                    self._insert(name, item, "needed", clock.now())  # added or un-crossed
            elif row is not None and before is not None and not before.crossed_off:
                self._bought(row)  # crossed off since the last sync
        for gone in seen.values():
            if gone.id in current or gone.crossed_off or _key(gone.value) in pending:
                continue
            self.db.execute(
                "UPDATE grocery_list SET status = 'removed', done_at = ? "
                "WHERE remote_id = ? AND status = 'needed' AND mirror_state = 'done'",
                (to_utc_iso(clock.now()), gone.id),
            )

    def _needed(self, item: RemoteItem, name: str) -> dict[str, Any] | None:
        """Themi's needed row for this item: by its id, else by name if it has none yet."""
        return self.db.one(
            "SELECT * FROM grocery_list WHERE status = 'needed' "
            "AND (remote_id = ? OR (remote_id IS NULL AND name = ?)) "
            "ORDER BY remote_id IS NULL, id DESC LIMIT 1",
            (item.id, name),
        )

    def _known(self, item: RemoteItem) -> bool:
        return bool(self.db.one("SELECT 1 FROM grocery_list WHERE remote_id = ?", (item.id,)))

    def _attach(self, row: dict[str, Any], item: RemoteItem) -> None:
        if row["remote_id"] is None:
            self.db.execute(
                "UPDATE grocery_list SET remote_id = ? WHERE id = ?", (item.id, row["id"])
            )

    def _insert(self, name: str, item: RemoteItem, status: str, when: datetime) -> None:
        pantry = self.db.one("SELECT id FROM pantry_items WHERE name = ?", (name,))
        stamp = to_utc_iso(when)
        self.db.execute(
            "INSERT INTO grocery_list (name, status, pantry_item_id, added_at, done_at, "
            "mirror_state, remote_id, source) VALUES (?, ?, ?, ?, ?, 'done', ?, 'ourgroceries')",
            (
                name,
                status,
                pantry["id"] if pantry else None,
                stamp,
                stamp if status != "needed" else None,
                item.id,
            ),
        )

    def _bought(self, row: dict[str, Any]) -> None:
        if self.bought is not None:
            self.bought(row["name"])
            return
        self.db.execute(
            "UPDATE grocery_list SET status = 'bought', done_at = ? "
            "WHERE id = ? AND status = 'needed'",
            (to_utc_iso(clock.now()), row["id"]),
        )

    # ----- what Themi changed ----------------------------------------------------------

    async def _push(self, current: dict[str, RemoteItem]) -> int:
        """Send pending rows; `current` is kept up to date with what was changed."""
        rows = self.due()
        if not rows:
            return 0
        on_list: dict[str, RemoteItem] = {}  # not crossed off
        crossed: dict[str, RemoteItem] = {}
        for item in current.values():
            (crossed if item.crossed_off else on_list).setdefault(_key(item.value), item)
        done = 0
        for row in rows:
            key = _key(row["name"])
            item = current.get(row["remote_id"] or "") or on_list.get(key) or crossed.get(key)
            try:
                if row["status"] == "needed":
                    if item is None:
                        await self.client.add(row["name"])  # its id is learnt next sync
                    elif item.crossed_off:
                        await self.client.set_crossed_off(item.id, False)
                        item = current[item.id] = replace(item, crossed_off=False)
                        crossed.pop(key, None)
                        on_list[key] = item
                elif item is not None and not item.crossed_off:
                    on_list.pop(key, None)
                    if row["status"] == "bought":
                        await self.client.set_crossed_off(item.id, True)
                        crossed[key] = current[item.id] = replace(item, crossed_off=True)
                    else:
                        await self.client.remove(item.id)
                        del current[item.id]
            except MirrorError as exc:
                log.warning("OurGroceries sync of %r waits: %s", row["name"], exc)
                self._failed(row, str(exc))
                continue
            remote_id = item.id if row["status"] == "needed" and item is not None else None
            self.db.execute(
                "UPDATE grocery_list SET mirror_state = 'done', mirror_error = NULL, "
                "mirror_after = NULL, remote_id = COALESCE(?, remote_id) "
                "WHERE id = ? AND status = ?",
                (remote_id, row["id"], row["status"]),  # unless it changed meanwhile
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
