"""Outbox timing rules, with Erin's quiet hours 21:30-08:00 Pacific and a frozen clock."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import SYSTEM, Member
from themi.channels.events import Button
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield

PACIFIC = ZoneInfo("America/Los_Angeles")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in October 2026, given in Pacific time."""
    return datetime(2026, 10, day, hour, minute, tzinfo=PACIFIC)


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, tuple[Button, ...], str]] = []
        self.failures = 0
        self.edited: list[tuple[int, str, tuple[Button, ...]]] = []
        self.previews: list[bool] = []
        self._ids = iter(range(500, 10_000))

    async def send_text(
        self,
        member: Member,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        kind: str = "chat",
        link_preview: bool = True,
    ) -> int:
        self.previews.append(link_preview)
        if self.failures:
            self.failures -= 1
            raise ConnectionError("telegram unreachable")
        self.sent.append((member.name, text, tuple(buttons), kind))
        return next(self._ids)

    def texts(self) -> list[str]:
        return [text for _, text, _, _ in self.sent]

    async def edit_text(
        self, member: Member, message_id: int, text: str, buttons: Sequence[Button] = ()
    ) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("telegram unreachable")
        self.edited.append((message_id, text, tuple(buttons)))


class LaterBy:
    """A receptivity provider that always wants to wait `delay`."""

    def __init__(self, delay: timedelta) -> None:
        self.delay = delay

    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        return now + self.delay


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def outbox(family: SeededFamily, sender: FakeSender) -> Outbox:
    return Outbox(family.store, sender, PdaShield(None))


async def test_replies_go_now_and_dont_count(family: SeededFamily, outbox: Outbox, sender) -> None:
    clock.freeze(at(21, 23))  # quiet hours
    result = await outbox.send(family.erin, "Noted.", priority=Priority.REPLY)
    assert result.status == "sent" and result.message_id == 500
    assert sender.texts() == ["Noted."]
    assert outbox.sent_today(family.erin.id) == 0


async def test_normal_messages_go_now_outside_quiet_hours(
    family: SeededFamily, outbox: Outbox, sender
) -> None:
    clock.freeze(at(21, 9))
    result = await outbox.send(family.erin, "The washer finished.", priority=Priority.NORMAL)
    assert result.status == "sent"
    assert outbox.sent_today(family.erin.id) == 1


async def test_quiet_hours_hold_messages_until_morning(
    family: SeededFamily, outbox: Outbox, sender
) -> None:
    clock.freeze(at(21, 22))
    result = await outbox.send(family.erin, "The feeders are low.", priority=Priority.NORMAL)
    assert result.status == "queued"
    assert result.send_after == at(22, 8)
    clock.freeze(at(22, 7, 59))
    assert await outbox.flush() == 0
    clock.freeze(at(22, 8))
    assert await outbox.flush() == 1
    assert sender.texts() == ["The feeders are low."]


async def test_urgent_messages_ignore_quiet_hours(
    family: SeededFamily, outbox: Outbox, sender
) -> None:
    clock.freeze(at(21, 23, 30))
    result = await outbox.send(family.erin, "The tenant reports a leak.", priority=Priority.URGENT)
    assert result.status == "sent"


async def test_quiet_hours_are_per_member(family: SeededFamily, outbox: Outbox, sender) -> None:
    clock.freeze(at(21, 22, 30))  # Erin is quiet from 21:30, her husband from 23:00
    assert (await outbox.send(family.erin, "hi", priority=Priority.NORMAL)).status == "queued"
    assert (await outbox.send(family.husband, "hi", priority=Priority.NORMAL)).status == "sent"


async def test_the_daily_limit_holds_extra_messages_until_tomorrow(
    family: SeededFamily, outbox: Outbox, sender
) -> None:
    erin = family.store.update_settings(SYSTEM, family.erin.id, daily_limit=2)
    clock.freeze(at(21, 10))
    for text in ("one", "two"):
        assert (await outbox.send(erin, text, priority=Priority.NORMAL)).status == "sent"
    third = await outbox.send(erin, "three", priority=Priority.LOW)
    assert third.status == "queued" and third.send_after == at(22, 8)
    assert (await outbox.send(erin, "urgent one", priority=Priority.URGENT)).status == "sent"
    clock.freeze(at(21, 18))
    assert await outbox.flush() == 0
    clock.freeze(at(22, 8, 5))
    assert await outbox.flush() == 1
    assert sender.texts() == ["one", "two", "urgent one", "three"]


async def test_the_daily_count_resets_at_local_midnight(
    family: SeededFamily, outbox: Outbox
) -> None:
    clock.freeze(at(21, 20))
    await outbox.send(family.husband, "evening note", priority=Priority.NORMAL)
    assert outbox.sent_today(family.husband.id) == 1
    clock.freeze(at(22, 0, 1))
    assert outbox.sent_today(family.husband.id) == 0


