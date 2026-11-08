"""V1: the Roborock connector against the fake: the emailed-code sign-in, kept encrypted;
discovery; reads that report changes only; an offline robot; a sign-in that stops working."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from tests.fakes.roborock import CODE, EMAIL, SECRET_TOKEN, FakeRoborock
from tests.fixtures.family import SeededFamily
from themi import clock
from themi_home.connectors.roborock import (
    JAMMED,
    PART,
    STUCK,
    BadCode,
    LoginExpired,
    RoborockAccount,
    RoborockWatcher,
    VacuumEvent,
)

pytestmark = pytest.mark.usefixtures("frozen_clock")
ROBOT = "rr-duid-1"


def watcher_for(family: SeededFamily, fake: FakeRoborock) -> RoborockWatcher:
    return RoborockWatcher(family.store, RoborockAccount(family.db, family.store.cipher, fake))


def heard(watcher: RoborockWatcher) -> list[VacuumEvent]:
    events: list[VacuumEvent] = []

    async def listen(event: VacuumEvent) -> None:
        events.append(event)

    watcher.listeners.append(listen)
    return events


async def linked(family: SeededFamily, fake: FakeRoborock) -> RoborockWatcher:
    fake.add_robot(ROBOT, "Robbie")
    watcher = watcher_for(family, fake)
    await watcher.send_code(EMAIL)
    await watcher.link(family.erin, EMAIL, CODE)
    return watcher


async def test_linking_by_emailed_code_keeps_the_login_encrypted(
    family: SeededFamily, fake_roborock: FakeRoborock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake_roborock.add_robot(ROBOT, "Robbie")
    watcher = watcher_for(family, fake_roborock)
    assert await watcher.send_code("  Family@Example.com ") == EMAIL
    assert fake_roborock.codes_sent == [EMAIL]
    added = await watcher.link(family.erin, EMAIL, f" {CODE} ")
    assert [(d.provider, d.external_id, d.name, d.appliance) for d in added] == [
        ("roborock", ROBOT, "Robbie", "vacuum")
    ]
    row = family.db.one("SELECT * FROM roborock_account")
    assert row is not None and row["email"] == EMAIL and row["linked_by"] == family.erin.id
    assert SECRET_TOKEN.encode() not in row["login"]  # encrypted at rest
    assert SECRET_TOKEN not in caplog.text
    # Linking again finds nothing new.
    await watcher.send_code(EMAIL)
    assert await watcher.link(family.erin, EMAIL, CODE) == []


async def test_a_wrong_code_or_email_isnt_kept(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = watcher_for(family, fake_roborock)
    with pytest.raises(BadCode):
        await watcher.link(family.erin, EMAIL, CODE)  # no code was sent
    await watcher.send_code(EMAIL)
    with pytest.raises(BadCode):
        await watcher.link(family.erin, EMAIL, "000000")
    with pytest.raises(BadCode):
        await watcher.link(family.erin, EMAIL, "  ")
    assert not watcher.account.linked()
    with pytest.raises(Exception, match="email address"):
        await watcher.send_code("not an email")


async def test_the_first_read_is_the_starting_point_then_changes_only(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    events = heard(watcher)
    fake_roborock.set_status(ROBOT, "main_brush_jammed")
    assert await watcher.poll() == 0  # already jammed when linked: not announced
    assert watcher.states() == {watcher.devices()[0].id: "stopped with a problem"}
    fake_roborock.set_status(ROBOT, "cleaning")
    assert await watcher.poll() == 1
    assert events[-1].kind == JAMMED and events[-1].gone
    fake_roborock.set_status(ROBOT, "trapped")
    assert await watcher.poll() == 1
    assert (events[-1].kind, events[-1].detail, events[-1].gone) == (STUCK, "it's trapped", False)
    assert await watcher.poll() == 0  # the same, read again


async def test_the_room_is_looked_up_for_a_stuck_robot_only(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    events = heard(watcher)
    fake_roborock.rooms[ROBOT] = "Kitchen"
    await watcher.poll()
    fake_roborock.set_status(ROBOT, "main_brush_jammed")
    clock.advance(timedelta(minutes=5))
    await watcher.poll()
    assert events[-1].room is None and fake_roborock.room_reads == 0
    fake_roborock.set_status(ROBOT, "trapped")
    await watcher.poll()
    assert events[-1].room == "Kitchen" and fake_roborock.room_reads == 1


async def test_a_calm_robot_is_read_every_five_minutes_a_busy_one_every_run(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    await watcher.poll()
    reads = fake_roborock.reads
    clock.advance(timedelta(minutes=1))
    await watcher.poll()
    assert fake_roborock.reads == reads  # docked: it waits
    clock.advance(timedelta(minutes=4))
    await watcher.poll()
    assert fake_roborock.reads == reads + 1
    fake_roborock.set_status(ROBOT, "cleaning")
    clock.advance(timedelta(minutes=5))
    await watcher.poll()
    clock.advance(timedelta(minutes=1))
    await watcher.poll()
    assert fake_roborock.reads == reads + 3  # cleaning: every run


async def test_an_offline_robot_says_nothing(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    events = heard(watcher)
    await watcher.poll()
    fake_roborock.offline(ROBOT)
    clock.advance(timedelta(minutes=5))
    assert await watcher.poll() == 0
    assert list(watcher.states().values()) == ["offline"]
    assert events == []


async def test_worn_parts_are_read_every_six_hours(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    events = heard(watcher)
    await watcher.poll()  # the parts' starting point too
    fake_roborock.set_parts(ROBOT, filter_work_time=530_000)
    clock.advance(timedelta(hours=1))
    await watcher.poll()
    assert events == []
    clock.advance(timedelta(hours=5))
    await watcher.poll()
    assert [(e.kind, e.detail, e.gone) for e in events] == [(PART, "filter", False)]
    fake_roborock.set_parts(ROBOT, filter_work_time=0)  # replaced, counter reset in the app
    clock.advance(timedelta(hours=6))
    await watcher.poll()
    assert [(e.kind, e.detail, e.gone) for e in events][-1] == (PART, "filter", True)


async def test_a_sign_in_that_stops_working_is_told_once_and_reads_stop(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    told: list[str] = []

    async def tell(why: str) -> None:
        told.append(why)

    watcher.expired_listeners.append(tell)
    await watcher.poll()
    fake_roborock.expire()
    clock.advance(timedelta(minutes=5))
    assert await watcher.poll() == 0
    assert len(told) == 1
    assert watcher.account.problem() is not None
    reads = fake_roborock.reads
    clock.advance(timedelta(minutes=5))
    await watcher.poll()
    assert fake_roborock.reads == reads and len(told) == 1  # quiet until linked again
    with pytest.raises(LoginExpired):
        await watcher.read(watcher.devices()[0])
    # Linking again clears it.
    await watcher.send_code(EMAIL)
    await watcher.link(family.erin, EMAIL, CODE)
    assert watcher.account.problem() is None
    clock.advance(timedelta(minutes=5))
    await watcher.poll()
    assert fake_roborock.reads == reads + 1


async def test_unlinking_forgets_the_sign_in_and_the_robot(
    family: SeededFamily, fake_roborock: FakeRoborock
) -> None:
    watcher = await linked(family, fake_roborock)
    session = fake_roborock.sessions[-1]
    await watcher.unlink()
    assert not watcher.account.linked()
    assert watcher.devices() == []
    assert session.closed
    assert await watcher.poll() == 0
