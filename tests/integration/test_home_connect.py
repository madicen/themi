"""H1: the Home Connect client and the family's sign-in, against the fake."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fakes.home_connect import FakeHomeConnect
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.connectors.homeconnect import (
    ApplianceOffline,
    HomeConnectAccount,
    HomeConnectError,
    LinkRevoked,
    RateLimited,
)

pytestmark = pytest.mark.usefixtures("frozen_clock")

REDIRECT = "http://themi.test/auth/home-connect/callback"


def account_for(family: SeededFamily, fake: FakeHomeConnect) -> HomeConnectAccount:
    return HomeConnectAccount(family.db, family.store.cipher, fake.client())


async def linked(family: SeededFamily, fake: FakeHomeConnect) -> HomeConnectAccount:
    account = account_for(family, fake)
    state, code = fake.approve(account.authorization_url(family.erin, REDIRECT))
    assert await account.complete(state, code, REDIRECT) == family.erin.id
    return account


async def test_linking_keeps_the_refresh_token_encrypted(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    account = await linked(family, fake_home_connect)
    assert account.linked()
    (row,) = family.db.query("SELECT refresh_token FROM home_connect_account")
    (refresh,) = fake_home_connect.refresh_tokens
    assert refresh.encode() not in row["refresh_token"]
    assert family.store.cipher.decrypt(row["refresh_token"]).reveal() == refresh


async def test_a_state_works_once_and_not_after_ten_minutes(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    account = account_for(family, fake_home_connect)
    state, code = fake_home_connect.approve(account.authorization_url(family.erin, REDIRECT))
    await account.complete(state, code, REDIRECT)
    with pytest.raises(HomeConnectError, match="expired or was already used"):
        await account.complete(state, code, REDIRECT)

    state, code = fake_home_connect.approve(account.authorization_url(family.erin, REDIRECT))
    clock.advance(timedelta(minutes=11))
    with pytest.raises(HomeConnectError, match="expired"):
        await account.complete(state, code, REDIRECT)


async def test_reads_appliances_and_the_operation_state(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance("BOSCH-SMV-1", "Dishwasher", "Dishwasher")
    fake_home_connect.add_appliance("BOSCH-WAT-1", "Washer", "Washer")
    account = await linked(family, fake_home_connect)
    appliances = await account.appliances()
    assert [(a.ha_id, a.kind, a.brand) for a in appliances] == [
        ("BOSCH-SMV-1", "Dishwasher", "Bosch"),
        ("BOSCH-WAT-1", "Washer", "Bosch"),
    ]
    assert await account.operation_state("BOSCH-SMV-1") == "Ready"
    fake_home_connect.set_state("BOSCH-SMV-1", "Run")
    assert await account.operation_state("BOSCH-SMV-1") == "Run"


async def test_an_expired_access_token_is_refreshed_and_the_new_refresh_token_kept(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance("BOSCH-SMV-1", "Dishwasher")
    account = await linked(family, fake_home_connect)
    (first,) = fake_home_connect.refresh_tokens
    clock.advance(timedelta(hours=24))
    assert await account.operation_state("BOSCH-SMV-1") == "Ready"
    (second,) = fake_home_connect.refresh_tokens
    assert second != first
    (row,) = family.db.query("SELECT refresh_token FROM home_connect_account")
    assert family.store.cipher.decrypt(row["refresh_token"]).reveal() == second

    # A fresh process has no access token in memory: it refreshes from the stored one.
    again = account_for(family, fake_home_connect)
    assert await again.operation_state("BOSCH-SMV-1") == "Ready"


async def test_a_revoked_link_says_so(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance("BOSCH-SMV-1", "Dishwasher")
    account = await linked(family, fake_home_connect)
    fake_home_connect.revoke()
    with pytest.raises(LinkRevoked, match="link it again"):
        await account.operation_state("BOSCH-SMV-1")


async def test_an_offline_appliance(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance("BOSCH-SMV-1", "Dishwasher")
    account = await linked(family, fake_home_connect)
    fake_home_connect.offline("BOSCH-SMV-1")
    with pytest.raises(ApplianceOffline):
        await account.operation_state("BOSCH-SMV-1")


async def test_a_rate_limit_is_waited_out_without_calling_again(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance("BOSCH-SMV-1", "Dishwasher")
    account = await linked(family, fake_home_connect)
    fake_home_connect.limit()
    with pytest.raises(RateLimited) as raised:
        await account.operation_state("BOSCH-SMV-1")
    assert raised.value.wait == timedelta(minutes=10)
    calls = len(fake_home_connect.calls)
    with pytest.raises(RateLimited):
        await account.operation_state("BOSCH-SMV-1")
    assert len(fake_home_connect.calls) == calls  # still waiting: Home Connect isn't asked
    clock.advance(timedelta(minutes=10))
    assert await account.operation_state("BOSCH-SMV-1") == "Ready"


async def test_unlinking_forgets_the_sign_in_and_its_devices(
    family: SeededFamily, fake_home_connect: FakeHomeConnect
) -> None:
    account = await linked(family, fake_home_connect)
    family.store.add_device(family.erin, "home_connect", "BOSCH-SMV-1", "Dishwasher", "dishwasher")
    account.unlink()
    assert not account.linked()
    assert family.store.list_devices() == []
