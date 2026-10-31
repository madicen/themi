"""A fake Google Keep, behind the same small interface the real adapter has.

Keep is reached only through the unofficial library, so this fake sits at the
`KeepAccount` interface rather than over HTTP. Each Google address has its own
lists. Tests act as the speaker (`put`), as someone in Keep (`check`, `uncheck`,
`delete`, `edit`), make calls fail (`fail("apply")`) or lose a save
(`drop_next_write`), and look at what each list holds.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass, field

import pytest

from themi.connectors.gkeep import KeepError, KeepItem, KeepLogin
from themi.storage.secrets import Secret

MASTER_TOKEN = "aas_et/fake-master-token"


@dataclass
class FakeItem:
    id: str
    text: str
    checked: bool = False


@dataclass
class FakeKeepUser:
    lists: dict[str, list[FakeItem]] = field(default_factory=dict)


class FakeKeep:
    def __init__(self) -> None:
        self.users: dict[str, FakeKeepUser] = {}
        self.calls: Counter[str] = Counter()
        self.logins: list[KeepLogin] = []
        self._failures: Counter[str] = Counter()
        self._drop_writes = 0
        self._ids = itertools.count(1)

    # ----- the test's controls ----------------------------------------------------------

    def user(self, email: str, *lists: str) -> FakeKeepUser:
        user = self.users.setdefault(email, FakeKeepUser())
        for name in lists or ("Shopping list",):
            user.lists.setdefault(name, [])
        return user

    def put(self, email: str, text: str, list_name: str = "Shopping list") -> str:
        """Someone tells the speaker to add `text`."""
        item = FakeItem(f"item-{next(self._ids)}", text)
        self.user(email, list_name).lists[list_name].append(item)
        return item.id

    def item(self, email: str, item_id: str, list_name: str = "Shopping list") -> FakeItem:
        return next(i for i in self.users[email].lists[list_name] if i.id == item_id)

    def uncheck(self, email: str, item_id: str) -> None:
        self.item(email, item_id).checked = False

    def check(self, email: str, item_id: str) -> None:
        self.item(email, item_id).checked = True

    def delete(self, email: str, item_id: str) -> None:
        items = self.users[email].lists["Shopping list"]
        items.remove(self.item(email, item_id))

    def find(self, email: str, text: str) -> FakeItem:
        return next(i for i in self.users[email].lists["Shopping list"] if i.text == text)

    def drop_next_write(self) -> None:
        """Keep says the next save worked, but loses it (seen with the real Keep)."""
        self._drop_writes += 1

    def edit(self, email: str, item_id: str, text: str) -> None:
        self.item(email, item_id).text = text

    def unchecked_texts(self, email: str, list_name: str = "Shopping list") -> list[str]:
        return [i.text for i in self.users[email].lists[list_name] if not i.checked]

    def checked_texts(self, email: str, list_name: str = "Shopping list") -> list[str]:
        return [i.text for i in self.users[email].lists[list_name] if i.checked]

    def fail(self, op: str, times: int = 1) -> None:
        self._failures[op] += times

    def exchange(self, email: str, oauth_token: Secret, device_id: str) -> Secret:
        if not oauth_token.reveal().startswith("oauth2_4/"):
            raise KeepError("Google didn't give a master token (BadAuthentication)")
        return Secret(MASTER_TOKEN)

    def connect(self, login: KeepLogin) -> FakeKeepAccount:
        self.logins.append(login)
        return FakeKeepAccount(self, login)

    # ----- what the account calls -------------------------------------------------------

    def _maybe_fail(self, op: str) -> None:
        self.calls[op] += 1
        if self._failures[op]:
            self._failures[op] -= 1
            raise KeepError(f"Keep {op} failed (fake)")

    def _list(self, login: KeepLogin, list_name: str) -> list[FakeItem]:
        if login.master_token.reveal() != MASTER_TOKEN:
            raise KeepError("Keep sign-in failed (LoginException)")
        user = self.users.get(login.email, FakeKeepUser())
        for name, items in user.lists.items():
            if name.lower() == list_name.strip().lower():
                return items
        raise KeepError(f"Keep has no list called {list_name!r}")


class FakeKeepAccount:
    def __init__(self, fake: FakeKeep, login: KeepLogin) -> None:
        self.fake = fake
        self.login = login

    async def lists(self) -> list[str]:
        self.fake._maybe_fail("lists")
        return list(self.fake.users.get(self.login.email, FakeKeepUser()).lists)

    async def items(self, list_name: str) -> list[KeepItem]:
        self.fake._maybe_fail("items")
        return [KeepItem(i.id, i.text, i.checked) for i in self.fake._list(self.login, list_name)]

    async def apply(
        self, list_name: str, add: list[str], check: list[str], delete: list[str]
    ) -> list[str]:
        self.fake._maybe_fail("apply")
        items = self.fake._list(self.login, list_name)
        ids = [f"item-{next(self.fake._ids)}" for _ in add]
        if self.fake._drop_writes:
            self.fake._drop_writes -= 1
            return ids
        for item in items:
            if item.id in check:
                item.checked = True
        items[:] = [i for i in items if i.id not in delete]
        items.extend(FakeItem(item_id, text) for item_id, text in zip(ids, add, strict=True))
        return ids


@pytest.fixture
def fake_keep() -> FakeKeep:
    return FakeKeep()
