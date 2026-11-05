"""34b: the family group in the outbox: questions that wait for everyone, replies that go
back to the group, and shielding for the stricter partner. Erin's quiet hours are
21:30-08:00, her husband's start at 23:00."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender, at
from themi import clock
from themi.accounts import SYSTEM, Member
from themi.channels.events import Button
from themi.channels.family_group import FamilyGroup, group_replies, shared_reader
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield

GROUP = -5001


class Windows:
    """Receptivity: each person's next good window."""

    def __init__(self, **by_name: datetime) -> None:
        self.by_name = by_name

    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        return max(now, self.by_name.get(member.name, now))


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def outbox(family: SeededFamily, sender: FakeSender) -> Outbox:
    return Outbox(family.store, sender, PdaShield(None))


def link(family: SeededFamily) -> None:
    FamilyGroup(family.db).link(GROUP, "Family", family.erin)


async def test_a_group_question_waits_for_both_good_windows(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    link(family)
    clock.freeze(at(21, 9))
    outbox.receptivity = Windows(Erin=at(21, 11), Husband=at(21, 15))
    result = await outbox.send(
        family.erin, "Feeders?", priority=Priority.NORMAL, kind="alignment", to_group=True
    )
    assert result.status == "queued" and result.send_after == at(21, 15)
    clock.freeze(at(21, 11))  # Erin's window alone isn't enough
    assert await outbox.flush() == 0
    clock.freeze(at(21, 15))
    assert await outbox.flush() == 1
    assert sender.texts() == ["Feeders?"] and sender.chats == [GROUP]


async def test_a_group_question_waits_out_either_partners_quiet_hours(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    link(family)
    clock.freeze(at(21, 22))  # Erin is quiet, her husband isn't
    result = await outbox.send(
        family.husband, "Feeders?", priority=Priority.NORMAL, kind="alignment", to_group=True
    )
    assert result.status == "queued" and result.send_after == at(22, 8)


async def test_a_window_that_lands_in_the_others_quiet_hours_moves_on(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    link(family)
    clock.freeze(at(21, 9))
    # His window is at 10 pm, inside Erin's quiet hours: the next moment for both is
    # the morning, when his window has passed too.
    outbox.receptivity = Windows(Husband=at(21, 22))
    result = await outbox.send(
        family.erin, "Feeders?", priority=Priority.NORMAL, kind="alignment", to_group=True
    )
    assert result.send_after == at(22, 8)


async def test_a_group_question_without_a_group_fails(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 9))
    result = await outbox.send(family.erin, "Feeders?", priority=Priority.NORMAL, to_group=True)
    assert result.status == "failed" and sender.sent == []


async def test_a_group_question_counts_toward_both_daily_limits(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    link(family)
    clock.freeze(at(21, 9))
    await outbox.send(family.erin, "Feeders?", priority=Priority.NORMAL, to_group=True)
    assert outbox.sent_today(family.erin.id) == 1
    assert outbox.sent_today(family.husband.id) == 1


async def test_replies_to_someone_in_the_group_go_to_the_group(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    link(family)
    clock.freeze(at(21, 9))
    token = group_replies.set(family.erin.id)
    try:
        await outbox.send(family.erin, "Done.", priority=Priority.REPLY)
        await outbox.send(family.husband, "From Erin: hi", priority=Priority.NORMAL)
        await outbox.edit(family.erin, 77, "Edited.")
    finally:
        group_replies.reset(token)
    await outbox.send(family.erin, "Later, alone.", priority=Priority.REPLY)
    # her reply went to the group; a note for him and anything after stay private
    assert sender.chats == [GROUP, None, None]
    assert sender.edited == [(77, "Edited.", ())]


async def test_a_reply_after_the_group_is_unlinked_goes_to_their_own_chat(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    clock.freeze(at(21, 9))
    token = group_replies.set(family.erin.id)
    try:
        result = await outbox.send(family.erin, "Done.", priority=Priority.REPLY)
    finally:
        group_replies.reset(token)
    assert result.status == "sent" and sender.chats == [None]


async def test_group_messages_are_shielded_for_the_stricter_partner(
    family: SeededFamily, outbox: Outbox, sender: FakeSender
) -> None:
    link(family)
    family.store.update_settings(SYSTEM, family.erin.id, pda_enabled=True, pda_strength=2)
    family.store.update_settings(SYSTEM, family.husband.id, pda_enabled=False)
    clock.freeze(at(21, 9))
    # The husband has no shielding, but Erin reads the group too.
    await outbox.send(
        family.husband,
        "Fill the feeders.",
        priority=Priority.NORMAL,
        to_group=True,
        buttons=[Button("Half", "alignment"), Button("Full", "alignment")],
    )
    await outbox.send(family.husband, "Fill the feeders.", priority=Priority.NORMAL)
    group_text, own_text = sender.texts()
    assert group_text != "Fill the feeders."  # softened
    assert own_text == "Fill the feeders."  # his own chat, his own settings


def test_the_shared_reader_takes_the_strictest_settings(family: SeededFamily) -> None:
    store = family.store
    store.update_settings(SYSTEM, family.erin.id, pda_enabled=True, pda_strength=3)
    store.update_settings(SYSTEM, family.husband.id, pda_enabled=False, pda_strength=0)
    store.update_settings(SYSTEM, family.erin.id, phrasing="gentle")
    members = store.list_members()
    husband = store.get_member(family.husband.id)
    reader = shared_reader(husband, members)
    assert reader.id == husband.id  # his backend rewrites it
    assert (reader.pda_enabled, reader.pda_strength, reader.phrasing) == (True, 3, "gentle")


def test_linking_and_a_move_to_a_supergroup(family: SeededFamily) -> None:
    groups = FamilyGroup(family.db)
    clock.freeze(at(21, 9))
    assert groups.chat_id() is None
    groups.link(GROUP, "Family", family.erin)
    assert groups.is_family(GROUP)
    assert groups.moved(GROUP, -100_5001)
    assert groups.chat_id() == -100_5001
    assert not groups.moved(GROUP, -1)  # not the family group
    assert groups.unlink() and groups.get() is None
