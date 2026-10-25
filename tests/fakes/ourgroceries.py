"""A fake OurGroceries list, behind the same small interface the real adapter has.

The real service is reached only through the unofficial library, so this fake
sits at the `GroceryListClient` interface rather than over HTTP. Tests can make
calls fail (`fail("add", times=2)`) and look at what the list holds.
"""

from __future__ import annotations

import itertools
from collections import Counter

import pytest

from themi.connectors.ourgroceries import MirrorError, RemoteItem


class FakeOurGroceries:
    def __init__(self) -> None:
        self.list: dict[str, RemoteItem] = {}
        self.calls: Counter[str] = Counter()
        self._failures: Counter[str] = Counter()
        self._ids = itertools.count(1)

    # ----- the interface -------------------------------------------------------

    def _maybe_fail(self, op: str) -> None:
        self.calls[op] += 1
        if self._failures[op]:
            self._failures[op] -= 1
            raise MirrorError(f"OurGroceries {op} failed (fake)")

    async def items(self) -> list[RemoteItem]:
        self._maybe_fail("items")
        return list(self.list.values())

    async def add(self, value: str) -> None:
        self._maybe_fail("add")
        self.put(value)

    async def remove(self, item_id: str) -> None:
        self._maybe_fail("remove")
        self.list.pop(item_id, None)

    # ----- for tests ------------------------------------------------------------

    def fail(self, op: str, times: int = 1) -> None:
        self._failures[op] += times

    def put(self, value: str, crossed_off: bool = False) -> str:
        """An item on the list, as if someone added it in the app."""
        item_id = f"og{next(self._ids)}"
        self.list[item_id] = RemoteItem(item_id, value, crossed_off)
        return item_id

    def values(self) -> list[str]:
        return sorted(i.value for i in self.list.values() if not i.crossed_off)


@pytest.fixture
def fake_ourgroceries() -> FakeOurGroceries:
    return FakeOurGroceries()