async def test_receptivity_can_ask_to_wait(family: SeededFamily, sender: FakeSender) -> None:
    outbox = Outbox(family.store, sender, PdaShield(None), LaterBy(timedelta(hours=2)))
    clock.freeze(at(21, 10))
    result = await outbox.send(family.erin, "maintenance idea", priority=Priority.LOW)
    assert result.status == "queued" and result.send_after == at(21, 12)


async def test_receptivity_never_lands_inside_quiet_hours(
    family: SeededFamily, sender: FakeSender
) -> None:
    outbox = Outbox(family.store, sender, PdaShield(None), LaterBy(timedelta(hours=2)))
    clock.freeze(at(21, 20, 30))
    result = await outbox.send(family.erin, "idea", priority=Priority.NORMAL)
    assert result.send_after == at(22, 8)  # 22:30 would be quiet, so 08:00


async def test_a_deadline_overrides_receptivity_and_the_limit_but_not_quiet_hours(
    family: SeededFamily, sender: FakeSender
) -> None:
    outbox = Outbox(family.store, sender, PdaShield(None), LaterBy(timedelta(hours=6)))
    erin = family.store.update_settings(SYSTEM, family.erin.id, daily_limit=0)
    clock.freeze(at(21, 12))
    result = await outbox.send(
        erin, "relay from him", priority=Priority.NORMAL, deadline=at(21, 17)
    )
    assert result.send_after == at(21, 17)
    clock.freeze(at(21, 17))
    assert await outbox.flush() == 1

    clock.freeze(at(21, 21))
    late = await outbox.send(erin, "late relay", priority=Priority.NORMAL, deadline=at(21, 22))
    clock.freeze(at(21, 22))
    assert await outbox.flush() == 0  # deadline passed, but it's quiet hours now
    assert outbox.queued(erin.id)[0]["id"] == late.outbox_id


async def test_dedupe_keys_suppress_repeats(family: SeededFamily, outbox: Outbox, sender) -> None:
    clock.freeze(at(21, 10))
    first = await outbox.send(
        family.erin, "Washer done", priority=Priority.NORMAL, dedupe_key="laundry:12"
    )
    again = await outbox.send(
        family.erin, "Washer done", priority=Priority.NORMAL, dedupe_key="laundry:12"
    )
    assert (first.status, again.status) == ("sent", "duplicate")
    other = await outbox.send(
        family.husband, "Washer done", priority=Priority.NORMAL, dedupe_key="laundry:12"
    )
    assert other.status == "sent"  # dedupe is per member
    clock.advance(timedelta(hours=25))
    assert (
        await outbox.send(
            family.erin, "Washer done", priority=Priority.NORMAL, dedupe_key="laundry:12"
        )
    ).status == "sent"


async def test_failed_sends_are_retried_with_backoff(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 10))
    sender.failures = 1
    result = await outbox.send(family.erin, "Thanks!", priority=Priority.NORMAL)
    assert result.status == "queued"
    assert result.send_after == at(21, 10, 1)
    assert await outbox.flush() == 0
    clock.advance(timedelta(minutes=1))
    assert await outbox.flush() == 1
    assert sender.texts() == ["Thanks!"]


async def test_a_failed_reply_is_retried_within_minutes(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    """Someone is waiting on a reply: an hour's backoff left one 90 minutes late."""
    clock.freeze(at(21, 10))
    sender.failures = 4
    result = await outbox.send(family.erin, "Added it.", priority=Priority.REPLY)
    for _ in range(10):
        clock.advance(timedelta(minutes=1))
        await outbox.flush()
    assert sender.texts() == ["Added it."]
    row = family.db.one("SELECT sent_at FROM outbox WHERE id = ?", (result.outbox_id,))
    assert row is not None and datetime.fromisoformat(row["sent_at"]) <= at(21, 10) + timedelta(
        minutes=5
    )


async def test_a_reply_keeps_trying_through_a_longer_outage(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 10))
    sender.failures = 6
    await outbox.send(family.erin, "Added it.", priority=Priority.REPLY)
    for _ in range(12):
        clock.advance(timedelta(minutes=15))
        await outbox.flush()
    assert sender.texts() == ["Added it."]


async def test_a_message_being_sent_isnt_sent_again_by_a_flush(
    family: SeededFamily, sender: FakeSender
) -> None:
    """Idea #8's "saved" reply went out twice: the scheduler's flush ran while the
    reply was still on its way and sent the same row again."""

    class SlowShield(PdaShield):
        def __init__(self) -> None:
            super().__init__(None)
            self.gate = asyncio.Event()

        async def apply(self, text, member, **kwargs):  # type: ignore[no-untyped-def]
            await self.gate.wait()
            return await super().apply(text, member, **kwargs)

    shield = SlowShield()
    outbox = Outbox(family.store, sender, shield)
    clock.freeze(at(21, 10))
    sending = asyncio.create_task(outbox.send(family.erin, "Saved.", priority=Priority.REPLY))
    await asyncio.sleep(0)  # the reply is now waiting on the shield
    flushing = asyncio.create_task(outbox.flush())
    await asyncio.sleep(0)
    shield.gate.set()
    await sending
    assert await flushing == 0
    assert sender.texts() == ["Saved."]


