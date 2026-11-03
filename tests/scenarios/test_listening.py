"""F22e, Erin's ideas #124 and #125: replies sized to the message, and listening before
problem-solving."""

from __future__ import annotations

import pytest

from tests.scenarios.harness import Scenario
from tests.scenarios.test_focus import a_full_day, tool_result, turn
from themi.core.focus import SIGNAL as FOCUS_SIGNAL
from themi.core.listening import LISTEN_SIGNAL, SHORT_SIGNAL, sentences

STRESSED = (
    "I'm so stressed today. Work was a lot and the baby didn't sleep. "
    "I feel like I'm failing at everything. I just needed to say it."
)


async def test_a_short_message_gets_a_short_reply(scenario: Scenario) -> None:
    scenario.primary.queue_text("Noted.")
    await scenario.say("Erin", "Bins are out")
    assert SHORT_SIGNAL in turn(scenario)


async def test_a_few_sentences_get_about_as_many(scenario: Scenario) -> None:
    scenario.primary.queue_text("That sounds like a really hard day.")
    await scenario.say("Erin", STRESSED)
    assert "their message is 4 sentences: reply at about that length" in turn(scenario)


async def test_feelings_are_listened_to_before_anything_is_fixed(scenario: Scenario) -> None:
    await a_full_day(scenario)
    scenario.primary.queue_tool_call("focus_now", {"spread": False})
    scenario.primary.queue_text("That's a lot to carry. Want ideas, or just to vent?")
    replies = await scenario.say("Erin", STRESSED)
    assert LISTEN_SIGNAL in turn(scenario) and FOCUS_SIGNAL not in turn(scenario)
    assert "Not sent: they're sharing how they feel" in tool_result(scenario)
    assert replies == ["That's a lot to carry. Want ideas, or just to vent?"]  # no list


async def test_asking_for_help_is_problem_solving(scenario: Scenario) -> None:
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "I'm so stressed today. What should I do first?")
    assert LISTEN_SIGNAL not in turn(scenario)


async def test_one_line_of_overwhelm_still_gets_a_few_things(scenario: Scenario) -> None:
    """O1a stays: "I'm completely overwhelmed today" is a few things for now."""
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "I'm completely overwhelmed today")
    assert FOCUS_SIGNAL in turn(scenario) and LISTEN_SIGNAL not in turn(scenario)


async def test_listening_first_can_be_turned_off(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, listen_first=False)
    assert not scenario.member("Erin").listen_first
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", STRESSED)
    assert LISTEN_SIGNAL not in turn(scenario)


@pytest.mark.parametrize(
    "said",
    [
        "You're welcome! Let me know if you need anything else.",
        "You're welcome! Anything else you'd like?",
        "You're welcome! Happy to help any time.",
    ],
)
async def test_after_a_short_message_no_anything_else(scenario: Scenario, said: str) -> None:
    scenario.primary.queue_text(said)
    assert await scenario.say("Erin", "thanks") == ["You're welcome!"]


async def test_a_longer_message_keeps_its_closing_line(scenario: Scenario) -> None:
    scenario.primary.queue_text("That's a lot. Let me know if you want ideas.")
    assert await scenario.say("Erin", STRESSED) == ["That's a lot. Let me know if you want ideas."]


@pytest.mark.parametrize(
    ("text", "n"),
    [("Bins are out", 1), ("Done. Thanks!", 2), (STRESSED, 4), ("one\ntwo\nthree", 3)],
)
def test_counting_sentences(text: str, n: int) -> None:
    assert sentences(text) == n
