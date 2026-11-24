"""F61a (bug #266): a kind in `Outbox.past_busy` (the washer's "into the dryer?") isn't held
by busy times or calendar events, but quiet hours and a pause still hold it."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender, at
from themi import clock
from themi.accounts import SYSTEM, BusyTime, Member
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield


@pytest.fixture
def outbox(family: SeededFamily) -> Outbox:
    outbox = Outbox(family.store, FakeSender(), PdaShield(None))
    outbox.past_busy.add("laundry")
    return outbox


def at_work(family: SeededFamily) -> Member:
    return family.store.update_settings(
        SYSTEM, family.erin.id, busy_times=[BusyTime((0, 1, 2, 3, 4), time(9), time(17))]
    )


async def queued_for(outbox: Outbox, member: Member, kind: str, moment: datetime) -> datetime:
    result = await outbox.send(
        member, "The washer finished.", priority=Priority.NORMAL, kind=kind,
        not_before=moment, deadline=moment,
    )  # fmt: skip
    assert result.send_after is not None
    return result.send_after


async def test_a_busy_time_doesnt_hold_it(family: SeededFamily, outbox: Outbox) -> None:
    erin = at_work(family)
    clock.freeze(at(21, 12, 40))
    assert await queued_for(outbox, erin, "laundry", at(21, 13, 10)) == at(21, 13, 10)
    assert await queued_for(outbox, erin, "task", at(21, 13, 10)) == at(21, 17)  # as before


async def test_a_calendar_event_doesnt_hold_it(family: SeededFamily, outbox: Outbox) -> None:
    outbox.calendar_blocks = lambda member, start, end: [(at(21, 13), at(21, 15))]
    clock.freeze(at(21, 12, 40))
    assert await queued_for(outbox, family.erin, "laundry", at(21, 13, 10)) == at(21, 13, 10)


async def test_quiet_hours_and_a_pause_still_hold_it(family: SeededFamily, outbox: Outbox) -> None:
    clock.freeze(at(21, 22, 30))  # Erin's quiet hours, 21:30-08:00
    assert await queued_for(outbox, family.erin, "laundry", at(21, 23)) == at(22, 8)
    clock.freeze(at(22, 10))
    outbox.pauses.pause(family.erin, "laundry", at(22, 12))
    assert await queued_for(outbox, family.erin, "laundry", at(22, 10, 30)) == at(22, 12)
