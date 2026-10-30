"""Google Tasks as an inbox (GT1a).

"Hey Google, add a task..." on the family's speakers puts it in that person's
Google Tasks. The family uses their default list ("My Tasks") as a queue for
Themi. Each minute (the `google_tasks.inbox` job), for every linked account
allowed to use Google Tasks whose person is on Telegram:

- each open item not seen before goes to the agent as that person's message
  ('Erin asked their Google speaker to add "milk" to Google Tasks'), and the
  reply reaches them
  in Telegram, as for anything they send; what it leads to (a grocery item, a
  task, a calendar event) goes through the trust tiers as usual;
- once it's handled, the item is deleted from Google Tasks. Emptying the queue
  needs no yes (decided 2026-10-30); a failed delete is retried, without
  handling the item again;
- if no AI backend answers, the item stays and waits an hour before it's
  tried again, so a busy model doesn't answer "busy" every minute.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import LinkedAccount, Member
from themi.connectors.google import TASKS_SCOPE, GoogleAccounts, TokenRevoked
from themi.connectors.google.oauth import OAuthError
from themi.connectors.gtasks import DEFAULT_LIST, TasksClient, TasksError
from themi.core.services import Services
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.agent import Agent

log = logging.getLogger(__name__)

KIND = "google_task"  # how the item shows in the message log
RETRY_AFTER = timedelta(hours=1)
MAX_TITLE = 300
MAX_NOTES = 500


def as_message(member: Member, task: dict[str, Any]) -> str:
    """The item in words, as if they'd sent it. It's their own words, said to their speaker."""
    title = " ".join(str(task.get("title") or "").split())[:MAX_TITLE]
    notes = " ".join(str(task.get("notes") or "").split())[:MAX_NOTES]
    # "asked ... to add": the person's own request, as the trust tiers read one (an item they
    # asked for by name goes on a list without a card).
    said = f'{member.name} asked their Google speaker to add "{title}" to Google Tasks'
    if due := str(task.get("due") or ""):
        said += f", due {date.fromisoformat(due[:10]):%A %-d %B}"  # Google keeps only the date
    if notes:
        said += f', with the note "{notes}"'
    return said + ". Take it as something they asked for."


class GoogleTasksInbox:
    def __init__(self, services: Services, google: GoogleAccounts, base_url: str) -> None:
        self.services = services
        self.google = google
        self.base_url = base_url
        self.store = services.store
        self.db = services.store.db
        self.agent: Agent | None = None  # set once the agent exists

    def install(self, agent: Agent) -> None:
        self.agent = agent
        self.services.google_tasks = self

    def client(self, account_id: int) -> TasksClient:
        return TasksClient(
            self.base_url,
            lambda: self.google.access_token(account_id),
            lambda: self.google.forget_access_token(account_id),
        )

    async def run(self) -> int:
        """Scheduler job: handle new items in each inbox. Returns how many were handled."""
        handled = 0
        for member in self.store.list_members():
            if member.telegram_user_id is None:
                continue
            for account in self.store.linked_accounts(member.id):
                if account.enabled and account.allows(TASKS_SCOPE):
                    handled += await self._empty(member, account)
        return handled

    async def _empty(self, member: Member, account: LinkedAccount) -> int:
        client = self.client(account.id)
        try:
            await self._delete_handled(client, account)
            items = await client.open_tasks(DEFAULT_LIST)
        except (TasksError, TokenRevoked, OAuthError) as exc:
            log.warning("Google Tasks for account %s waits: %s", account.id, exc)
            return 0
        handled = 0
        now = clock.now()
        for task in items:
            task_id = str(task["id"])
            row = self.db.one(
                "SELECT * FROM google_task_inbox WHERE account_id = ? AND task_id = ?",
                (account.id, task_id),
            )
            if row is not None and (
                row["status"] != "waiting" or row["retry_after"] > to_utc_iso(now)
            ):
                continue
            if not str(task.get("title") or "").strip():
                continue  # an empty item says nothing; it's left for them
            assert self.agent is not None
            text = as_message(member, task)
            if not await self.agent.take_in(member, text, KIND):
                self._note(account, task_id, text, "waiting", now + RETRY_AFTER)
                return handled  # the model isn't answering: the rest wait too
            self._note(account, task_id, text, "handled", None)
            handled += 1
            try:
                await client.delete_task(DEFAULT_LIST, task_id)
            except (TasksError, TokenRevoked, OAuthError) as exc:
                log.warning("Couldn't remove a handled Google Task yet: %s", exc)
                continue
            self._removed(account, task_id)
        return handled

    async def _delete_handled(self, client: TasksClient, account: LinkedAccount) -> None:
        """Items handled earlier whose delete didn't go through."""
        for row in self.db.query(
            "SELECT task_id FROM google_task_inbox WHERE account_id = ? AND status = 'handled'",
            (account.id,),
        ):
            await client.delete_task(DEFAULT_LIST, row["task_id"])
            self._removed(account, row["task_id"])

    def _note(
        self, account: LinkedAccount, task_id: str, text: str, status: str, retry: Any
    ) -> None:
        self.db.execute(
            "INSERT INTO google_task_inbox (account_id, task_id, text, status, retry_after, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, task_id) DO UPDATE "
            "SET status = excluded.status, retry_after = excluded.retry_after",
            (
                account.id,
                task_id,
                text,
                status,
                to_utc_iso(retry) if retry else None,
                to_utc_iso(clock.now()),
            ),
        )

    def _removed(self, account: LinkedAccount, task_id: str) -> None:
        self.db.execute(
            "UPDATE google_task_inbox SET status = 'removed' WHERE account_id = ? AND task_id = ?",
            (account.id, task_id),
        )
