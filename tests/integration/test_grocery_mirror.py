"""The OurGroceries mirror: Themi's list is the truth, and failures only delay the copy."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.connectors.ourgroceries import (
    GroceryMirror,
    MirrorError,
    OurGroceriesClient,
    OurGroceriesConfig,
)
from themi.localtime import to_utc_iso
from themi.storage.secrets import Secret


def put(family: SeededFamily, name: str, status: str = "needed") -> int:
    return family.db.execute(
        "INSERT INTO grocery_list (name, status, added_at) VALUES (?, ?, ?)",
        (name, status, to_utc_iso(clock.now())),
    )


def finish(family: SeededFamily, row_id: int, status: str = "bought") -> None:
    family.db.execute(
        "UPDATE grocery_list SET status = ?, mirror_state = 'pending', mirror_attempts = 0, "
        "mirror_after = NULL WHERE id = ?",
        (status, row_id),
    )


def row(family: SeededFamily, row_id: int) -> dict[str, Any]:
    found = family.db.one("SELECT * FROM grocery_list WHERE id = ?", (row_id,))
    assert found is not None
    return found


@pytest.fixture
def mirror(
    family: SeededFamily, fake_ourgroceries: FakeOurGroceries, frozen_clock: datetime
) -> GroceryMirror:
    return GroceryMirror(family.db, fake_ourgroceries)


async def test_needed_items_are_added_once(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    fake_ourgroceries.put("Eggs")  # already there, added in the app
    put(family, "eggs")
    put(family, "olive oil")
    assert await mirror.sync() == 2
    assert fake_ourgroceries.values() == ["Eggs", "olive oil"]
    assert fake_ourgroceries.calls["add"] == 1
    assert await mirror.sync() == 0  # nothing pending: OurGroceries isn't even asked
    assert fake_ourgroceries.calls["items"] == 1


async def test_bought_items_are_crossed_off_and_removed_ones_deleted(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    """The family crosses things off when they buy them, so bought means crossed off."""
    eggs, rice = put(family, "eggs"), put(family, "rice")
    await mirror.sync()
    finish(family, eggs, "bought")
    finish(family, rice, "removed")
    assert await mirror.sync() == 2
    assert fake_ourgroceries.values() == []  # nothing left to buy
    assert [(i.value, i.crossed_off) for i in fake_ourgroceries.list.values()] == [
        ("eggs", True)  # still there, done
    ]


async def test_a_needed_item_crossed_off_in_the_app_is_uncrossed_not_doubled(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    """Most of the family's items are crossed off (bought before). Needing one again
    brings it back, rather than leaving it hidden or adding a second copy."""
    fake_ourgroceries.put("Olive oil", crossed_off=True)
    put(family, "olive oil")
    assert await mirror.sync() == 1
    assert [(i.value, i.crossed_off) for i in fake_ourgroceries.list.values()] == [
        ("Olive oil", False)
    ]
    assert fake_ourgroceries.calls["add"] == 0


async def test_failures_back_off_and_retry(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    eggs = put(family, "eggs")
    fake_ourgroceries.fail("items")
    assert await mirror.sync() == 0
    failed = row(family, eggs)
    assert failed["mirror_state"] == "pending" and failed["mirror_attempts"] == 1
    assert "failed (fake)" in failed["mirror_error"]
    assert failed["status"] == "needed"  # the local list is untouched

    assert await mirror.sync() == 0  # still backing off
    assert fake_ourgroceries.calls["items"] == 1
    clock.advance(timedelta(minutes=1))
    fake_ourgroceries.fail("add", times=1)
    assert await mirror.sync() == 0
    assert row(family, eggs)["mirror_attempts"] == 2
    clock.advance(timedelta(minutes=1))
    assert await mirror.sync() == 0  # the second delay is two minutes
    clock.advance(timedelta(minutes=1))
    assert await mirror.sync() == 1
    done = row(family, eggs)
    assert done["mirror_state"] == "done" and done["mirror_error"] is None
    assert fake_ourgroceries.values() == ["eggs"]


async def test_one_failing_item_doesnt_hold_up_the_rest(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    eggs, rice = put(family, "eggs"), put(family, "rice")
    fake_ourgroceries.fail("add", times=1)
    assert await mirror.sync() == 1
    assert row(family, eggs)["mirror_state"] == "pending"
    assert row(family, rice)["mirror_state"] == "done"
    assert fake_ourgroceries.values() == ["rice"]


async def test_a_change_during_the_sync_stays_pending(
    family: SeededFamily, fake_ourgroceries: FakeOurGroceries
) -> None:
    eggs = put(family, "eggs")

    class Racing(FakeOurGroceries):
        async def add(self, value: str) -> None:
            await super().add(value)
            finish(family, eggs)  # bought while the add was in flight

    racing = Racing()
    await GroceryMirror(family.db, racing).sync()
    assert row(family, eggs)["mirror_state"] == "pending"
    await GroceryMirror(family.db, racing).sync()
    assert racing.values() == []


# ----- the real adapter, over a stand-in for the library ----------------------------


class StandInLibrary:
    """Answers like the `ourgroceries` library does."""

    def __init__(self, fail_on: str = "") -> None:
        self.fail_on = fail_on
        self.added: list[tuple[str, str, bool]] = []
        self.removed: list[tuple[str, str]] = []
        self.toggled: list[tuple[str, str, bool]] = []
        self.logins = 0

    async def login(self) -> None:
        self.logins += 1

    async def get_my_lists(self) -> dict[str, Any]:
        return {
            "shoppingLists": [{"id": "L1", "name": "Costco"}, {"id": "L2", "name": "Groceries"}]
        }

    async def get_list_items(self, list_id: str) -> dict[str, Any]:
        if self.fail_on == "items":
            raise OSError("connection reset")
        # As the real library returns them: its own crossedOff is always False; the real
        # sign of a crossed-off item is a crossedOffAt timestamp (milliseconds).
        return {
            "list": {
                "id": list_id,
                "items": [
                    {"id": "i1", "value": "eggs", "crossedOff": False},
                    {
                        "id": "i2",
                        "value": "rice",
                        "crossedOff": False,
                        "crossedOffAt": 1761400000000,
                    },
                ],
            }
        }

    async def toggle_item_crossed_off(
        self, list_id: str, item_id: str, cross_off: bool = False
    ) -> dict:
        self.toggled.append((list_id, item_id, cross_off))
        return {}

    async def add_item_to_list(self, list_id: str, value: str, auto_category: bool = False) -> dict:
        self.added.append((list_id, value, auto_category))
        return {}

    async def remove_item_from_list(self, list_id: str, item_id: str) -> dict:
        self.removed.append((list_id, item_id))
        return {}


def real_client(library: StandInLibrary, list_name: str = "groceries") -> OurGroceriesClient:
    client = OurGroceriesClient(OurGroceriesConfig("us@x.example", Secret("pw"), list_name))
    client._api = library
    return client


async def test_the_adapter_finds_the_list_by_name_and_maps_items() -> None:
    library = StandInLibrary()
    client = real_client(library)
    eggs, rice = await client.items()
    assert (eggs.id, eggs.value, eggs.crossed_off) == ("i1", "eggs", False)
    assert (rice.id, rice.value, rice.crossed_off) == ("i2", "rice", True)  # crossedOffAt
    await client.add("olive oil")
    await client.remove("i1")
    await client.set_crossed_off("i2", False)
    await client.set_crossed_off("i1", True)
    assert library.added == [("L2", "olive oil", True)]
    assert library.removed == [("L2", "i1")]
    assert library.toggled == [("L2", "i2", False), ("L2", "i1", True)]
    assert library.logins == 1


async def test_the_adapter_turns_problems_into_mirror_errors() -> None:
    with pytest.raises(MirrorError, match="no list called 'Pantry'"):
        await real_client(StandInLibrary(), "Pantry").items()
    library = StandInLibrary(fail_on="items")
    client = real_client(library)
    with pytest.raises(MirrorError, match="reading the list failed"):
        await client.items()
    library.fail_on = ""
    assert len(await client.items()) == 2
    assert library.logins == 2  # signed in again after the failure


async def test_without_the_library_the_mirror_just_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "ourgroceries", None)  # as if it weren't installed
    client = OurGroceriesClient(OurGroceriesConfig("us@x.example", Secret("pw"), "Groceries"))
    with pytest.raises(MirrorError, match="isn't installed"):
        await client.items()
