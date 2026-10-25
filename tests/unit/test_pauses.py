from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.channels.pauses import PauseBook, PauseError, normalise_topic, parse_until

TZ = "America/Los_Angeles"
PACIFIC = ZoneInfo(TZ)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("", at(22, 0)),
        ("today", at(22, 0)),
        ("for today", at(22, 0)),
        ("tonight", at(22, 8)),  # Erin's quiet hours end at 08:00
        ("tomorrow", at(23, 0)),
        ("3 hours", at(21, 13)),
        ("3h", at(21, 13)),
        ("an hour", at(21, 11)),
        ("2 days", at(23, 10)),
        ("a week", at(28, 10)),
        ("45 minutes", at(21, 10, 45)),
    ],
)
def test_durations(family: SeededFamily, phrase: str, expected: datetime) -> None:
    assert parse_until(phrase, family.erin, TZ, at(21, 10)) == expected


@pytest.mark.parametrize("phrase", ["for a while", "forever", "0 hours", "40 days"])
def test_unclear_or_too_long_durations_are_refused(family: SeededFamily, phrase: str) -> None:
    with pytest.raises(PauseError):
        parse_until(phrase, family.erin, TZ, at(21, 10))


def test_topics_and_aliases() -> None:
    assert normalise_topic("Meals") == "meals"
    assert normalise_topic("dinner") == "meals"
    assert normalise_topic("all") == "everything"
    with pytest.raises(PauseError, match="Topics:"):
        normalise_topic("weather")


def test_pauses_cover_their_kinds_and_expire(family: SeededFamily) -> None:
    clock.freeze(at(21, 10))
    book = PauseBook(family.db)
    book.pause(family.erin, "meals", at(22, 0))
    assert book.held_until(family.erin, "meal") == at(22, 0)
    assert book.held_until(family.erin, "laundry") is None
    assert book.held_until(family.husband, "meal") is None  # pauses are per member
    clock.freeze(at(22, 0))
    assert book.held_until(family.erin, "meal") is None
    assert book.active(family.erin) == []


def test_everything_covers_every_kind_and_resume_ends_it(family: SeededFamily) -> None:
    clock.freeze(at(21, 10))
    book = PauseBook(family.db)
    book.pause(family.erin, "everything", at(21, 18))
    book.pause(family.erin, "laundry", at(21, 20))
    assert book.held_until(family.erin, "laundry") == at(21, 20)  # the longer one wins
    assert book.held_until(family.erin, "approval") == at(21, 18)
    assert book.resume(family.erin, "laundry") == 1
    assert book.held_until(family.erin, "laundry") == at(21, 18)
    assert book.resume(family.erin) == 1
    assert book.held_until(family.erin, "approval") is None
    assert book.resume(family.erin) == 0


async def test_the_outbox_holds_paused_kinds_but_not_replies_or_urgent(
    family: SeededFamily,
) -> None:
    from tests.unit.test_outbox import FakeSender
    from themi.channels.outbox import Outbox, Priority
    from themi.channels.pda import PdaShield

    clock.freeze(at(21, 10))
    sender = FakeSender()
    outbox = Outbox(family.store, sender, PdaShield(None))
    outbox.pauses.pause(family.erin, "meals", at(21, 15))
    held = await outbox.send(family.erin, "Lunch idea?", priority=Priority.NORMAL, kind="meal")
    assert held.status == "queued" and held.send_after == at(21, 15)
    other = await outbox.send(
        family.erin, "Washer's done.", priority=Priority.NORMAL, kind="laundry"
    )
    reply = await outbox.send(family.erin, "Okay!", priority=Priority.REPLY, kind="meal")
    urgent = await outbox.send(family.erin, "Leak!", priority=Priority.URGENT, kind="meal")
    assert (other.status, reply.status, urgent.status) == ("sent", "sent", "sent")
    clock.advance(timedelta(hours=5))
    assert await outbox.flush() == 1
    assert sender.texts()[-1] == "Lunch idea?"


async def test_a_pause_outranks_a_deadline(family: SeededFamily) -> None:
    from tests.unit.test_outbox import FakeSender
    from themi.channels.outbox import Outbox, Priority
    from themi.channels.pda import PdaShield

    clock.freeze(at(21, 10))
    outbox = Outbox(family.store, FakeSender(), PdaShield(None))
    outbox.pauses.pause(family.erin, "notes", at(21, 16))
    result = await outbox.send(
        family.erin,
        "From him: vet called",
        priority=Priority.NORMAL,
        kind="relay",
        deadline=at(21, 12),
    )
    assert result.send_after == at(21, 16)
