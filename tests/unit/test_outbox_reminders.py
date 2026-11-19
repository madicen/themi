"""F50a (bug #231): a reminder someone set goes at the time they set, whatever else is going
on; and a message held past its expiry is dropped there and then, saying what held it."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

import pytest

from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender, TrayAll, at
from themi import clock
from themi.accounts import SYSTEM, BusyTime, Member
from themi.channels.outbox import Outbox, OutboxResult, Priority
from themi.channels.pda import PdaShield


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def outbox(family: SeededFamily, sender: FakeSender) -> Outbox:
    return Outbox(family.store, sender, PdaShield(None))


async def remind(outbox: Outbox, member: Member, moment: datetime, text: str) -> OutboxResult:
    """As `add_reminder` queues one."""
    return await outbox.send(
        member,
        f"Reminder: {text}",
        priority=Priority.NORMAL,
        kind="reminder",
        not_before=moment,
        deadline=moment,
        expires=moment + timedelta(hours=2),
        dedupe_key=f"reminder-{moment.isoformat()}-{text.casefold()}",
    )


async def goes_at(outbox: Outbox, sender: FakeSender, moment: datetime) -> list[str]:
    clock.freeze(moment - timedelta(minutes=1))
    assert await outbox.flush() == 0
    clock.freeze(moment)
    await outbox.flush()
    return sender.texts()


async def test_a_reminder_inside_a_busy_time_goes_at_its_time(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    """Bug #231: 10 am inside Michael's 9-5 was held to 5 pm, past its expiry, and lost."""
    erin = family.store.update_settings(
        SYSTEM, family.erin.id, busy_times=[BusyTime((0, 1, 2, 3, 4), time(9), time(17))]
    )
    clock.freeze(at(20, 21, 15))  # Tuesday night, quiet hours
    queued = await remind(outbox, erin, at(21, 10), "Call 650-723-5001")
    assert (queued.status, queued.send_after) == ("queued", at(21, 10))
    assert await goes_at(outbox, sender, at(21, 10)) == ["Reminder: Call 650-723-5001"]


async def test_a_reminder_inside_quiet_hours_goes_at_its_time(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 18))
    await remind(outbox, family.erin, at(21, 23), "Take the bins out")
    assert await goes_at(outbox, sender, at(21, 23)) == ["Reminder: Take the bins out"]


async def test_a_reminder_inside_a_calendar_event_goes_at_its_time(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    outbox.calendar_blocks = lambda member, start, end: [(at(21, 13), at(21, 15))]
    clock.freeze(at(21, 9))
    await remind(outbox, family.erin, at(21, 14), "Ring the vet")
    assert await goes_at(outbox, sender, at(21, 14)) == ["Reminder: Ring the vet"]


async def test_a_reminder_goes_during_a_cooking_pause_or_a_pause_on_everything(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 9))
    outbox.pauses.pause(family.erin, "cooking", at(21, 16))
    outbox.pauses.pause(family.erin, "everything", at(21, 16))
    await remind(outbox, family.erin, at(21, 11), "Call the plumber")
    assert await goes_at(outbox, sender, at(21, 11)) == ["Reminder: Call the plumber"]


async def test_a_reminder_goes_over_the_daily_limit_and_isnt_counted(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    erin = family.store.update_settings(SYSTEM, family.erin.id, daily_limit=1)
    clock.freeze(at(21, 9))
    assert (await outbox.send(erin, "one", priority=Priority.NORMAL)).status == "sent"
    await remind(outbox, erin, at(21, 11), "Call the plumber")
    assert await goes_at(outbox, sender, at(21, 11)) == ["one", "Reminder: Call the plumber"]
    assert outbox.sent_today(erin.id) == 1


async def test_a_reminder_isnt_put_in_the_morning_tray(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    outbox.tray = TrayAll()
    clock.freeze(at(20, 20))
    await remind(outbox, family.erin, at(21, 8, 30), "Pack the lunch")
    assert await goes_at(outbox, sender, at(21, 8, 30)) == ["Reminder: Pack the lunch"]
    assert outbox.trayed(family.erin.id) == []


async def test_a_message_held_past_its_expiry_is_dropped_saying_what_held_it(
    family: SeededFamily, outbox: Outbox, sender: FakeSender, caplog: pytest.LogCaptureFixture
) -> None:
    erin = family.store.update_settings(
        SYSTEM, family.erin.id, busy_times=[BusyTime((0, 1, 2, 3, 4), time(9), time(17))]
    )
    clock.freeze(at(21, 8, 30))  # queued before the busy time, due to go at 8:45
    queued = await outbox.send(
        erin, "The washer finished.", priority=Priority.NORMAL, kind="laundry",
        not_before=at(21, 8, 45), expires=at(21, 12),
    )  # fmt: skip
    assert queued.send_after == at(21, 8, 45)
    erin = family.store.update_settings(  # the busy time starts earlier now
        SYSTEM, erin.id, busy_times=[BusyTime((0, 1, 2, 3, 4), time(8, 40), time(17))]
    )
    clock.freeze(at(21, 8, 45))
    with caplog.at_level(logging.WARNING, logger="themi.channels.outbox"):
        assert await outbox.flush() == 0
    assert family.db.one("SELECT id FROM outbox WHERE id = ?", (queued.outbox_id,)) is None
    line = next(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert f"message {queued.outbox_id}" in line and "laundry" in line and "busy time" in line
    clock.freeze(at(21, 17))
    assert await outbox.flush() == 0
    assert sender.texts() == []


async def test_a_message_that_couldnt_go_before_its_expiry_isnt_queued(
    family: SeededFamily, outbox: Outbox, sender: FakeSender, caplog: pytest.LogCaptureFixture
) -> None:
    erin = family.store.update_settings(
        SYSTEM, family.erin.id, busy_times=[BusyTime((0, 1, 2, 3, 4), time(9), time(17))]
    )
    clock.freeze(at(21, 10))
    with caplog.at_level(logging.WARNING, logger="themi.channels.outbox"):
        result = await outbox.send(
            erin, "The washer finished.", priority=Priority.NORMAL, kind="laundry",
            expires=at(21, 12),
        )  # fmt: skip
    assert (result.status, result.outbox_id) == ("failed", None)
    assert family.db.scalar("SELECT COUNT(*) FROM outbox") == 0
    assert any("busy time" in r.getMessage() for r in caplog.records)
