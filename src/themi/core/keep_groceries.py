"""The grocery list in Google Keep, both ways (GK1, GK2).

"Hey Google, add tomatoes to my shopping list" lands in the speaker's person's Keep, so each
linked person's watched Keep list shows Themi's grocery list. Each sync (the
`groceries.keep` job, every 2 minutes) first brings in what changed in Keep, like the
OurGroceries mirror (G1):

- an unchecked item Themi doesn't know (the speaker, or someone typing): needed, as theirs,
  and it stays as that item; one already on the list is a duplicate, deleted from Keep;
- checked off: bought; deleted: removed; a checked-off one unchecked: needed again.

Then Themi's list goes out: needed with no item in Keep, added; bought, checked off;
removed, deleted.

Themi wins: a Keep change counts only while Themi hasn't changed that item since. Keep can
drop a write, so Themi's writes stay unconfirmed until a read shows them; an unconfirmed one
that isn't there is made again, never read as someone's change.

Keep failing is logged and retried with a backoff per person; it never blocks the list.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.connectors.gkeep import KeepAccount, KeepError, KeepFactory, KeepItem, KeepLogin
from themi.connectors.ourgroceries.mirror import backoff
from themi.core.groceries import GroceryList, item_name
from themi.localtime import to_utc_iso
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

DEFAULT_LIST = "Shopping list"


@dataclass(frozen=True)
class KeepLink:
    member_id: int
    login: KeepLogin
    list_name: str


def new_device_id() -> str:
    """The Android-style id a master token is made for, and used with after."""
    return secrets.token_hex(8)


class KeepLinks:
    """Who has linked Keep: their master token (encrypted) and the list to watch."""

    def __init__(self, db: Database, cipher: Cipher) -> None:
        self.db = db
        self.cipher = cipher

    def link(self, member: Member, login: KeepLogin, list_name: str) -> None:
        self.db.execute(
            "INSERT INTO keep_accounts "
            "(member_id, email, master_token, device_id, list_name, linked_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(member_id) DO UPDATE SET "
            "email = excluded.email, master_token = excluded.master_token, "
            "device_id = excluded.device_id, list_name = excluded.list_name, "
            "linked_at = excluded.linked_at",
            (
                member.id,
                login.email,
                self.cipher.encrypt(login.master_token),
                login.device_id,
                list_name,
                to_utc_iso(clock.now()),
            ),
        )
        self.db.execute("DELETE FROM keep_items WHERE member_id = ?", (member.id,))

    def unlink(self, member: Member) -> bool:
        self.db.execute("DELETE FROM keep_items WHERE member_id = ?", (member.id,))
        return self.db.update("DELETE FROM keep_accounts WHERE member_id = ?", (member.id,)) > 0

    def all(self) -> list[KeepLink]:
        return [
            KeepLink(
                r["member_id"],
                KeepLogin(r["email"], self.cipher.decrypt(r["master_token"]), r["device_id"]),
                r["list_name"],
            )
            for r in self.db.query("SELECT * FROM keep_accounts ORDER BY member_id")
        ]


@dataclass
class _Changes:
    """What one sync sends to a person's Keep."""

    add: list[tuple[int, str]]  # (grocery_list id, text)
    check: list[str]
    delete: list[str]


