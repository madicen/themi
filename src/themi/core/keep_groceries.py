"""Groceries said to Google Home, taken from Google Keep (GK1).

"Hey Google, add tomatoes to my shopping list" lands in the speaker's person's Keep. Each
sync (the `groceries.keep` job, every 2 minutes) reads each linked person's watched list:

- an unchecked item Themi hasn't taken goes on the grocery list as theirs, like an item
  added in the OurGroceries app (G1), then is checked off in Keep;
- one taken but not checked off yet (the check-off failed) is only checked off;
- one Themi checked off that someone unchecked since is new again.

Keep failing is logged and retried with a backoff per person; it never blocks the list.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.connectors.gkeep import KeepAccount, KeepError, KeepFactory, KeepLogin
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


class KeepGroceries:
    def __init__(
        self, db: Database, links: KeepLinks, groceries: GroceryList, connect: KeepFactory
    ) -> None:
        self.db = db
        self.links = links
        self.groceries = groceries
        self.connect = connect
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
        """Scheduler job: returns how many items went on the grocery list."""
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
        items = await account.unchecked(link.list_name)
        taken = {
            r["item_id"]: (r["status"], r["text"])
            for r in self.db.query(
                "SELECT item_id, status, text FROM keep_items WHERE member_id = ?", (member.id,)
            )
        }
        now = to_utc_iso(clock.now())
        added, to_check = 0, []
        for item in items:
            status, text = taken.get(item.id, (None, None))
            if status == "skipped" and text == item.text:  # edited since: tried again
                continue
            if status != "added":  # new, or unchecked again since Themi checked it off
                try:
                    name = item_name(item.text)
                except InvalidValue:
                    log.info("Keep item %r has no name Themi can keep; left", item.text[:60])
                    self._remember(member, item.id, item.text, "skipped", now)
                    continue
                added += len(self.groceries.add([name], by=member))
                self._remember(member, item.id, item.text, "added", now)
            to_check.append(item.id)
        if to_check:
            try:
                await account.check_off(link.list_name, to_check)
            except KeepError as exc:  # they're on the list; only the check-off waits
                self._failed(member, exc)
                return added
            self.db.executemany(
                "UPDATE keep_items SET status = 'checked' WHERE member_id = ? AND item_id = ?",
                [(member.id, item_id) for item_id in to_check],
            )
        self._failures.pop(member.id, None)
        self._wait_until.pop(member.id, None)
        return added

    def _remember(self, member: Member, item_id: str, text: str, status: str, now: str) -> None:
        self.db.execute(
            "INSERT INTO keep_items (member_id, item_id, text, status, seen_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(member_id, item_id) DO UPDATE SET "
            "text = excluded.text, status = excluded.status, seen_at = excluded.seen_at",
            (member.id, item_id, text, status, now),
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
    waiting = await account.unchecked(list_name)
    links.link(member, login, list_name)
    say(
        f"Linked {member.name}'s Google Keep ({email}). Themi checks {list_name!r} every 2 "
        f"minutes; {len(waiting)} item{'' if len(waiting) == 1 else 's'} there now will go on "
        "the grocery list and be checked off in Keep."
    )
