"""34a: relays' timing, what counts as asking to pass something on, and the note's wording."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from themi.accounts import Member
from themi.accounts.models import Role
from themi.channels.outbox import Priority
from themi_home.liaison import ASKS_TO_PASS_ON, delivery_text, timing

PACIFIC = ZoneInfo("America/Los_Angeles")
TZ = "America/Los_Angeles"


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 21, hour, minute, tzinfo=PACIFIC)


def test_an_urgent_note_goes_now() -> None:
    assert timing("urgent", at(9), TZ) == (Priority.URGENT, None)


def test_a_note_for_today_goes_by_early_evening() -> None:
    priority, deadline = timing("today", at(9), TZ)
    assert priority is Priority.NORMAL
    assert deadline == at(18)


def test_a_note_for_today_asked_for_after_early_evening_is_already_due() -> None:
    assert timing("today", at(20, 15), TZ) == (Priority.NORMAL, at(20, 15))


def test_a_note_for_whenever_waits_for_a_good_window() -> None:
    assert timing("whenever", at(9), TZ) == (Priority.NORMAL, None)


@pytest.mark.parametrize(
    "said",
    [
        "Tell my husband I'll be home late tonight",
        "Let Erin know the dog's been fed",
        "Can you pass on to him that the car needs gas?",
        "pass it on to Erin please: the vet called",
        "Ask Erin if she wants takeout tonight",
        "Can you tell Hundo “I Wuv U ❤️”?",
        "message him that I'm on my way",
        "send her a note saying the plumber is coming",
    ],
)
def test_asking_to_pass_something_on(said: str) -> None:
    assert ASKS_TO_PASS_ON.search(said.replace("\u2019", "'"))


@pytest.mark.parametrize(
    "said",
    [
        "Ask him to take the bins out",  # a job for him: a task
        "Can you have Michael get the pacifier?",
        "Tell me what's on today",
        "Let me know when the washer's done",
        "The vet called",
        "Remind me to call the vet",
        "Send the email to the landlord",
    ],
)
def test_not_asking_to_pass_anything_on(said: str) -> None:
    assert not ASKS_TO_PASS_ON.search(said)


def _member(name: str) -> Member:
    return Member(
        id=1,
        name=name,
        role=Role.MEMBER,
        telegram_user_id=None,
        quiet_start=time(22),
        quiet_end=time(7),
        daily_limit=6,
        pda_enabled=True,
        pda_strength=1,
        recovery_hours=4,
        tracking={},
        created_at=at(9),
    )


def test_the_note_says_who_its_from() -> None:
    husband = _member("Husband")
    assert delivery_text(husband, "I'll be home late tonight.", "today") == (
        "From Husband: I'll be home late tonight."
    )
    assert delivery_text(husband, "The basement is flooding.", "urgent") == (
        "Urgent, from Husband: The basement is flooding."
    )