class KeepGroceries:
    def __init__(
        self,
        db: Database,
        links: KeepLinks,
        groceries: GroceryList,
        connect: KeepFactory,
        bought: Callable[[str], object] | None = None,
    ) -> None:
        self.db = db
        self.links = links
        self.groceries = groceries
        self.connect = connect
        # Checked off in Keep: as the OurGroceries mirror's, the pantry has it again.
        self.bought = bought
        self._accounts: dict[int, tuple[KeepLogin, KeepAccount]] = {}
        self._failures: dict[int, int] = {}
        self._wait_until: dict[int, datetime] = {}

    def _account(self, link: KeepLink) -> KeepAccount:
        known = self._accounts.get(link.member_id)
        if known is None or known[0] != link.login:  # linked again: sign in afresh
            known = (link.login, self.connect(link.login))
            self._accounts[link.member_id] = known
        return known[1]

    async def sync(self) -> int:
        """Scheduler job: returns how many items Keep put on the grocery list."""
        added = 0
        for link in self.links.all():
            wait = self._wait_until.get(link.member_id)
            if wait is not None and clock.now() < wait:
                continue
            member = self.groceries.services.store.get_member(link.member_id)
            try:
                added += await self._sync_one(member, link)
            except KeepError as exc:
                self._failed(member, exc)
        return added

    def _failed(self, member: Member, exc: KeepError) -> None:
        failures = self._failures.get(member.id, 0) + 1
        self._failures[member.id] = failures
        self._wait_until[member.id] = clock.now() + backoff(failures)
        log.warning("Keep for %s waits: %s", member.name, exc)

    async def _sync_one(self, member: Member, link: KeepLink) -> int:
        account = self._account(link)
        items = await account.items(link.list_name)
        changes = _Changes([], [], [])
        added = self._pull(member, items, changes)
        self._push(member, changes)
        if changes.add or changes.check or changes.delete:
            try:
                ids = await account.apply(
                    link.list_name, [t for _, t in changes.add], changes.check, changes.delete
                )
            except KeepError as exc:  # Keep's changes are in; Themi's go next time
                self._failed(member, exc)
                return added
            self._wrote(member, changes, ids)
        self._failures.pop(member.id, None)
        self._wait_until.pop(member.id, None)
        return added

    # ----- what changed in Keep ---------------------------------------------------------

    def _pull(self, member: Member, items: list[KeepItem], changes: _Changes) -> int:
        rows = {
            r["item_id"]: r
            for r in self.db.query("SELECT * FROM keep_items WHERE member_id = ?", (member.id,))
        }
        added = 0
        for item in items:
            row = rows.pop(item.id, None)
            if row is None or (row["status"] == "skipped" and row["text"] != item.text):
                if not item.checked:  # checked ones Themi never knew are history
                    added += self._new(member, item, changes)
            elif row["status"] == "shown":
                self._shown(member, item, row)
            elif row["status"] == "done" and not item.checked:
                if row["confirmed"]:  # someone unchecked it: needed again
                    added += self._new(member, item, changes)
                else:  # Themi's check-off didn't stick: again
                    changes.check.append(item.id)
            elif row["status"] == "done":
                self._confirm(member, item.id)
        for row in rows.values():  # not in Keep any more
            needed = self._needed_row(row["grocery_id"])
            if row["status"] == "shown" and row["confirmed"] and needed:
                self.groceries.finish(needed["name"], "removed")  # deleted in Keep
            self._forget(member, row["item_id"])  # an unconfirmed add is made again below
        return added

    def _new(self, member: Member, item: KeepItem, changes: _Changes) -> int:
        """An unchecked item Themi doesn't know: needed, unless it's a duplicate."""
        try:
            name = item_name(item.text)
        except InvalidValue:
            log.info("Keep item %r has no name Themi can keep; left", item.text[:60])
            self._remember(member, item, None, "skipped", confirmed=True)
            return 0
        needed = self._needed_by_name(name)
        if needed is not None and self._shows(member, needed["id"]):
            changes.delete.append(item.id)  # already there: one copy is enough
            self._forget(member, item.id)
            return 0
        added = len(self.groceries.add([name], by=member))
        needed = self._needed_by_name(name)
        assert needed is not None  # just added, or already needed
        self._remember(member, item, needed["id"], "shown", confirmed=True)
        return added

    def _shown(self, member: Member, item: KeepItem, row: dict[str, Any]) -> None:
        needed = self._needed_row(row["grocery_id"])
        if item.checked and needed is not None:  # Themi still needs it: bought in Keep
            self.groceries.finish(needed["name"], "bought")
            if self.bought is not None:
                self.bought(needed["name"])
            self._remember(member, item, row["grocery_id"], "done", confirmed=True)
        elif item.checked:  # Themi was done with it too
            self._remember(member, item, row["grocery_id"], "done", confirmed=True)
        else:
            self._confirm(member, item.id)

    # ----- Themi's list, out to Keep ----------------------------------------------------

    def _push(self, member: Member, changes: _Changes) -> None:
        shown = {
            r["grocery_id"]: r
            for r in self.db.query(
                "SELECT * FROM keep_items WHERE member_id = ? AND status = 'shown'", (member.id,)
            )
        }
        needed = self.db.query(
            "SELECT id, name FROM grocery_list WHERE status = 'needed' ORDER BY id"
        )
        for row in needed:
            if shown.pop(row["id"], None) is None:
                changes.add.append((row["id"], row["name"]))
        for grocery_id, row in shown.items():  # Themi's done with these (Themi wins)
            if row["item_id"] in changes.delete:
                continue
            status = self.db.one("SELECT status FROM grocery_list WHERE id = ?", (grocery_id,))
            if status is not None and status["status"] == "bought":
                changes.check.append(row["item_id"])
            else:
                changes.delete.append(row["item_id"])

    def _wrote(self, member: Member, changes: _Changes, ids: list[str]) -> None:
        now = to_utc_iso(clock.now())
        for (grocery_id, text), item_id in zip(changes.add, ids, strict=True):
            self._remember(member, KeepItem(item_id, text), grocery_id, "shown", now=now)
        for item_id in changes.check:
            self.db.execute(
                "UPDATE keep_items SET status = 'done', confirmed = 0 "
                "WHERE member_id = ? AND item_id = ?",
                (member.id, item_id),
            )
        for item_id in changes.delete:
            self._forget(member, item_id)

    # ----- bookkeeping ------------------------------------------------------------------

    def _needed_row(self, grocery_id: int | None) -> dict[str, Any] | None:
        if grocery_id is None:
            return None
        return self.db.one(
            "SELECT id, name FROM grocery_list WHERE id = ? AND status = 'needed'", (grocery_id,)
        )

    def _needed_by_name(self, name: str) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT id, name FROM grocery_list WHERE name = ? AND status = 'needed' "
            "ORDER BY id LIMIT 1",
            (name,),
        )

    def _shows(self, member: Member, grocery_id: int) -> bool:
        return bool(
            self.db.one(
                "SELECT 1 FROM keep_items WHERE member_id = ? AND grocery_id = ? "
                "AND status = 'shown'",
                (member.id, grocery_id),
            )
        )

    def _remember(
        self,
        member: Member,
        item: KeepItem,
        grocery_id: int | None,
        status: str,
        *,
        confirmed: bool = False,
        now: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO keep_items "
            "(member_id, item_id, text, grocery_id, status, confirmed, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(member_id, item_id) DO UPDATE SET "
            "text = excluded.text, grocery_id = excluded.grocery_id, status = excluded.status, "
            "confirmed = excluded.confirmed, seen_at = excluded.seen_at",
            (
                member.id,
                item.id,
                item.text,
                grocery_id,
                status,
                int(confirmed),
                now or to_utc_iso(clock.now()),
            ),
        )

    def _confirm(self, member: Member, item_id: str) -> None:
        self.db.execute(
            "UPDATE keep_items SET confirmed = 1 WHERE member_id = ? AND item_id = ?",
            (member.id, item_id),
        )

    def _forget(self, member: Member, item_id: str) -> None:
        self.db.execute(
            "DELETE FROM keep_items WHERE member_id = ? AND item_id = ?", (member.id, item_id)
        )


