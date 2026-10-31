"""GK1: groceries said to Google Home land in Google Keep; Themi takes them onto the grocery
list and checks them off in Keep. Linked from the command line (`themi keep link`)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fakes.keep import MASTER_TOKEN, FakeKeep
from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts import Member
from themi.connectors.gkeep import KeepError, KeepLogin
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


async def sync(scenario: Scenario) -> object:
    return await scenario.run_periodic("groceries.keep")


def needed(scenario: Scenario) -> dict[str, int | None]:
    assert scenario.app.services.groceries is not None
    return {i.name: i.added_by for i in scenario.app.services.groceries.needed()}


async def test_an_item_said_to_the_speaker_goes_on_the_grocery_list(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    erin = scenario.family.erin
    link(scenario, fake_keep, erin, ERIN)
    fake_keep.put(ERIN, "14oz can of tomatoes")

    assert await sync(scenario) == 1
    assert needed(scenario) == {"14oz can of tomatoes": erin.id}
    assert fake_keep.unchecked_texts(ERIN) == []  # checked off in Keep

    assert await sync(scenario) == 0
    assert list(needed(scenario)) == ["14oz can of tomatoes"]


async def test_each_persons_keep_is_their_own(scenario: Scenario, fake_keep: FakeKeep) -> None:
    erin, husband = scenario.family.erin, scenario.family.husband
    link(scenario, fake_keep, erin, ERIN)
    link(scenario, fake_keep, husband, HIM)
    fake_keep.put(ERIN, "Limes")
    fake_keep.put(HIM, "Coffee")

    assert await sync(scenario) == 2
    assert needed(scenario) == {"limes": erin.id, "coffee": husband.id}


async def test_an_item_already_needed_isnt_added_twice(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    assert scenario.app.services.groceries is not None
    scenario.app.services.groceries.add(["eggs"], by=scenario.family.husband)
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    fake_keep.put(ERIN, "Eggs")

    assert await sync(scenario) == 0
    assert list(needed(scenario)) == ["eggs"]
    assert fake_keep.unchecked_texts(ERIN) == []


async def test_a_failed_check_off_is_retried_without_adding_again(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    assert scenario.app.services.groceries is not None
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    fake_keep.put(ERIN, "Milk")
    fake_keep.fail("check_off")

    assert await sync(scenario) == 1
    assert fake_keep.unchecked_texts(ERIN) == ["Milk"]
    scenario.app.services.groceries.finish("milk")  # bought meanwhile: not wanted again

    clock.advance(timedelta(minutes=2))
    assert await sync(scenario) == 0
    assert fake_keep.unchecked_texts(ERIN) == []
    assert needed(scenario) == {}


async def test_an_item_unchecked_in_keep_is_new_again(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    assert scenario.app.services.groceries is not None
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "Bread")
    await sync(scenario)
    scenario.app.services.groceries.finish("bread")

    fake_keep.uncheck(ERIN, item)
    assert await sync(scenario) == 1
    assert list(needed(scenario)) == ["bread"]
    assert fake_keep.unchecked_texts(ERIN) == []


async def test_an_item_without_a_name_is_left_in_keep(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    item = fake_keep.put(ERIN, "🍅🍅")

    assert await sync(scenario) == 0
    assert await sync(scenario) == 0
    assert fake_keep.unchecked_texts(ERIN) == ["🍅🍅"]
    assert fake_keep.calls["check_off"] == 0

    fake_keep.edit(ERIN, item, "tomatoes 🍅")  # edited: tried again
    assert await sync(scenario) == 1
    assert list(needed(scenario)) == ["tomatoes"]


async def test_keep_down_waits_longer_each_time_and_keeps_others_going(
    scenario: Scenario, fake_keep: FakeKeep
) -> None:
    link(scenario, fake_keep, scenario.family.erin, ERIN)
    link(scenario, fake_keep, scenario.family.husband, HIM)
    fake_keep.put(ERIN, "Rice")
    fake_keep.put(HIM, "Oats")
    fake_keep.fail("unchecked")  # Erin's read comes first and fails

    assert await sync(scenario) == 1
    assert list(needed(scenario)) == ["oats"]
    reads = fake_keep.calls["unchecked"]

    assert await sync(scenario) == 0  # Erin's waits a minute; his has nothing new
    assert fake_keep.calls["unchecked"] == reads + 1

    clock.advance(timedelta(minutes=1))
    assert await sync(scenario) == 1
    assert "rice" in needed(scenario)


async def test_nobody_linked_does_nothing(scenario: Scenario, fake_keep: FakeKeep) -> None:
    assert await sync(scenario) == 0
    assert not fake_keep.calls


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
    assert "1 item there now" in said[-1]
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
