"""30: the LG ThinQ connector against the fake: the token, discovery, polling and pushes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fakes.thinq import TOKEN, FakeThinq, payload
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.connectors.thinq import (
    FINISHED,
    RUNNING,
    ApplianceEvent,
    RateLimited,
    ThinqAccount,
    ThinqError,
    ThinqPush,
    ThinqWatcher,
    TokenRejected,
)

pytestmark = pytest.mark.usefixtures("frozen_clock")


def watcher_for(family: SeededFamily, fake: FakeThinq, *, pushes: bool = True) -> ThinqWatcher:
    config = fake.config(pushes=pushes)
    account = ThinqAccount(family.db, family.store.cipher, config)
    return ThinqWatcher(family.store, account, ThinqPush(account, config.mqtt))


def heard(watcher: ThinqWatcher) -> list[ApplianceEvent]:
    events: list[ApplianceEvent] = []

    async def listen(event: ApplianceEvent) -> None:
        events.append(event)

    watcher.listeners.append(listen)
    return events


@pytest.fixture
def laundry_room(fake_thinq: FakeThinq) -> FakeThinq:
    fake_thinq.add_device("lg-washer-1", "DEVICE_WASHER", "Washer")
    fake_thinq.add_device("lg-dryer-1", "DEVICE_DRYER", "Dryer", "DLEX4000W")
    fake_thinq.add_device("lg-fridge-1", "DEVICE_REFRIGERATOR", "Fridge", "LRMVS3006S")
    return fake_thinq


async def test_linking_keeps_the_token_encrypted_and_finds_the_appliances(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    added = await watcher.link(family.erin, f"  {TOKEN} ", "us")
    assert [(d.provider, d.external_id, d.name, d.appliance) for d in added] == [
        ("lg_thinq", "lg-washer-1", "Washer", "washer"),
        ("lg_thinq", "lg-dryer-1", "Dryer", "dryer"),
        ("lg_thinq", "lg-fridge-1", "Fridge", None),  # waits to be mapped, or left alone
    ]
    (row,) = family.db.query("SELECT token, country FROM thinq_account")
    assert TOKEN.encode() not in row["token"]
    assert family.store.cipher.decrypt(row["token"]).reveal() == TOKEN
    assert row["country"] == "US"
    assert await watcher.link(family.erin, TOKEN, "US") == []  # nothing new the second time


async def test_a_bad_token_or_country_isnt_kept(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    with pytest.raises(TokenRejected):
        await watcher.link(family.erin, "not-the-token", "US")
    with pytest.raises(ThinqError, match="country ZZ"):
        await watcher.link(family.erin, TOKEN, "ZZ")
    with pytest.raises(ThinqError, match="Paste"):
        await watcher.link(family.erin, "  ", "US")
    assert not watcher.account.linked()
    assert family.store.list_devices() == []


async def test_the_client_id_is_made_once(family: SeededFamily, laundry_room: FakeThinq) -> None:
    watcher = watcher_for(family, laundry_room)
    await watcher.link(family.erin, TOKEN, "US")
    first = family.db.scalar("SELECT client_id FROM thinq_account")
    await watcher.link(family.husband, TOKEN, "US")
    assert family.db.scalar("SELECT client_id FROM thinq_account") == first


async def test_polling_reports_changes_only(family: SeededFamily, laundry_room: FakeThinq) -> None:
    watcher = watcher_for(family, laundry_room, pushes=False)
    await watcher.link(family.erin, TOKEN, "US")
    events = heard(watcher)
    laundry_room.set_state("lg-washer-1", "washer_end")  # an old load, from before linking
    assert await watcher.poll() == 0  # the first read is only the starting point
    laundry_room.set_state("lg-washer-1", "washer_running")
    assert await watcher.poll() == 1
    clock.advance(timedelta(minutes=5))
    assert await watcher.poll() == 0  # still running
    laundry_room.set_state("lg-washer-1", "washer_end")
    assert await watcher.poll() == 1
    washer = watcher.devices("washer")[0]
    assert [(e.device_id, e.appliance, e.state) for e in events] == [
        (washer.id, "washer", RUNNING),
        (washer.id, "washer", FINISHED),
    ]
    assert watcher.states()[washer.id] == FINISHED


async def test_an_offline_appliance_says_nothing(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room, pushes=False)
    await watcher.link(family.erin, TOKEN, "US")
    await watcher.poll()
    laundry_room.offline("lg-washer-1")
    laundry_room.set_run_state("lg-dryer-1", "DRYING")
    laundry_room.offline("lg-washer-1")
    assert await watcher.poll() == 1  # the dryer, still read
    laundry_room.set_run_state("lg-washer-1", "POWER_OFF")
    assert await watcher.poll() == 0  # back, and as it was


async def test_a_rate_limit_is_waited_out_without_calling(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room, pushes=False)
    await watcher.link(family.erin, TOKEN, "US")
    laundry_room.limit()
    assert await watcher.poll() == 0
    calls = len(laundry_room.calls)
    with pytest.raises(RateLimited):
        await watcher.account.state("lg-washer-1")
    clock.advance(timedelta(minutes=10))
    assert await watcher.poll() == 0
    assert len(laundry_room.calls) == calls  # nothing sent while waiting
    clock.advance(timedelta(hours=1))
    await watcher.poll()
    assert len(laundry_room.calls) > calls


async def test_a_revoked_token_stops_reads_quietly(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room, pushes=False)
    await watcher.link(family.erin, TOKEN, "US")
    laundry_room.revoke()
    assert await watcher.poll() == 0
    with pytest.raises(TokenRejected):
        await watcher.account.devices()


async def test_pushes_connect_and_bring_changes(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    await watcher.link(family.erin, TOKEN, "US")
    events = heard(watcher)
    assert await watcher.listen() == 0
    assert watcher.push.connected()
    assert laundry_room.certificates == 1
    assert laundry_room.subscribed == {
        f"{kind}:{device}"
        for kind in ("push", "event")
        for device in ("lg-washer-1", "lg-dryer-1", "lg-fridge-1")
    }
    await watcher.poll()  # the starting point
    laundry_room.push_state("lg-washer-1", "RUNNING")
    laundry_room.push(payload("push_timer_only"))  # says nothing about running
    assert await watcher.listen() == 1
    laundry_room.push(payload("push_washing_complete"))
    laundry_room.push(payload("push_status_washer_end"))  # the same news twice
    assert await watcher.listen() == 1
    assert [e.state for e in events] == [RUNNING, FINISHED]
    assert laundry_room.certificates == 1  # one connection, kept


async def test_polling_steps_back_while_pushes_come_in(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    await watcher.link(family.erin, TOKEN, "US")
    await watcher.listen()
    await watcher.poll()
    reads = sum(c.endswith("/state") for c in laundry_room.calls)
    clock.advance(timedelta(minutes=30))
    await watcher.poll()
    assert sum(c.endswith("/state") for c in laundry_room.calls) == reads
    clock.advance(timedelta(minutes=31))  # an hour on: a safety read
    await watcher.poll()
    assert sum(c.endswith("/state") for c in laundry_room.calls) == reads + 3


async def test_a_push_connection_that_fails_leaves_polling_to_it(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    await watcher.link(family.erin, TOKEN, "US")
    laundry_room.limit()  # the client registration is turned down
    await watcher.listen()
    assert not watcher.push.connected()
    await watcher.poll()
    laundry_room.set_run_state("lg-washer-1", "RUNNING")
    clock.advance(timedelta(minutes=5))
    assert await watcher.poll() == 1  # read every 5 minutes meanwhile
    clock.advance(timedelta(minutes=5))
    await watcher.listen()
    assert not watcher.push.connected()  # waits before trying again
    clock.advance(timedelta(minutes=15))
    await watcher.listen()
    assert watcher.push.connected()


async def test_a_connection_that_never_comes_up_is_made_again(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    await watcher.link(family.erin, TOKEN, "US")
    laundry_room.broker_up = False
    await watcher.listen()
    clock.advance(timedelta(minutes=5))
    await watcher.listen()
    assert len(laundry_room.connections) == 1  # still connecting: left alone
    laundry_room.broker_up = True
    clock.advance(timedelta(minutes=11))
    await watcher.listen()
    assert len(laundry_room.connections) == 2 and laundry_room.connections[0].closed
    assert watcher.push.connected()


async def test_unlinking_forgets_the_token_and_the_appliances(
    family: SeededFamily, laundry_room: FakeThinq
) -> None:
    watcher = watcher_for(family, laundry_room)
    await watcher.link(family.erin, TOKEN, "US")
    await watcher.listen()
    await watcher.unlink()
    assert not watcher.account.linked()
    assert family.store.list_devices() == []
    assert laundry_room.connections[0].closed
    assert await watcher.poll() == 0 and await watcher.listen() == 0
