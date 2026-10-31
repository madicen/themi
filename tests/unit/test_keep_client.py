"""GK1: the real Keep adapter, over a stand-in for the gkeepapi library (no network)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from themi.connectors.gkeep import GKeepAccount, KeepError, KeepLogin, exchange_token
from themi.storage.secrets import Secret

LOGIN = KeepLogin("erin@example.com", Secret("aas_et/master"), "0123456789abcdef")


class Item:
    def __init__(self, item_id: str, text: str, checked: bool = False) -> None:
        self.id, self.text, self.checked, self.deleted = item_id, text, checked, False

    def delete(self) -> None:
        self.deleted = True


class List:
    def __init__(self, title: str, items: list[Item], trashed: bool = False) -> None:
        self.title, self.children, self.trashed, self.archived = title, items, trashed, False

    @property
    def items(self) -> list[Item]:  # as the library's: deleted items aren't there
        return [i for i in self.children if not i.deleted]

    def add(self, text: str, checked: bool = False) -> Item:
        item = Item(f"new-{len(self.children)}", text, checked)
        self.children.append(item)
        return item


class Note:
    title, trashed, archived = "A note", False, False


def library(notes: list[Any], fail_sync: bool = False) -> types.ModuleType:
    module = types.ModuleType("gkeepapi")
    module.node = types.SimpleNamespace(List=List)  # type: ignore[attr-defined]
    calls: list[str] = []

    class Keep:
        def authenticate(self, email: str, token: str, device_id: str | None = None) -> None:
            calls.append(f"authenticate {email} {token} {device_id}")

        def sync(self) -> None:
            calls.append("sync")
            if fail_sync:
                raise RuntimeError("Google changed something")

        def all(self) -> list[Any]:
            return notes

    module.Keep = Keep  # type: ignore[attr-defined]
    module.calls = calls  # type: ignore[attr-defined]
    return module


async def test_reads_the_list_and_changes_it_in_one_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eggs, milk, jam = Item("1", "Eggs"), Item("2", "Milk", checked=True), Item("3", "Jam")
    shopping = List("Shopping list", [eggs, milk, jam])
    old = List("Shopping list", [Item("9", "Old")], trashed=True)
    lib = library([old, Note(), shopping])
    monkeypatch.setitem(sys.modules, "gkeepapi", lib)
    account = GKeepAccount(LOGIN)

    read = await account.items(" shopping LIST")
    assert [(i.id, i.text, i.checked) for i in read] == [
        ("1", "Eggs", False),
        ("2", "Milk", True),
        ("3", "Jam", False),
    ]
    assert await account.lists() == ["Shopping list"]
    syncs = lib.calls.count("sync")  # type: ignore[attr-defined]
    assert await account.apply("Shopping list", ["rice"], ["1"], ["3"]) == ["new-3"]

    assert eggs.checked and jam.deleted
    assert [(i.text, i.checked) for i in shopping.items] == [
        ("Eggs", True),
        ("Milk", True),
        ("rice", False),
    ]
    assert lib.calls.count("sync") == syncs + 2  # type: ignore[attr-defined]  # read, save
    assert lib.calls[0] == "authenticate erin@example.com aas_et/master 0123456789abcdef"  # type: ignore[attr-defined]
    assert lib.calls.count("authenticate erin@example.com aas_et/master 0123456789abcdef") == 1  # type: ignore[attr-defined]


async def test_a_missing_list_or_library_failure_is_a_keep_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "gkeepapi", library([Note()]))
    with pytest.raises(KeepError, match="no list called 'Shopping list'"):
        await GKeepAccount(LOGIN).items("Shopping list")

    lib = library([List("Shopping list", [])], fail_sync=True)
    monkeypatch.setitem(sys.modules, "gkeepapi", lib)
    account = GKeepAccount(LOGIN)
    await account.items("Shopping list")  # signs in; no sync yet
    with pytest.raises(KeepError, match=r"Keep reading the list failed \(RuntimeError\)"):
        await account.items("Shopping list")
    await account.items("Shopping list")  # signs in again
    assert sum(c.startswith("authenticate") for c in lib.calls) == 2  # type: ignore[attr-defined]


async def test_without_the_library_it_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "gkeepapi", None)
    with pytest.raises(KeepError, match=r"pip install 'themi\[keep\]'"):
        await GKeepAccount(LOGIN).items("Shopping list")
    with pytest.raises(KeepError, match=r"pip install 'themi\[keep\]'"):
        exchange_token("erin@example.com", Secret("oauth2_4/x"), "0123456789abcdef")


def test_a_login_never_shows_its_token() -> None:
    assert "aas_et/master" not in repr(LOGIN)
