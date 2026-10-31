"""GK1, GK2: each linked person's Google Keep list shows the grocery list, both ways. What the
speaker adds there joins it; Themi wins when both sides changed. Linked from the command
line (`themi keep link`)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fakes.keep import MASTER_TOKEN, FakeKeep
from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts import Member
from themi.connectors.gkeep import KeepError, KeepLogin
from themi.core.groceries import GroceryList
from themi.core.keep_groceries import KeepLinks, run_keep_link
from themi.storage.secrets import Secret

ERIN = "erin@example.com"
HIM = "him@example.com"


def links(scenario: Scenario) -> KeepLinks:
    return KeepLinks(scenario.app.db, scenario.family.store.cipher)


def link(scenario: Scenario, fake: FakeKeep, member: Member, email: str) -> None:
    fake.user(email)
    login = KeepLogin(email, Secret(MASTER_TOKEN), "0123456789abcdef")
    links(scenario).link(member, login, "Shopping list")


def groceries(scenario: Scenario) -> GroceryList:
    assert scenario.app.services.groceries is not None
    return scenario.app.services.groceries


async def sync(scenario: Scenario) -> object:
    return await scenario.run_periodic("groceries.keep")


def needed(scenario: Scenario) -> dict[str, int | None]:
    return {i.name: i.added_by for i in groceries(scenario).needed()}


def status(scenario: Scenario, name: str) -> str:
    row = scenario.app.db.one(
        "SELECT status FROM grocery_list WHERE name = ? ORDER BY id DESC LIMIT 1", (name,)
    )
    assert row is not None
    return str(row["status"])


# ----- from Keep ----------------------------------------------------------------------------


async def test_an_item_said_to_the_speaker_joins_the_list_and_stays_in_keep(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    erin = scenario.family.erin
    link(scenario, fake_keep, erin, ERIN)
    fake_keep.put(ERIN, "14oz can of tomatoes")

    assert await sync(scenario) == 1
    assert needed(scenario) == {"14oz can of tomatoes": erin.id}
    assert fake_keep.unchecked_texts(ERIN) == ["14oz can of tomatoes"]  # as they said it

    assert await sync(scenario) == 0
    assert fake_keep.calls["apply"] == 0  # nothing to write
    assert fake_keep.unchecked_texts(ERIN) == ["14oz can of tomatoes"]


async def test_each_persons_keep_shows_the_same_list(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    erin, husband = scenario.family.erin, scenario.family.husband
    link(scenario, fake_keep, erin, ERIN)
    link(scenario, fake_keep, husband, HIM)
    fake_keep.put(ERIN, "Limes")
    fake_keep.put(HIM, "Coffee")

    assert await sync(scenario) == 2
    assert needed(scenario) == {"limes": erin.id, "coffee": husband.id}
    await sync(scenario)  # Erin's list hears about the coffee on the next run
    assert sorted(fake_keep.unchecked_texts(ERIN)) == ["Limes", "coffee"]
    assert sorted(fake_keep.unchecked_texts(HIM)) == ["Coffee", "limes"]

    fake_keep.check(HIM, fake_keep.find(HIM, "limes").id)  # he buys them
    await sync(scenario)
    await sync(scenario)
    assert status(scenario, "limes") == "bought"
    assert fake_keep.checked_texts(ERIN) == ["Limes"]


async def test_a_duplicate_said_to_the_speaker_is_deleted_from_keep(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    groceries(scenario).add(["eggs"], by=scenario.family.husband)
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    await sync(scenario)
    assert fake_keep.unchecked_texts(ERIN) == ["eggs"]

    fake_keep.put(ERIN, "Eggs")
    assert await sync(scenario) == 0
    assert list(needed(scenario)) == ["eggs"]
    assert fake_keep.unchecked_texts(ERIN) == ["eggs"]


async def test_checked_off_in_keep_is_bought_and_the_pantry_has_it(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "Milk")
    await sync(scenario)

    fake_keep.check(ERIN, item)
    await sync(scenario)
    assert status(scenario, "milk") == "bought"
    pantry = scenario.app.db.one("SELECT status FROM pantry_items WHERE name = 'milk'")
    assert pantry is not None and pantry["status"] == "plenty"


async def test_deleted_in_keep_is_removed(scenario: Scenario, fake_keep: FakeKeep) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "Jam")
    await sync(scenario)

    fake_keep.delete(ERIN, item)
    await sync(scenario)
    assert status(scenario, "jam") == "removed"
    assert fake_keep.unchecked_texts(ERIN) == []


async def test_unchecked_in_keep_is_needed_again(scenario: Scenario, fake_keep: FakeKeep) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "Bread")
    await sync(scenario)
    fake_keep.check(ERIN, item)
    await sync(scenario)
    assert status(scenario, "bread") == "bought"

    fake_keep.uncheck(ERIN, item)
    assert await sync(scenario) == 1
    assert list(needed(scenario)) == ["bread"]
    assert fake_keep.unchecked_texts(ERIN) == ["Bread"]


async def test_old_checked_items_in_keep_are_left_alone(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    old = fake_keep.put(ERIN, "Nutmeg")
    fake_keep.check(ERIN, old)

    assert await sync(scenario) == 0
    assert needed(scenario) == {}
    assert fake_keep.checked_texts(ERIN) == ["Nutmeg"]


async def test_an_item_without_a_name_is_left_in_keep(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "🍅🍅")

    assert await sync(scenario) == 0
    assert await sync(scenario) == 0
    assert fake_keep.unchecked_texts(ERIN) == ["🍅🍅"]

    fake_keep.edit(ERIN, item, "tomatoes 🍅")  # edited: tried again
    assert await sync(scenario) == 1
    assert list(needed(scenario)) == ["tomatoes"]


# ----- to Keep ------------------------------------------------------------------------------


async def test_themis_list_reaches_keep(scenario: Scenario, fake_keep: FakeKeep) -> None:
    groceries(scenario).add(["apples", "rice", "foil"], by=scenario.family.erin)
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    await sync(scenario)
    assert fake_keep.unchecked_texts(ERIN) == ["apples", "rice", "foil"]

    groceries(scenario).finish("apples")  # bought: checked off
    groceries(scenario).finish("foil", "removed")  # removed: deleted
    groceries(scenario).add(["pears"], by=scenario.family.husband)
    assert await sync(scenario) == 0
    assert fake_keep.unchecked_texts(ERIN) == ["rice", "pears"]
    assert fake_keep.checked_texts(ERIN) == ["apples"]
    assert await sync(scenario) == 0
    assert fake_keep.unchecked_texts(ERIN) == ["rice", "pears"]


# ----- Themi wins, and Keep losing writes ---------------------------------------------------


async def test_themi_wins_over_a_keep_change_to_the_same_item(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "Cheese")
    await sync(scenario)

    groceries(scenario).finish("cheese", "removed")  # removed in Themi...
    fake_keep.check(ERIN, item)  # ...and bought in Keep, before the next sync
    await sync(scenario)
    assert status(scenario, "cheese") == "removed"


async def test_a_dropped_add_is_made_again_not_taken_as_a_delete(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    groceries(scenario).add(["salt"], by=scenario.family.erin)
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    fake_keep.drop_next_write()

    await sync(scenario)
    assert fake_keep.unchecked_texts(ERIN) == []
    await sync(scenario)
    assert status(scenario, "salt") == "needed"
    assert fake_keep.unchecked_texts(ERIN) == ["salt"]


async def test_a_dropped_check_off_is_made_again_not_taken_as_an_uncheck(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    fake_keep.put(ERIN, "Flour")
    await sync(scenario)
    groceries(scenario).finish("flour")
    fake_keep.drop_next_write()

    await sync(scenario)
    assert fake_keep.unchecked_texts(ERIN) == ["Flour"]  # Keep lost the check-off
    assert await sync(scenario) == 0
    assert status(scenario, "flour") == "bought"
    assert fake_keep.checked_texts(ERIN) == ["Flour"]


async def test_keep_down_waits_longer_each_time_and_keeps_others_going(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    link(scenario, fake_keep, scenario.family.husband, HIM)
    fake_keep.put(ERIN, "Rice")
    fake_keep.put(HIM, "Oats")
    fake_keep.fail("items")  # Erin's read comes first and fails

    assert await sync(scenario) == 1
    assert list(needed(scenario)) == ["oats"]
    reads = fake_keep.calls["items"]

    await sync(scenario)  # Erin's waits a minute
    assert fake_keep.calls["items"] == reads + 1

    clock.advance(timedelta(minutes=1))
    assert await sync(scenario) == 1
    assert "rice" in needed(scenario)


async def test_a_failed_write_keeps_what_keep_said_and_writes_next_time(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    groceries(scenario).add(["tea"], by=scenario.family.erin)
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    fake_keep.put(ERIN, "Honey")
    fake_keep.fail("apply")

    assert await sync(scenario) == 1
    assert sorted(needed(scenario)) == ["honey", "tea"]
    clock.advance(timedelta(minutes=2))
    await sync(scenario)
    assert sorted(fake_keep.unchecked_texts(ERIN)) == ["Honey", "tea"]


async def test_nobody_linked_does_nothing(scenario: Scenario, fake_keep: FakeKeep) -> None:
    groceries(scenario).add(["salt"], by=scenario.family.erin)
    assert await sync(scenario) == 0
    assert not fake_keep.calls


# ----- linking ------------------------------------------------------------------------------


async def test_linking_keeps_the_token_encrypted_and_checks_the_list(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    erin = scenario.family.erin
    fake_keep.user(ERIN, "Shopping list", "Ideas")
    fake_keep.put(ERIN, "Butter")
    said: list[str] = []
    answers = iter([ERIN])

    await run_keep_link(
        links(scenario),
        erin,
        "shopping list",
        lambda _: next(answers),
        lambda _: "oauth2_4/one-time-cookie",
        fake_keep.exchange,
        fake_keep.connect,
        said.append,
    )

    assert "EmbeddedSetup" in said[0]
    assert "the 1 unchecked item there now will join" in said[-1]
    (stored,) = links(scenario).all()
    assert (stored.member_id, stored.login.email, stored.list_name) == (
        erin.id,
        ERIN,
        "shopping list",
    )
    assert stored.login.master_token.reveal() == MASTER_TOKEN
    assert MASTER_TOKEN not in repr(stored)
    raw = scenario.app.db.one("SELECT master_token FROM keep_accounts")
    assert raw is not None and MASTER_TOKEN.encode() not in raw["master_token"]

    assert await sync(scenario) == 1  # the running app picks it up, no restart


async def test_linking_to_a_list_that_isnt_there_saves_nothing(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    fake_keep.user(ERIN, "Groceries")
    with pytest.raises(KeepError, match=r"no list called 'Shopping list'.*'Groceries'"):
        await run_keep_link(
            links(scenario),
            scenario.family.erin,
            "Shopping list",
            lambda _: ERIN,
            lambda _: "oauth2_4/one-time-cookie",
            fake_keep.exchange,
            fake_keep.connect,
            lambda _: None,
        )
    assert links(scenario).all() == []


async def test_a_bad_cookie_saves_nothing(scenario: Scenario, fake_keep: FakeKeep) -> None:
    with pytest.raises(KeepError, match="BadAuthentication"):
        await run_keep_link(
            links(scenario),
            scenario.family.erin,
            "Shopping list",
            lambda _: ERIN,
            lambda _: "not-a-cookie",
            fake_keep.exchange,
            fake_keep.connect,
            lambda _: None,
        )
    assert links(scenario).all() == []


async def test_unlinking_stops_the_sync(scenario: Scenario, fake_keep: FakeKeep) -> None:
    erin = scenario.family.erin
    link(scenario, fake_keep, erin, ERIN)
    assert links(scenario).unlink(erin)
    assert not links(scenario).unlink(erin)
    fake_keep.put(ERIN, "Jam")
    assert await sync(scenario) == 0
    assert fake_keep.unchecked_texts(ERIN) == ["Jam"]
