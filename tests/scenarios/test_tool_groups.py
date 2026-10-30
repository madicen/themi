"""P1 (from bug #29): each message sends only the tools it needs; `more_tools` adds a group
when the model finds it needs one."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.core.timing import Reply, router_numbers, week_of_replies
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


async def test_the_evals_messages_bring_the_tools_they_need(scenario: Scenario) -> None:
    # The 2026-10-29 evals: without update_pantry or set_task_schedule, the model reached
    # for the grocery list and for a rule.
    for said, needed in [
        ("Used the last of the olive oil.", "update_pantry"),
        ("Just picked up eggs and coffee", "update_pantry"),
        ("The spinach needs using up by Friday", "update_pantry"),
        ("Always remind me about the bins on Tuesday evenings", "set_task_schedule"),
    ]:
        scenario.primary.queue_text("Okay.")
        await scenario.say("Erin", said)
        assert needed in sent(scenario), said


# ----- P3: how well the groups were chosen -------------------------------------------


async def test_each_reply_records_the_groups_it_sent(scenario: Scenario) -> None:
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "Make a packing list for the trip")
    scenario.primary.queue_tool_call("more_tools", {"groups": ["pantry"]})
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", "Hmm, what should we do about that")
    hit, missed = week_of_replies(scenario.app.db)
    assert hit.groups == ("lists",) and hit.groups_added == () and not hit.asked_for_more
    assert hit.tools_sent == len(sent(scenario, 0))
    # The last messages still call for lists; the model asked for the pantry's.
    assert missed.groups == ("lists",) and missed.groups_added == ("pantry",)
    assert missed.asked_for_more and missed.tools_sent == len(sent(scenario, 1))
    numbers = router_numbers([hit, missed])
    assert numbers is not None
    assert (numbers.count, numbers.missed, numbers.added_late) == (2, 1, [("pantry", 1)])


async def test_a_reply_with_only_the_core_records_no_groups(scenario: Scenario) -> None:
    scenario.primary.queue_text("Hi!")
    await scenario.say("Erin", "Hello")
    (reply,) = week_of_replies(scenario.app.db)
    assert reply.groups == () and reply.tools_sent == len(sent(scenario))


def test_replies_from_before_p3_are_left_out_of_the_numbers() -> None:
    old = Reply(1, 1, "2026-10-28T09:00:00Z", 4.0, 3.0, 0.0, 1.0, None, ())
    assert router_numbers([old]) is None
