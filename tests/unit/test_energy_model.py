import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import Member
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield
from themi.energy.model import (
    DAY_LEVEL_TARGETS,
    LABELS,
    NOT_TRACKED,
    PRIOR_CURVE,
    EnergyModel,
    Signal,
    combine,
    hour_of_week,
    label_for,
    prior,
    signal_effect,
)

TZ = "America/Los_Angeles"
PACIFIC = ZoneInfo(TZ)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


@pytest.fixture
def model(family: SeededFamily) -> EnergyModel:
    return EnergyModel(family.store)


# ----- the maths ------------------------------------------------------------------


def test_signals_halve_every_recovery_period() -> None:
    assert signal_effect(-3, timedelta(0), 8) == -24
    assert signal_effect(-3, timedelta(hours=8), 8) == pytest.approx(-12)
    assert signal_effect(-3, timedelta(hours=16), 8) == pytest.approx(-6)
    assert signal_effect(2, timedelta(hours=4), 4) == pytest.approx(8)
    assert signal_effect(-3, timedelta(hours=-1), 8) == 0  # future signals don't count


def test_faster_recovery_fades_faster() -> None:
    slow = signal_effect(-3, timedelta(hours=8), 8)
    fast = signal_effect(-3, timedelta(hours=8), 4)
    assert abs(fast) < abs(slow)


def test_the_prior_curve_is_low_at_night_and_highest_late_morning() -> None:
    assert len(PRIOR_CURVE) == 24
    assert prior(3) < prior(9) < prior(11)
    assert max(PRIOR_CURVE) == prior(11)
    assert prior(23) < prior(18)


def test_hour_of_week_is_local_monday_based() -> None:
    assert hour_of_week(datetime(2026, 10, 19, 0, 30, tzinfo=PACIFIC), TZ) == 0  # Monday 00:30
    assert hour_of_week(datetime(2026, 10, 21, 16, 0, tzinfo=UTC), TZ) == 2 * 24 + 9  # Wed 09:00


@given(
    baseline=st.floats(min_value=0, max_value=100),
    values=st.lists(st.floats(min_value=-3, max_value=3), max_size=40),
    ages=st.lists(st.floats(min_value=0, max_value=200), max_size=40),
    recovery=st.floats(min_value=0.5, max_value=72),
)
def test_capacity_always_stays_between_0_and_100(
    baseline: float, values: list[float], ages: list[float], recovery: float
) -> None:
    now = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)
    signals = [
        Signal("text_note", v, now - timedelta(hours=a)) for v, a in zip(values, ages, strict=False)
    ]
    assert 0.0 <= combine(baseline, signals, now, recovery) <= 100.0


# ----- labels ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("capacity", "words"),
    [
        (0, "running low today, it seems"),
        (24.9, "running low today, it seems"),
        (25, "seems like a low stretch"),
        (50, "steady"),
        (70, "seems to have some energy"),
        (95, "seems to be in a good stretch"),
        (100, "seems to be in a good stretch"),
    ],
)
def test_labels_map_from_ranges(capacity: float, words: str) -> None:
    assert label_for(capacity) == words


def test_no_label_ever_contains_a_number() -> None:
    for capacity in range(101):
        assert not re.search(r"\d", label_for(capacity))
    assert not re.search(r"\d", NOT_TRACKED)
    assert all(not re.search(r"\d", words) for _, words in LABELS)


# ----- the model over the database ------------------------------------------------


