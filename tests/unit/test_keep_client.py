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
        self.id, self.text, self.checked = item_id, text, checked


class List:
    def __init__(self, title: str, items: list[Item], trashed: bool = False) -> None:
        self.title, self.items, self.trashed, self.archived = title, items, trashed, False

    @property
    def unchecked(self) -> list[Item]:
        return [i for i in self.items if not i.checked]


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


async def test_reads_unchecked_items_and_checks_them_off(monkeypatch: pytest.MonkeyPatch) -> None:
    shopping = List("Shopping list", [Item("1", "Eggs"), Item("2", "Milk", checked=True)])
    old = List("Shopping list", [Item("9", "Old")], trashed=True)
    lib = library([old, Note(), shopping])
    monkeypatch.setitem(sys.modules, "gkeepapi", lib)
    account = GKeepAccount(LOGIN)

    assert [i.text for i in await account.unchecked(" shopping LIST")] == ["Eggs"]
    assert await account.lists() == ["Shopping list"]
    await account.check_off("Shopping list", ["1"])

    assert shopping.items[0].checked
    assert lib.calls[0] == "authenticate erin@example.com aas_et/master 0123456789abcdef"  # type: ignore[attr-defined]
    assert lib.calls.count("authenticate erin@example.com aas_et/master 0123456789abcdef") == 1  # type: ignore[attr-defined]


async def test_a_missing_list_or_library_failure_is_a_keep_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "gkeepapi", library([Note()]))
    with pytest.raises(KeepError, match="no list called 'Shopping list'"):
        await GKeepAccount(LOGIN).unchecked("Shopping list")

    lib = library([List("Shopping list", [])], fail_sync=True)
    monkeypatch.setitem(sys.modules, "gkeepapi", lib)
    account = GKeepAccount(LOGIN)
    await account.unchecked("Shopping list")  # signs in; no sync yet
    with pytest.raises(KeepError, match=r"Keep reading the list failed \(RuntimeError\)"):
        await account.unchecked("Shopping list")
    await account.unchecked("Shopping list")  # signs in again
    assert sum(c.startswith("authenticate") for c in lib.calls) == 2  # type: ignore[attr-defined]


async def test_without_the_library_it_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "gkeepapi", None)
    with pytest.raises(KeepError, match=r"pip install 'themi\[keep\]'"):
        await GKeepAccount(LOGIN).unchecked("Shopping list")
    with pytest.raises(KeepError, match=r"pip install 'themi\[keep\]'"):
        exchange_token("erin@example.com", Secret("oauth2_4/x"), "0123456789abcdef")


def test_a_login_never_shows_its_token() -> None:
    assert "aas_et/master" not in repr(LOGIN)
