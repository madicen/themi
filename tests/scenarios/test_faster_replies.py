"""P2b: faster replies, from a week of P2a's timings (2026-10-28 to 11-03).

A list add done as asked has its own reply (F21a), so the model's next round was made
and then thrown away: 2.5 s on about one reply in four. It isn't made now. And a model
call still out after a few seconds is sent again (the router's hedge)."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from tests.scenarios.test_lists import gift_list, items, packing_list
from tests.scenarios.test_routines import add, routines
from themi.ai.router import HEDGE_AFTER
from themi.core import keys
from themi.standard.lists import ADD_CATEGORY
from themi.standard.timing import SLOW_AFTER, week_of_replies


def chats(scenario: Scenario) -> int:
    return sum(1 for r in scenario.primary.requests if r.op == "chat")


async def test_an_add_done_as_asked_ends_the_turn(scenario: Scenario) -> None:
    await gift_list(scenario)
    before = chats(scenario)
    scenario.primary.queue_tool_call("add_to_list", {"list": "gift ideas", "items": ["A scarf"]})
    replies = await scenario.say("Erin", "Gift list. A scarf")
    assert replies == ['Added "A scarf" to Gift ideas.']
    assert chats(scenario) - before == 1
    assert items(scenario, "Erin", "gift ideas") == [("A scarf", False)]


async def test_an_add_and_another_tool_still_gets_the_next_round(scenario: Scenario) -> None:
    await packing_list(scenario)
    scenario.primary.queue_tool_calls(
        [
            ("add_to_list", {"list": "packing", "items": ["sunscreen"]}, None),
            ("list_open_items", {}, None),
        ]
    )
    scenario.primary.queue_text("Sunscreen's on. Nothing else is open.")
    replies = await scenario.say("Erin", "Add sunscreen to the packing list, and what's open?")
    assert replies == ["Sunscreen's on. Nothing else is open."]
    assert scenario.primary.pending() == 0


async def test_an_add_the_model_inferred_still_gets_the_next_round(scenario: Scenario) -> None:
    # Reply 204 (2026-11-02): an automatic add the model took the message for, then a task in
    # its next round, which was what they meant. That round must still come.
    await packing_list(scenario)
    erin = scenario.member("Erin")
    scenario.app.services.autonomy.grant_tier2(ADD_CATEGORY, via_rule_id=1, by=erin)
    scenario.primary.queue_tool_call("add_to_list", {"list": "packing", "items": ["Clean towels"]})
    scenario.primary.queue_tool_call(
        "create_task", {"title": "Wash the beach towels", "assign_to": "me"}
    )
    scenario.primary.queue_text("I'll keep it on your list.")
    await scenario.say("Erin", "Someone needs to wash the beach towels")
    assert ("Clean towels", False) in items(scenario, "Erin", "packing")  # not her words
    assert scenario.primary.pending() == 0  # the task round ran


async def test_a_failed_add_still_goes_back_to_the_model(scenario: Scenario) -> None:
    # It may try again with the item shortened; F21a's plain "too long" reply stays.
    await packing_list(scenario)
    nl = scenario.app.services.maybe(keys.lists).find(scenario.member("Erin"), "packing")  # type: ignore[union-attr]
    scenario.app.db.execute("UPDATE lists SET cozyla_list_id = 'wall-1' WHERE id = ?", (nl.id,))
    long = "the big blue cooler with the broken handle, " * 3
    scenario.primary.queue_tool_call("add_to_list", {"list": "packing", "items": [long]})
    scenario.primary.queue_text("Too long, sorry.")
    replies = await scenario.say("Erin", f"Add {long} to the packing list")
    assert replies[0].startswith("That one's over 100 characters")
    assert scenario.primary.pending() == 0  # the model got its next round


async def test_a_stuck_call_is_sent_again_before_a_word_is_needed(scenario: Scenario) -> None:
    # One call in seven took over 8 s that week; a second try is usually quick.
    scenario.app.router.hedge_after = HEDGE_AFTER
    scenario.primary.take(SLOW_AFTER + 20).queue_text("The vet is on Tuesday.")
    replies = await scenario.say("Erin", "When's the vet?")
    assert replies == ["The vet is on Tuesday."]  # no "still coming" first
    (reply,) = week_of_replies(scenario.app.db)
    assert reply.seconds < SLOW_AFTER
    assert "sent again, the second answered" in reply.steps[0].detail


# F33a (reply 237, 2026-11-04): a direct change made as asked has its own line, so the
# model's next round, which only said "Removed.", isn't made.


async def test_a_routine_item_removed_as_asked_ends_the_turn(scenario: Scenario) -> None:
    add(scenario, "Erin", "Evening", "Refill cat feeders")
    before = chats(scenario)
    scenario.primary.queue_tool_call(
        "remove_routine_item", {"title": "Refill cat feeders", "routine": "Evening"}
    )
    replies = await scenario.say("Erin", "Remove the refill cat feeders from my evening routine")
    assert replies == ['Removed "Refill cat feeders" from your Evening routine.']
    assert chats(scenario) - before == 1
    evening = routines(scenario).find(scenario.member("Erin"), "Evening")
    assert evening is not None and routines(scenario).items(evening) == []


async def test_a_removal_not_in_their_words_still_gets_the_next_round(scenario: Scenario) -> None:
    add(scenario, "Erin", "Evening", "Refill cat feeders")
    scenario.primary.queue_tool_call(
        "remove_routine_item", {"title": "Refill cat feeders", "routine": "Evening"}
    )
    scenario.primary.queue_text("Removed Refill cat feeders.")
    replies = await scenario.say("Erin", "Take the kitty food thing off tonight's list")
    assert replies == ["Removed Refill cat feeders."]
    assert scenario.primary.pending() == 0


async def test_a_removal_and_a_failed_call_still_get_the_next_round(scenario: Scenario) -> None:
    add(scenario, "Erin", "Evening", "Refill cat feeders")
    scenario.primary.queue_tool_calls(
        [
            ("remove_routine_item", {"title": "Refill cat feeders", "routine": "Evening"}, None),
            ("remove_routine_item", {"title": "Walk the dog", "routine": "Evening"}, None),
        ]
    )
    scenario.primary.queue_text("Cat feeders are off. There's no dog walk on it.")
    replies = await scenario.say(
        "Erin", "Remove refill cat feeders and walk the dog from my evening routine"
    )
    assert replies == ["Cat feeders are off. There's no dog walk on it."]
    assert scenario.primary.pending() == 0


async def test_a_tick_in_their_words_ends_the_turn(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    before = chats(scenario)
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "vitamins"})
    replies = await scenario.say("Erin", "took my vitamins")
    assert replies == ['Ticked "Vitamins" for today.']
    assert chats(scenario) - before == 1
