from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender
from themi import clock
from themi.channels.events import ButtonPress, InboundEvent, Reaction
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield
from themi.energy.model import EnergyModel, hour_of_week, prior
from themi.energy.outcomes import LEARNING_FLOOR, TARGETS, OutcomeTracker

PACIFIC = ZoneInfo("America/Los_Angeles")
TZ = "America/Los_Angeles"


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


@pytest.fixture
def tracker(family: SeededFamily) -> OutcomeTracker:
    return OutcomeTracker(family.store)


@pytest.fixture
def outbox(family: SeededFamily, tracker: OutcomeTracker) -> Outbox:
    box = Outbox(family.store, FakeSender(), PdaShield(None))
    box.sent_listeners.append(tracker.on_sent)
    return box


def text(family: SeededFamily, words: str) -> InboundEvent:
    return InboundEvent("text", family.erin, 1001, 1, clock.now(), 1, text=words)


def cell(family: SeededFamily, hour: int) -> dict | None:
    return family.db.one(
        "SELECT mean, n FROM energy_baseline WHERE member_id = ? AND hour_of_week = ?",
        (family.erin.id, hour),
    )


async def test_only_messages_themi_started_are_tracked(
    family: SeededFamily, outbox: Outbox, tracker: OutcomeTracker
) -> None:
    clock.freeze(at(21, 10))
    await outbox.send(family.erin, "Washer's done.", priority=Priority.NORMAL, kind="laundry")
    await outbox.send(family.erin, "Okay!", priority=Priority.REPLY)
    await outbox.send(family.erin, "Leak!", priority=Priority.URGENT)
    (row,) = family.db.query("SELECT kind, hour_of_week, respond_by FROM prompt_outcomes")
    assert row["kind"] == "laundry"
    assert row["hour_of_week"] == hour_of_week(at(21, 10), TZ)
    assert datetime.fromisoformat(row["respond_by"]) == at(21, 13)


async def test_a_reply_means_acted_and_teaches_that_hour(
    family: SeededFamily, outbox: Outbox, tracker: OutcomeTracker
) -> None:
    clock.freeze(at(21, 10))
    await outbox.send(family.erin, "Lunch idea?", priority=Priority.NORMAL, kind="meal")
    clock.advance(timedelta(minutes=20))
    assert tracker.observe(family.erin, text(family, "soup sounds good")) == "acted"
    hour = hour_of_week(at(21, 10), TZ)
    assert cell(family, hour) == {"mean": TARGETS["acted"], "n": 1}
    assert tracker.observe(family.erin, text(family, "thanks")) is None  # already resolved


async def test_not_now_means_snoozed(
    family: SeededFamily, outbox: Outbox, tracker: OutcomeTracker
) -> None:
    clock.freeze(at(21, 10))
    await outbox.send(family.erin, "Filter's due?", priority=Priority.NORMAL)
    assert tracker.observe(family.erin, text(family, "not now")) == "snoozed"


async def test_buttons_and_reactions_resolve_their_own_message(
    family: SeededFamily, outbox: Outbox, tracker: OutcomeTracker
) -> None:
    clock.freeze(at(21, 10))
    first = await outbox.send(family.erin, "one", priority=Priority.NORMAL, kind="approval")
    await outbox.send(family.erin, "two", priority=Priority.NORMAL, kind="approval")
    tap = InboundEvent(
        "button",
        family.erin,
        1001,
        first.message_id,
        clock.now(),
        2,
        button=ButtonPress("Not now", "approval", {"decision": "snooze"}, first.message_id),
    )
    assert tracker.observe(family.erin, tap) == "snoozed"
    outcomes = [r["outcome"] for r in tracker.history(family.erin.id)]
    assert outcomes == ["snoozed", None]  # the older message, not the latest
    second_id = family.db.scalar(
        "SELECT telegram_message_id FROM prompt_outcomes WHERE outcome IS NULL"
    )
    react = InboundEvent(
        "reaction",
        family.erin,
        1001,
        second_id,
        clock.now(),
        3,
        reaction=Reaction(("✅",), second_id),
    )
    assert tracker.observe(family.erin, react) == "acted"


async def test_silence_past_the_timeout_is_ignored(
    family: SeededFamily, outbox: Outbox, tracker: OutcomeTracker
) -> None:
    clock.freeze(at(21, 10))
    await outbox.send(family.erin, "Washer's done.", priority=Priority.NORMAL, kind="laundry")
    clock.advance(timedelta(hours=2, minutes=59))
    assert tracker.expire() == 0
    clock.advance(timedelta(minutes=1))
    assert tracker.expire() == 1
    assert tracker.observe(family.erin, text(family, "oh, done now")) is None  # too late
    hour = hour_of_week(at(21, 10), TZ)
    assert cell(family, hour) == {"mean": TARGETS["ignored"], "n": 1}


def test_learning_steps_shrink_but_never_below_the_floor(
    family: SeededFamily, tracker: OutcomeTracker
) -> None:
    hour = 50
    first = tracker.learn(family.erin.id, hour, "acted")
    assert first == TARGETS["acted"]  # step 1/1 from the prior
    second = tracker.learn(family.erin.id, hour, "ignored")
    assert second == pytest.approx(75 + 0.5 * (25 - 75))
    for _ in range(30):
        tracker.learn(family.erin.id, hour, "acted")
    before = cell(family, hour)["mean"]  # type: ignore[index]
    after = tracker.learn(family.erin.id, hour, "ignored")
    assert before - after == pytest.approx(LEARNING_FLOOR * (before - TARGETS["ignored"]))


def test_outcomes_move_the_baseline_the_right_way(
    family: SeededFamily, tracker: OutcomeTracker
) -> None:
    model = EnergyModel(family.store)
    clock.freeze(at(21, 10))
    start = model.baseline(family.erin)
    hour = hour_of_week(clock.now(), TZ)
    for _ in range(6):
        tracker.learn(family.erin.id, hour, "ignored")
    assert model.baseline(family.erin) < start < prior(hour) + 1
    assert model.baseline(family.husband) == start  # his baseline is untouched


async def test_recent_rate(family: SeededFamily, outbox: Outbox, tracker: OutcomeTracker) -> None:
    clock.freeze(at(21, 10))
    assert tracker.recent_rate(family.erin.id) is None
    for words in ("ok", "not now"):
        await outbox.send(family.erin, "nudge", priority=Priority.NORMAL)
        tracker.observe(family.erin, text(family, words))
    assert tracker.recent_rate(family.erin.id) == 0.5
