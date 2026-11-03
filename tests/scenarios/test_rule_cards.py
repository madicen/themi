"""F21b, Erin's bug #116: a rule card says what it really makes automatic, a policy can't
skip a yes, and a reply that repeats this turn's approval card isn't sent."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from tests.scenarios.test_lists import packing_list, tool_result
from themi.core.rules import PROPOSAL_TEXT

IDEA = "Automatically add items starting with 'gift list' to the gift list"


def propose(scenario: Scenario, kind: str, category: str, summary: str, text: str) -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": summary,
            "text": text,
            "kind": kind,
            "category": category,
            "rule_id": 0,
            "applies_to": "personal",
        },
    )
    scenario.primary.queue_text("Here it is.")


async def test_a_list_add_grant_card_names_everyone_and_every_list(scenario: Scenario) -> None:
    propose(scenario, "autonomy_grant", "list_add", IDEA, "Add the rest to the gift list.")
    replies = await scenario.say("Erin", "when I start with gift list, just add it")
    assert replies[0] == PROPOSAL_TEXT.format(
        summary="Automatic for everyone: Add items to any of Themi's lists, the wall's "
        f"included (the idea: {IDEA})"
    )
    (draft,) = scenario.app.rulebook.drafts(scenario.member("Erin"))
    assert draft.scope == "household"
    assert draft.text == (
        "Themi may add items to any of Themi's lists, the wall's included, without asking "
        "first, for everyone."
    )


async def test_a_personal_grant_card_names_the_category(scenario: Scenario) -> None:
    propose(scenario, "autonomy_grant", "email_archive_noise", "Archive noise emails", "x")
    replies = await scenario.say("Erin", "archive my noise emails without asking")
    assert replies[0].startswith(
        "Proposed Rule (just for you): Automatic: Archive noise emails. A YES"
    )


async def test_a_policy_that_skips_a_yes_is_refused_with_the_choices(
    scenario: Scenario,
) -> None:
    propose(
        scenario,
        "policy",
        "",
        "Gift list adds",
        "When Erin starts with 'gift list', add the rest without asking.",
    )
    replies = await scenario.say("Erin", "when I start with gift list, add it without asking")
    assert replies == ["Here it is."]  # no card
    assert "can't skip a yes" in tool_result(scenario)
    assert "autonomy_grant" in tool_result(scenario)
    assert scenario.app.rulebook.drafts(scenario.member("Erin")) == []


async def test_a_reply_repeating_the_card_isnt_sent(scenario: Scenario) -> None:
    await packing_list(scenario)
    scenario.primary.queue_tool_call("add_to_list", {"list": "packing", "items": ["beach towels"]})
    scenario.primary.queue_text("Beach towels for Packing for the trip\nGo ahead, or not now?")
    replies = await scenario.say("Erin", "We'll be at the beach most days")
    assert replies == ["Beach towels for Packing for the trip\nGo ahead, or not now?"]


async def test_a_reply_repeating_only_the_cards_summary_isnt_sent(scenario: Scenario) -> None:
    await packing_list(scenario)
    scenario.primary.queue_tool_call("add_to_list", {"list": "packing", "items": ["beach towels"]})
    scenario.primary.queue_text("Beach towels for Packing for the trip")
    replies = await scenario.say("Erin", "We'll be at the beach most days")
    assert replies == ["Beach towels for Packing for the trip\nGo ahead, or not now?"]


async def test_a_reply_saying_more_than_the_card_is_sent(scenario: Scenario) -> None:
    await packing_list(scenario)
    scenario.primary.queue_tool_call("add_to_list", {"list": "packing", "items": ["beach towels"]})
    scenario.primary.queue_text("Towels could be handy. Want sun hats too?")
    replies = await scenario.say("Erin", "We'll be at the beach most days")
    assert replies[1] == "Towels could be handy. Want sun hats too?"
