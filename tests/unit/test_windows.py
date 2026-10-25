from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender
from themi import clock
from themi.accounts import Member
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield
from themi.energy.model import EnergyModel
from themi.energy.windows import EnergyReceptivity, Window, next_window, windows

PACIFIC = ZoneInfo("America/Los_Angeles")
WEDNESDAY = 2


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


def set_day(
    family: SeededFamily,
    member: Member,
    values: dict[int, float],
    default: float,
    weekday: int = WEDNESDAY,
) -> None:
    """Give `member` a confident learned baseline for one weekday (hour -> capacity)."""
    for hour in range(24):
        family.db.execute(
            "INSERT OR REPLACE INTO energy_baseline (member_id, hour_of_week, mean, n, updated_at)"
            " VALUES (?, ?, ?, 100000, '2026-10-01')",
            (member.id, weekday * 24 + hour, values.get(hour, default)),
        )


@pytest.fixture
def model(family: SeededFamily) -> EnergyModel:
    return EnergyModel(family.store)


def test_the_first_window_follows_the_baseline(model: EnergyModel, family: SeededFamily) -> None:
    set_day(family, family.erin, {13: 80, 14: 80, 15: 80}, default=30)
    clock.freeze(at(21, 9))
    assert next_window(model, family.erin, at(21, 9)) == at(21, 13)
    first = windows(model, family.erin, at(21, 9), horizon=at(21, 20) - at(21, 9))[0]
    assert first == Window(at(21, 13), at(21, 16))


def test_low_priority_waits_for_a_strong_window(model: EnergyModel, family: SeededFamily) -> None:
    set_day(family, family.erin, {11: 50, 14: 70}, default=30)
    clock.freeze(at(21, 9))
    assert next_window(model, family.erin, at(21, 9), threshold=45) == at(21, 11)
    assert next_window(model, family.erin, at(21, 9), threshold=60) == at(21, 14)


def test_quiet_hours_are_never_a_window(model: EnergyModel, family: SeededFamily) -> None:
    set_day(family, family.erin, {22: 90, 23: 90}, default=30)
    clock.freeze(at(21, 20))
    found = next_window(model, family.erin, at(21, 20))
    assert found >= at(22, 8)  # Erin's quiet hours run 21:30 to 08:00


def test_with_no_good_window_the_best_moment_is_used(
    model: EnergyModel, family: SeededFamily
) -> None:
    for weekday in range(7):
        set_day(family, family.erin, {15: 40}, default=20, weekday=weekday)
    clock.freeze(at(21, 9))
    assert next_window(model, family.erin, at(21, 9)) == at(21, 15)  # 40: below 45, but best


def test_a_draining_day_pushes_the_window_later(model: EnergyModel, family: SeededFamily) -> None:
    set_day(family, family.erin, {}, default=55)
    clock.freeze(at(21, 9))
    calm = next_window(model, family.erin, at(21, 9))
    model.record(family.erin, "text_note", -3, "rough morning")
    drained = next_window(model, family.erin, at(21, 9))
    assert calm == at(21, 9) and drained > at(21, 9)


def test_windows_are_per_member(model: EnergyModel, family: SeededFamily) -> None:
    set_day(family, family.erin, {}, default=20)
    set_day(family, family.husband, {}, default=70)
    clock.freeze(at(21, 9))
    assert next_window(model, family.husband, at(21, 9)) == at(21, 9)
    assert next_window(model, family.erin, at(21, 9)) != at(21, 9)


# ----- the outbox, timed by the model --------------------------------------------


@pytest.fixture
def outbox(family: SeededFamily, model: EnergyModel) -> tuple[Outbox, FakeSender]:
    sender = FakeSender()
    return Outbox(family.store, sender, PdaShield(None), EnergyReceptivity(model)), sender


async def test_normal_messages_wait_for_a_window(
    family: SeededFamily, outbox: tuple[Outbox, FakeSender]
) -> None:
    box, sender = outbox
    set_day(family, family.erin, {13: 80}, default=30)
    clock.freeze(at(21, 9))
    result = await box.send(family.erin, "The filter is due.", priority=Priority.NORMAL)
    assert result.status == "queued" and result.send_after == at(21, 13)
    clock.freeze(at(21, 12, 45))
    assert await box.flush() == 0
    clock.freeze(at(21, 13))
    assert await box.flush() == 1 and sender.texts() == ["The filter is due."]


async def test_low_priority_waits_longer(
    family: SeededFamily, outbox: tuple[Outbox, FakeSender]
) -> None:
    box, _ = outbox
    set_day(family, family.erin, {11: 50, 16: 75}, default=30)
    clock.freeze(at(21, 9))
    normal = await box.send(family.erin, "normal", priority=Priority.NORMAL)
    low = await box.send(family.erin, "low", priority=Priority.LOW)
    assert (normal.send_after, low.send_after) == (at(21, 11), at(21, 16))


async def test_deadlines_beat_windows(
    family: SeededFamily, outbox: tuple[Outbox, FakeSender]
) -> None:
    box, _ = outbox
    set_day(family, family.erin, {15: 80}, default=30)
    clock.freeze(at(21, 9))
    result = await box.send(family.erin, "relay", priority=Priority.NORMAL, deadline=at(21, 11))
    assert result.send_after == at(21, 11)


async def test_replies_and_urgent_never_wait(
    family: SeededFamily, outbox: tuple[Outbox, FakeSender]
) -> None:
    box, _ = outbox
    set_day(family, family.erin, {}, default=10)
    clock.freeze(at(21, 9))
    assert (await box.send(family.erin, "ok", priority=Priority.REPLY)).status == "sent"
    assert (await box.send(family.erin, "leak", priority=Priority.URGENT)).status == "sent"


async def test_no_read_means_no_holding_back(
    family: SeededFamily, outbox: tuple[Outbox, FakeSender]
) -> None:
    box, _ = outbox
    set_day(family, family.erin, {}, default=10)
    erin = family.store.update_settings(
        family.erin,
        family.erin.id,
        tracking={"text_notes": False, "message_timing": False, "device_activity": False},
    )
    clock.freeze(at(21, 9))
    assert (await box.send(erin, "hi", priority=Priority.NORMAL)).status == "sent"
