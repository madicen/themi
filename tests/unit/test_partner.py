"""Who a message is about: the speaker or their partner (bug #126)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time

import pytest

from themi.accounts import Member
from themi.accounts.models import Role
from themi.core.partner import about_partner, about_partner_at, named

BASE = Member(
    id=1, name="Michael", role=Role.ADMIN, telegram_user_id=1, quiet_start=time(22),
    quiet_end=time(7), daily_limit=3, pda_enabled=True, pda_strength=0, recovery_hours=1.0,
    tracking={}, created_at=datetime(2026, 11, 2, tzinfo=UTC),
)  # fmt: skip
MICHAEL = BASE
ERIN = replace(BASE, id=2, name="Erin")
GRAN = replace(BASE, id=3, name="Gran")


@pytest.mark.parametrize(
    ("said", "who"),
    [
        ("What's on her plate?", ERIN),
        ("Not for me, for Erin", ERIN),
        ("What does my wife have today?", ERIN),
        ("What's on my plate?", None),
    ],
)
def test_named_with_one_other(said: str, who: Member | None) -> None:
    assert named(said, MICHAEL, [MICHAEL, ERIN]) == who


def test_a_pronoun_names_nobody_when_there_are_two_others() -> None:
    family = [MICHAEL, ERIN, GRAN]
    assert named("What's on her plate?", MICHAEL, family) is None
    assert named("What's on Gran's plate?", MICHAEL, family) == GRAN


def test_the_nearest_subject_decides() -> None:
    said = "I'm worried. She\u2019s overwhelmed"
    assert about_partner_at(said, said.index("overwhelmed"), MICHAEL, [MICHAEL, ERIN])
    said = "She's out, so I'm overwhelmed"
    assert not about_partner_at(said, said.index("overwhelmed"), MICHAEL, [MICHAEL, ERIN])


def test_the_whole_message_about_the_partner() -> None:
    assert about_partner("Erin is at zero energy", MICHAEL, [MICHAEL, ERIN])
    assert not about_partner("Erin wore me out", MICHAEL, [MICHAEL, ERIN])
    assert not about_partner("Erin is at zero energy", MICHAEL, [MICHAEL])  # nobody to name