SETUP_STEPS = """To link {name}'s Google Keep:
1. In a private browser window, open https://accounts.google.com/EmbeddedSetup and sign in
   as the Google account the speaker adds {name}'s shopping list to. Agree if it asks.
   (The page may spin at the end; that's fine.)
2. Open the developer tools (F12), then Application (Chrome) or Storage (Firefox),
   Cookies, https://accounts.google.com, and copy the value of `oauth_token`
   (it starts with oauth2_4/). It works once, for a few minutes.
Themi turns it into a master token, kept encrypted. Removing "Android device" sign-ins on
the account's security page, or `themi keep unlink {name}`, ends it."""


async def run_keep_link(
    links: KeepLinks,
    member: Member,
    list_name: str,
    ask: Callable[[str], str],
    ask_secret: Callable[[str], str],
    exchange: Callable[[str, Secret, str], Secret],
    connect: KeepFactory,
    say: Callable[[str], object],
) -> None:
    """`themi keep link`: get a master token, check it reads the list, and keep it."""
    say(SETUP_STEPS.format(name=member.name))
    email = ask("Google address").strip()
    cookie = ask_secret("oauth_token cookie (not shown)").strip()
    if not email or not cookie:
        raise KeepError("both the address and the cookie are needed; nothing was saved")
    device_id = new_device_id()
    login = KeepLogin(email, exchange(email, Secret(cookie), device_id), device_id)
    account = connect(login)
    lists = await account.lists()
    if list_name.strip().lower() not in {t.strip().lower() for t in lists}:
        found = ", ".join(repr(t) for t in lists) or "none"
        raise KeepError(
            f"{email}'s Keep has no list called {list_name!r} (lists: {found}). "
            "Nothing was saved; --list picks another."
        )
    waiting = [i for i in await account.items(list_name) if not i.checked]
    links.link(member, login, list_name)
    say(
        f"Linked {member.name}'s Google Keep ({email}). Every 2 minutes, {list_name!r} and the "
        f"grocery list are kept in step; the {len(waiting)} unchecked "
        f"item{'' if len(waiting) == 1 else 's'} there now will join the grocery list."
    )
