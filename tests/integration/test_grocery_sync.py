"""G1: OurGroceries syncs both ways. What the family does in the app reaches Themi's list,
crossed-off history comes in as done, and Themi's own changes still go out and win."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fixtures.family import SeededFamily
from tests.integration.test_grocery_mirror import finish, put
from themi import clock
from themi.connectors.ourgroceries import GroceryMirror
from themi.localtime import to_utc_iso


@pytest.fixture
def mirror(
    family: SeededFamily, fake_ourgroceries: FakeOurGroceries, frozen_clock: datetime
) -> GroceryMirror:
    return GroceryMirror(family.db, fake_ourgroceries)


def rows(family: SeededFamily, name: str) -> list[dict[str, Any]]:
    return family.db.query("SELECT * FROM grocery_list WHERE name = ? ORDER BY id", (name,))


def needed(family: SeededFamily) -> list[str]:
    return [
        r["name"]
        for r in family.db.query(
            "SELECT name FROM grocery_list WHERE status = 'needed' ORDER BY name"
        )
    ]


def pushes(fake: FakeOurGroceries) -> int:
    return fake.calls["add"] + fake.calls["cross"] + fake.calls["remove"]


async def test_the_first_sync_brings_in_the_list_with_crossed_off_items_as_done(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    a_week_ago = clock.now() - timedelta(days=7)
    fake_ourgroceries.put("Milk")
    fake_ourgroceries.put("Bananas", crossed_off=True, at=a_week_ago)
    fake_ourgroceries.put("White miso")
    put(family, "white miso")  # already Themi's, and the mirror added it before
    family.db.execute("UPDATE grocery_list SET mirror_state = 'done'")

    await mirror.sync()
    assert needed(family) == ["milk", "white miso"]  # nothing crossed off looks new
    (bananas,) = rows(family, "bananas")
    assert bananas["status"] == "bought" and bananas["done_at"] == to_utc_iso(a_week_ago)
    assert bananas["source"] == "ourgroceries" and bananas["mirror_state"] == "done"
    (milk,) = rows(family, "milk")
    assert milk["source"] == "ourgroceries" and milk["added_by"] is None
    assert milk["remote_id"] == fake_ourgroceries.find("Milk")
    (miso,) = rows(family, "white miso")
    assert miso["source"] == "themi" and miso["remote_id"] == fake_ourgroceries.find("White miso")
    assert pushes(fake_ourgroceries) == 0  # nothing echoed back

    await mirror.sync()
    assert family.db.scalar("SELECT COUNT(*) FROM grocery_list") == 3  # no doubles


async def test_adding_crossing_off_and_deleting_in_the_app_reach_themi(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    milk, rice = fake_ourgroceries.put("Milk"), fake_ourgroceries.put("rice")
    await mirror.sync()

    fake_ourgroceries.put("Cumin")
    fake_ourgroceries.cross(milk)  # bought it
    fake_ourgroceries.delete(rice)  # changed their mind
    clock.advance(timedelta(minutes=1))
    await mirror.sync()

    assert needed(family) == ["cumin"]
    (milk_row,) = rows(family, "milk")
    assert milk_row["status"] == "bought" and milk_row["done_at"] == to_utc_iso(clock.now())
    assert rows(family, "rice")[0]["status"] == "removed"
    assert all(r["mirror_state"] == "done" for r in family.db.query("SELECT * FROM grocery_list"))
    assert pushes(fake_ourgroceries) == 0


async def test_uncrossing_in_the_app_means_needed_again(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    eggs = fake_ourgroceries.put("Eggs", crossed_off=True)
    await mirror.sync()
    fake_ourgroceries.cross(eggs, False)
    await mirror.sync()
    assert needed(family) == ["eggs"]
    assert [r["status"] for r in rows(family, "eggs")] == ["bought", "needed"]  # history kept
    assert rows(family, "eggs")[1]["remote_id"] == eggs
    assert pushes(fake_ourgroceries) == 0


async def test_crossing_off_in_the_app_can_mark_it_bought_elsewhere_too(
    family: SeededFamily, fake_ourgroceries: FakeOurGroceries, frozen_clock: datetime
) -> None:
    """The app wires this to the pantry, as the website's "Got it" does."""
    bought: list[str] = []

    def mark(name: str) -> None:
        bought.append(name)
        family.db.execute(
            "UPDATE grocery_list SET status = 'bought', mirror_state = 'pending' "
            "WHERE name = ? AND status = 'needed'",
            (name,),
        )

    mirror = GroceryMirror(family.db, fake_ourgroceries, bought=mark)
    milk = fake_ourgroceries.put("Milk")
    await mirror.sync()
    fake_ourgroceries.cross(milk)
    await mirror.sync()
    assert bought == ["milk"]
    assert rows(family, "milk")[0]["mirror_state"] == "done"  # already crossed: nothing to send
    assert pushes(fake_ourgroceries) == 0


