"""Themi's tasks on Google Tasks, kept apart from the inbox (GT1b).

Each person's open one-off tasks go on a list of Themi's own ("Themi") in the
Google account they linked first with Google Tasks allowed: never on My Tasks,
which the inbox empties (GT1a). Themi keeps the Google id of every task it
writes there, so anything else on that list is a new item, handled as the
inbox does.

Each run (with the inbox, every minute):
- done in Google ("Hey Google, mark call the plumber done", or ticked in the
  app): done in Themi;
- done in Themi: done in Google; cancelled, or no longer theirs: removed there;
- a title or due date changed in Themi: changed there. Themi's version wins, so
  edits made in Google aren't brought back. One deleted in Google stays off.

Repeating chores stay off the list, as on the wall's to-do lists. Google keeps
only a task's date, never its time.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from themi.accounts import LinkedAccount, Member
from themi.connectors.gtasks import TasksClient
from themi.core.services import Services
from themi.core.tasks import Task, TaskBoard

log = logging.getLogger(__name__)

LIST_TITLE = "Themi"


def _due(day: date | None) -> str | None:
    return f"{day:%Y-%m-%d}T00:00:00.000Z" if day else None


def on_the_list(task: Task) -> bool:
    return task.status in ("open", "snoozed") and not task.repeats and not task.off_wall


class GoogleTaskList:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.store = services.store
        self.db = services.store.db

    def list_id(self, account: LinkedAccount) -> str | None:
        row = self.db.one(
            "SELECT list_id FROM google_task_lists WHERE account_id = ?", (account.id,)
        )
        return row["list_id"] if row else None

    def known(self, account: LinkedAccount, google_id: str) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM google_task_links WHERE account_id = ? AND google_id = ?",
                (account.id, google_id),
            )
        )

    async def run(self, member: Member, account: LinkedAccount, client: TasksClient) -> None:
        list_id = await self._list(account, client)
        google = {str(t["id"]): t for t in await client.all_tasks(list_id)}
        links = {
            r["task_id"]: r
            for r in self.db.query(
                "SELECT * FROM google_task_links WHERE account_id = ?", (account.id,)
            )
        }
        # Done in Google: done in Themi.
        for task_id, link in links.items():
            remote = google.get(link["google_id"])
            task = self.board.get(task_id)
            if remote and remote.get("status") == "completed" and on_the_list(task):
                await self.board.complete(task.id, member)
        wanted = {t.id: t for t in self.board.open_for(member) if on_the_list(t)}
        for task in wanted.values():
            link = links.get(task.id)
            if link is None:
                google_id = await client.insert_task(list_id, self._body(task))
                self.db.execute(
                    "INSERT INTO google_task_links (task_id, account_id, google_id) "
                    "VALUES (?, ?, ?)",
                    (task.id, account.id, google_id),
                )
                continue
            if link["removed"]:
                continue
            remote = google.get(link["google_id"])
            if remote is None:  # deleted in Google: left off
                self.db.execute(
                    "UPDATE google_task_links SET removed = 1 WHERE task_id = ? AND account_id = ?",
                    (task.id, account.id),
                )
                continue
            changes = self._changes(task, remote)
            if changes:
                await client.patch_task(list_id, link["google_id"], changes)
        for task_id, link in links.items():
            if task_id in wanted:
                continue
            remote = google.get(link["google_id"])
            if remote is not None and not link["removed"]:
                if self.board.get(task_id).status == "done":
                    if remote.get("status") != "completed":
                        await client.patch_task(list_id, link["google_id"], {"status": "completed"})
                else:  # cancelled, or someone else's now
                    await client.delete_task(list_id, link["google_id"])
            self.db.execute(
                "DELETE FROM google_task_links WHERE task_id = ? AND account_id = ?",
                (task_id, account.id),
            )

    async def _list(self, account: LinkedAccount, client: TasksClient) -> str:
        """The account's "Themi" list: found by name, or made."""
        known = self.list_id(account)
        if known is not None:
            return known
        found = next((x for x in await client.lists() if x.get("title") == LIST_TITLE), None)
        list_id = str(found["id"]) if found else await client.create_list(LIST_TITLE)
        self.db.execute(
            "INSERT OR REPLACE INTO google_task_lists (account_id, list_id) VALUES (?, ?)",
            (account.id, list_id),
        )
        return list_id

    @staticmethod
    def _body(task: Task) -> dict[str, Any]:
        body: dict[str, Any] = {"title": task.title}
        if task.due_on:
            body["due"] = _due(task.due_on)
        return body

    @staticmethod
    def _changes(task: Task, remote: dict[str, Any]) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        if remote.get("title") != task.title:
            changes["title"] = task.title
        if str(remote.get("due") or "")[:10] != (task.due_on.isoformat() if task.due_on else ""):
            changes["due"] = _due(task.due_on)
        if remote.get("status") == "completed":  # reopened in Themi
            changes["status"] = "needsAction"
        return changes
