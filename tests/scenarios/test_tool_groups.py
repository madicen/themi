"""P1 (from bug #29): each message sends only the tools it needs; `more_tools` adds a group
when the model finds it needs one."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.core.tools import GROUPS, TOOL_GROUPS


def sent(scenario: Scenario, index: int = -1) -> set[str]:
    return {t.name for t in scenario.primary.requests[index].tools}


async def test_a_plain_message_gets_the_core_only(scenario: Scenario) -> None:
    scenario.primary.queue_text("Hi!")
    await scenario.say("Erin", "Good morning")
    names = sent(scenario)
    assert {"create_task", "remember_fact", "propose_rule", "more_tools"} <= names
    assert not names & {"add_calendar_event", "create_list", "update_pantry", "expect_email"}
    assert len(names) < len(scenario.app.services.tools.specs()) * 0.6


async def test_the_words_bring_their_group(scenario: Scenario) -> None:
    scenario.primary.queue_text("Sure.")
    await scenario.say("Erin", "What's on my calendar tomorrow?")
    assert "day_summary" in sent(scenario)  # (event tools exist only with Google set up)
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Make a packing list for the trip")
    assert {"create_list", "add_to_list"} <= sent(scenario)
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "and add sunscreen")  # the last messages count too
    assert "add_to_list" in sent(scenario)


async def test_more_tools_brings_a_group_mid_turn(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("more_tools", {"groups": ["pantry"]})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Hmm, what should we do about that")
    assert "update_pantry" not in sent(scenario, -2)
    assert "update_pantry" in sent(scenario, -1)  # the next step has it


def test_every_group_is_known_and_has_words() -> None:
    assert set(TOOL_GROUPS.values()) <= set(GROUPS)
    assert all(words for _, words in GROUPS.values())