async def test_sending_gives_up_after_five_attempts(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 10))
    sender.failures = 10
    result = await outbox.send(family.erin, "hello", priority=Priority.NORMAL)
    for _ in range(4):
        clock.advance(timedelta(hours=2))
        await outbox.flush()
    row = family.db.one(
        "SELECT status, attempts, last_error FROM outbox WHERE id = ?", (result.outbox_id,)
    )
    assert row == {"status": "failed", "attempts": 5, "last_error": "ConnectionError"}


async def test_shielding_happens_at_send_time(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 22))
    queued = await outbox.send(
        family.erin,
        "Move the laundry to the dryer.",
        priority=Priority.NORMAL,
        buttons=[Button("Done", "laundry", {"cycle": 3})],
        kind="laundry",
    )
    clock.freeze(at(22, 8))
    await outbox.flush()
    ((_name, text, buttons, kind),) = sender.sent
    assert text == "Up next: move the laundry to the dryer."
    assert buttons == (Button("Done", "laundry", {"cycle": 3}),) and kind == "laundry"
    row = family.db.one("SELECT text, sent_text FROM outbox WHERE id = ?", (queued.outbox_id,))
    assert row == {"text": "Move the laundry to the dryer.", "sent_text": text}


async def test_flush_sends_higher_priorities_first(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 23))
    await outbox.send(family.erin, "low one", priority=Priority.LOW)
    await outbox.send(family.erin, "normal one", priority=Priority.NORMAL)
    clock.freeze(at(22, 8))
    await outbox.flush()
    assert sender.texts() == ["normal one", "low one"]


def test_stored_times_are_utc(family: SeededFamily, outbox: Outbox) -> None:
    clock.freeze(at(21, 22))
    import asyncio

    asyncio.run(outbox.send(family.erin, "x", priority=Priority.NORMAL))
    row = family.db.one("SELECT send_after, created_at FROM outbox")
    assert row is not None
    assert datetime.fromisoformat(row["send_after"]).utcoffset() == timedelta(0)
    assert datetime.fromisoformat(row["send_after"]) == at(22, 8).astimezone(UTC)


async def test_edits_are_shielded_and_failures_are_harmless(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 10))
    assert await outbox.edit(family.erin, 501, "Don't forget the vet.")
    assert sender.edited == [(501, "In case it's handy, there's the vet.", ())]
    sender.failures = 1
    assert not await outbox.edit(family.erin, 501, "anything")


async def test_cancel_withdraws_only_unsent_messages(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 23))
    queued = await outbox.send(family.erin, "later", priority=Priority.NORMAL)
    assert queued.outbox_id is not None and outbox.message_id(queued.outbox_id) is None
    assert outbox.cancel(queued.outbox_id)
    clock.freeze(at(22, 9))
    assert await outbox.flush() == 0
    sent = await outbox.send(family.erin, "now", priority=Priority.NORMAL)
    assert sent.outbox_id is not None
    assert not outbox.cancel(sent.outbox_id)
    assert outbox.message_id(sent.outbox_id) == sent.message_id


async def test_busy_times_hold_messages_until_they_end(
    family: SeededFamily, outbox: Outbox, sender
) -> None:
    from datetime import time

    from themi.accounts import SYSTEM, BusyTime

    erin = family.store.update_settings(
        SYSTEM, family.erin.id, busy_times=[BusyTime((0, 1, 2, 3, 4), time(9), time(17))]
    )
    clock.freeze(at(21, 10))  # Wednesday morning, at work
    held = await outbox.send(erin, "The washer finished.", priority=Priority.NORMAL)
    assert (held.status, held.send_after) == ("queued", at(21, 17))
    assert (await outbox.send(erin, "Sure, done.", priority=Priority.REPLY)).status == "sent"
    assert (await outbox.send(erin, "Leak!", priority=Priority.URGENT)).status == "sent"
    clock.freeze(at(21, 17))
    assert await outbox.flush() == 1
    assert sender.texts()[-1] == "The washer finished."


async def test_not_before_holds_a_message_until_then(
    family: SeededFamily, outbox: Outbox, sender
) -> None:
    from datetime import timedelta

    clock.freeze(at(21, 10))
    later = at(21, 14)
    held = await outbox.send(
        family.erin, "On the list for you.", priority=Priority.NORMAL, not_before=later
    )
    assert (held.status, held.send_after) == ("queued", later)
    reply = await outbox.send(family.erin, "Sure.", priority=Priority.REPLY, not_before=later)
    assert reply.status == "sent"  # replies never wait
    clock.advance(timedelta(hours=4))
    assert await outbox.flush() == 1
