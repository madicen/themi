"""A fake OurGroceries list, behind the same small interface the real adapter has.

The real service is reached only through the unofficial library, so this fake
sits at the `GroceryListClient` interface rather than over HTTP. Tests can make
calls fail (`fail("add", times=2)`), act as someone using the app (`put`,
`cross`, `delete`) and look at what the list holds.
"""

from __future__ import annotations

import itertools
from collections import Counter
from datetime import datetime

import pytest

from themi import clock
from themi.connectors.ourgroceries import MirrorError, RemoteItem


class FakeOurGroceries:
    def __init__(self, list_name: str = "Groceries") -> None:
        self.list_name = list_name
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

    async def set_crossed_off(self, item_id: str, crossed_off: bool) -> None:
        self._maybe_fail("cross")
        self.cross(item_id, crossed_off)

    # ----- for tests: what someone does in the app -------------------------------

    def fail(self, op: str, times: int = 1) -> None:
        self._failures[op] += times

    def put(self, value: str, crossed_off: bool = False, at: datetime | None = None) -> str:
        """An item on the list, as if someone added it in the app."""
        item_id = f"og{next(self._ids)}"
        when = (at or clock.now()) if crossed_off else None
        self.list[item_id] = RemoteItem(item_id, value, crossed_off, when)
        return item_id

    def cross(self, item_id: str, crossed_off: bool = True) -> None:
        item = self.list[item_id]
        when = clock.now() if crossed_off else None
        self.list[item_id] = RemoteItem(item.id, item.value, crossed_off, when)

    def delete(self, item_id: str) -> None:
        del self.list[item_id]

    def find(self, value: str) -> str:
        """The id of the item with that name (any case), crossed off or not."""
        (item_id,) = [i.id for i in self.list.values() if i.value.lower() == value.lower()]
        return item_id

    def values(self) -> list[str]:
        return sorted(i.value for i in self.list.values() if not i.crossed_off)


@pytest.fixture
def fake_ourgroceries() -> FakeOurGroceries:
    return FakeOurGroceries()