def test_capacity_starts_from_the_prior(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    assert model.capacity(family.erin) == prior(9)
    assert model.label(family.erin) == "steady"


def test_a_draining_note_lowers_capacity_and_fades(
    model: EnergyModel, family: SeededFamily
) -> None:
    clock.freeze(at(21, 9))
    assert model.record(family.erin, "text_note", -3, "long client call")
    assert model.capacity(family.erin) == pytest.approx(prior(9) - 24)
    assert model.label(family.erin) == "seems like a low stretch"
    clock.freeze(at(21, 17))  # Erin recovers with an 8-hour half-life
    assert model.capacity(family.erin) == pytest.approx(prior(17) - 12)


def test_values_are_clamped_to_the_scale(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    model.record(family.erin, "text_note", -10)
    (row,) = family.db.query("SELECT value FROM energy_signals")
    assert row["value"] == -3


def test_learned_baselines_blend_with_the_prior(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    hour = hour_of_week(clock.now(), TZ)
    family.db.execute(
        "INSERT INTO energy_baseline (member_id, hour_of_week, mean, n, updated_at) "
        "VALUES (?, ?, 85, 3, '2026-10-20')",
        (family.erin.id, hour),
    )
    assert model.baseline(family.erin) == pytest.approx((85 + prior(9)) / 2)
    assert model.baseline(family.husband) == prior(9)


def test_switched_off_inputs_are_not_recorded_or_used(
    model: EnergyModel, family: SeededFamily
) -> None:
    clock.freeze(at(21, 9))
    model.record(family.erin, "text_note", -3)
    erin = family.store.update_settings(family.erin, family.erin.id, tracking={"text_notes": False})
    assert model.capacity(erin) == prior(9)  # the old note no longer counts
    assert not model.record(erin, "text_note", -3)
    assert family.db.scalar("SELECT COUNT(*) FROM energy_signals") == 1


def test_everything_off_means_no_read(model: EnergyModel, family: SeededFamily) -> None:
    erin = family.store.update_settings(
        family.erin,
        family.erin.id,
        tracking={"text_notes": False, "message_timing": False, "device_activity": False},
    )
    assert model.label(erin) == NOT_TRACKED


def test_signals_are_private_to_each_member(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    model.record(family.erin, "text_note", -3)
    assert model.capacity(family.husband) == prior(9)


# ----- reply latency --------------------------------------------------------------


async def proactive(family: SeededFamily, member: Member, text: str = "Washer's done.") -> None:
    from tests.unit.test_outbox import FakeSender

    outbox = Outbox(family.store, FakeSender(), PdaShield(None))
    await outbox.send(member, text, priority=Priority.NORMAL)


async def test_a_quick_reply_is_a_small_positive_signal(
    model: EnergyModel, family: SeededFamily
) -> None:
    clock.freeze(at(21, 10))
    await proactive(family, family.erin)
    model.observe_inbound(family.erin, at(21, 10, 5))
    model.observe_inbound(family.erin, at(21, 10, 6))  # the same message isn't counted twice
    rows = family.db.query("SELECT source, value FROM energy_signals")
    assert rows == [{"source": "message_timing", "value": 0.5}]


@pytest.mark.parametrize(("minutes", "value"), [(45, 0.0), (180, -0.5)])
async def test_slower_replies(
    model: EnergyModel, family: SeededFamily, minutes: int, value: float
) -> None:
    clock.freeze(at(21, 10))
    await proactive(family, family.erin)
    model.observe_inbound(family.erin, at(21, 10) + timedelta(minutes=minutes))
    assert family.db.scalar("SELECT value FROM energy_signals") == value


async def test_very_late_replies_and_replies_to_replies_say_nothing(
    model: EnergyModel, family: SeededFamily
) -> None:
    clock.freeze(at(21, 10))
    await proactive(family, family.erin)
    model.observe_inbound(family.erin, at(21, 23, 30))
    assert family.db.scalar("SELECT COUNT(*) FROM energy_signals") == 0
    model.observe_inbound(family.husband, at(21, 10, 5))  # nothing was sent to him
    assert family.db.scalar("SELECT COUNT(*) FROM energy_signals") == 0


async def test_reply_timing_respects_its_toggle(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 10))
    erin = family.store.update_settings(
        family.erin, family.erin.id, tracking={"message_timing": False}
    )
    await proactive(family, erin)
    model.observe_inbound(erin, at(21, 10, 2))
    assert family.db.scalar("SELECT COUNT(*) FROM energy_signals") == 0


# ----- day levels ("it's a medium energy day") ----------------------------------------


def test_a_day_level_pulls_today_towards_it(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 10))
    erin = family.erin
    before = model.capacity(erin)
    assert model.record(erin, "day_level", -1, "said it's a low energy day")
    low = model.capacity(erin)
    assert low < before and abs(low - DAY_LEVEL_TARGETS[-1]) < abs(before - DAY_LEVEL_TARGETS[-1])
    assert model.record(erin, "day_level", 1, "now a high energy day")  # the latest one counts
    assert model.capacity(erin) > before
    clock.freeze(at(22, 10))  # the next day it's gone
    assert model.capacity(erin) == pytest.approx(model.baseline(erin), abs=1)


def test_a_day_level_isnt_an_extra_drain(model: EnergyModel, family: SeededFamily) -> None:
    clock.freeze(at(21, 10))
    model.record(family.erin, "day_level", 0, "medium energy day")
    assert DAY_LEVEL_TARGETS[0] - 15 < model.capacity(family.erin) < DAY_LEVEL_TARGETS[0] + 15


def test_day_levels_follow_the_energy_notes_switch(
    model: EnergyModel, family: SeededFamily
) -> None:
    from themi.accounts import SYSTEM

    erin = family.store.update_settings(SYSTEM, family.erin.id, tracking={"text_notes": False})
    assert not model.record(erin, "day_level", -1, "low energy day")
