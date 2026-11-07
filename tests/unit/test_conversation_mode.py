"""CM1a: which messages get conversation mode's chat reply, and what that reply may say."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from themi.accounts import Member
from themi.accounts.models import Role
from themi.core.conversation_mode import CHAT_SYSTEM, build_chat_turn, honest, is_request

ERIN = Member(
    id=1, name="Erin", role=Role.ADMIN, telegram_user_id=1, quiet_start=time(22),
    quiet_end=time(7), daily_limit=3, pda_enabled=True, pda_strength=0, recovery_hours=1.0,
    tracking={}, created_at=datetime(2026, 11, 2, tzinfo=UTC),
)  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        "add milk to the list",
        "Add oat milk",
        "please remind me tomorrow at 9 to call the vet",
        "remind me to text Sam",
        "can you put bin day on the calendar",
        "Could you move the dentist to Friday?",
        "Themi, cancel the plumber",
        "ok so mark the laundry done",
        "done with the dishes",
        "we're out of coffee",
        "I need to buy batteries",
        "don't let me forget the permission slip",
        "what's on my list?",
        "how's the laundry doing?",
        "is the dishwasher done",
        "what do I have tomorrow",
        "what's for dinner?",
        "Groceries. eggs",
        "Hardware: wood glue",
    ],
)
def test_requests_go_to_the_tool_agent(text: str) -> None:
    assert is_request(text, ["Hardware"])


@pytest.mark.parametrize(
    "text",
    [
        "long day, the kids were a lot",
        "ugh, I need to call the vet Thursday",
        "I should really clean the garage someday",
        "I'm so tired",
        "thanks, that helped",
        "do you ever think about how weird birds are?",
        "Sam's recital was lovely",
        "the meeting ran over again and I'm fried",
        "what a week",
    ],
)
def test_everything_else_is_chat(text: str) -> None:
    assert not is_request(text, ["Hardware"])


def test_a_claim_that_something_was_done_is_dropped() -> None:
    assert honest("I've added that to your list. Sounds like a long day.") == (
        "Sounds like a long day."
    )
    assert honest("Done! It's on the list.") != "Done! It's on the list."
    assert honest("I've added it.") == "Got it."
    assert honest("That sounds hard.") == "That sounds hard."


def test_the_chat_turn_has_no_energy_and_no_tools() -> None:
    member = ERIN
    turn = build_chat_turn(
        member,
        "long day",
        local_now=datetime(2026, 11, 5, 18, 30, tzinfo=UTC),
        timezone="America/Los_Angeles",
        modes=["burnout mode: nothing to do"],
        open_items=["Waiting on you: Archive 3 emails"],
    )
    assert "seems" not in turn and "energy" not in turn.lower()
    assert "Thursday 5 November 2026, 6:30 PM" in turn
    assert "Modes they're in: burnout mode" in turn
    assert "- Waiting on you: Archive 3 emails" in turn
    assert turn.endswith(f"{member.name} says:\nlong day")
    assert "tool" not in CHAT_SYSTEM.lower() and "json" in CHAT_SYSTEM.lower()  # told: no JSON


def test_chat_says_when_it_doesnt_know() -> None:
    """F30b (#160): "The Redwood City dentist is Dr. Evans, 650-555-0144" was made up."""
    from themi.core.conversation_mode import CHAT_SYSTEM

    assert "Never make up names, phone numbers, addresses" in CHAT_SYSTEM
    assert "say so" in CHAT_SYSTEM and "places they could look" in CHAT_SYSTEM


# F34a, bugs #178 and #179 (2026-11-06): these went to the tool-less chat, and nothing was
# done. A word about an open task with a change in it, body doubling, a question about what
# Themi can see, and an email rule all need the tools.
ERIN_OPEN = ["Go for a run", "Clean the bird cage", "Put the laundry away", "Walk dog"]


@pytest.mark.parametrize(
    "text",
    [
        "No run today. I plan to run 1.3 miles either tomorrow or Sunday",
        "Can we body double the bird cage?",
        "sit with me while I do the taxes",
        "let's do the dishes together",
        "Can you see the screenshot I sent?",
        "are you able to read pdfs",
        "I found the email. Future emails like that are mostly noise",
        "from now on mail from the HOA is important",
        "I'll do the laundry Sunday instead",
        "skipping the bird cage tonight",
    ],
)
def test_an_open_task_body_doubling_or_a_rule_goes_to_the_tools(text: str) -> None:
    assert is_request(text, ["Hardware"], ERIN_OPEN)


@pytest.mark.parametrize(
    "text",
    [
        "the run was lovely",
        "long day, the kids were a lot",
        "I should really clean the garage someday",
        "do you ever think about how weird birds are?",
        "Idk what to watch",
    ],
)
def test_a_remark_about_a_task_is_still_chat(text: str) -> None:
    assert not is_request(text, ["Hardware"], ERIN_OPEN)