async def test_themis_changes_still_go_out(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    fake_ourgroceries.put("Milk")
    await mirror.sync()
    finish(family, rows(family, "milk")[0]["id"], "bought")
    put(family, "eggs")
    await mirror.sync()
    assert fake_ourgroceries.values() == ["eggs"]
    assert fake_ourgroceries.list[fake_ourgroceries.find("Milk")].crossed_off
    await mirror.sync()  # the next read learns the new item's id
    assert rows(family, "eggs")[0]["remote_id"] == fake_ourgroceries.find("eggs")
    assert needed(family) == ["eggs"]


async def test_when_both_sides_changed_an_item_themis_change_wins(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    milk = fake_ourgroceries.put("Milk")
    bread = fake_ourgroceries.put("Bread", crossed_off=True)
    await mirror.sync()

    finish(family, rows(family, "milk")[0]["id"], "removed")  # Themi: not needed
    fake_ourgroceries.cross(milk)  # the app: bought
    put(family, "bread")  # Themi: needed again
    fake_ourgroceries.delete(bread)  # the app: deleted
    await mirror.sync()

    assert rows(family, "milk")[0]["status"] == "removed"  # not bought: Themi's change wins
    assert fake_ourgroceries.list[milk].crossed_off  # off the list either way; left as it is
    assert needed(family) == ["bread"]
    assert fake_ourgroceries.values() == ["bread"]  # added back, once


async def test_an_outage_changes_nothing_and_the_next_sync_catches_up(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    milk = fake_ourgroceries.put("Milk")
    await mirror.sync()
    fake_ourgroceries.cross(milk)
    fake_ourgroceries.put("Cumin")
    fake_ourgroceries.fail("items")
    await mirror.sync()
    assert needed(family) == ["milk"]

    await mirror.sync()  # backing off: not asked again yet
    assert fake_ourgroceries.calls["items"] == 2
    clock.advance(timedelta(minutes=1))
    await mirror.sync()
    assert needed(family) == ["cumin"]
    assert rows(family, "milk")[0]["status"] == "bought"


async def test_a_different_list_starts_over_instead_of_deleting_everything(
    family: SeededFamily, frozen_clock: datetime
) -> None:
    groceries = FakeOurGroceries("Groceries")
    groceries.put("Milk")
    await GroceryMirror(family.db, groceries).sync()

    costco = FakeOurGroceries("Costco")
    costco.put("Paper towels")
    await GroceryMirror(family.db, costco).sync()
    assert needed(family) == ["milk", "paper towels"]
    assert costco.values() == ["Paper towels", "milk"]  # Themi's, so it goes onto the new list
    assert groceries.values() == ["Milk"]  # the old list is left alone


async def test_names_themi_cant_store_are_skipped(
    family: SeededFamily, mirror: GroceryMirror, fake_ourgroceries: FakeOurGroceries
) -> None:
    fake_ourgroceries.put("🍌🍌")
    fake_ourgroceries.put("Bananas")
    await mirror.sync()
    assert needed(family) == ["bananas"]
