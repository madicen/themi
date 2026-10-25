"""Rules: brainstorm in chat, lock in with an explicit yes from the person it affects."""

import pytest

from tests.scenarios.harness import Scenario
from themi.autonomy import Tier
from themi.core.rules import (
    LOCKED_REPLY,
    PROPOSAL_TEXT,
    RuleError,
)

PROPOSAL = PROPOSAL_TEXT.format(summary="Archive store promos")
RULE_TEXT = "Archive promotional emails from stores without asking."


def queue_proposal(scenario: Scenario, kind: str = "policy", category: str = "") -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Archive store promos",
            "text": RULE_TEXT,
            "kind": kind,
            "category": category,
            "rule_id": 0,
        },
    )
    scenario.primary.queue_text("Here's that as a draft rule.")


async def test_plan_scenario_2_only_the_affected_persons_yes_locks(scenario: Scenario) -> None:
    """Erin brainstorms a rule, her husband replies YES, and nothing locks.
    Erin replies YES and it locks."""
    queue_proposal(scenario)
    replies = await scenario.say("Erin", "honestly store promo emails could just be archived")
    assert replies == [PROPOSAL, "Here's that as a draft rule."]
    assert scenario.last_buttons("Erin") == ["Lock it in"]
    rulebook = scenario.app.rulebook

    scenario.primary.queue_text("Yes to what? Happy to help.")
    await scenario.say("Husband", "YES")
    assert rulebook.locked() == []

    assert await scenario.say("Erin", "YES") == [LOCKED_REPLY]
    (rule,) = rulebook.locked()
    assert rule.text == RULE_TEXT
    assert scenario.edits("Erin")[-1]["text"] == "Locked in: Archive store promos."

    scenario.primary.queue_text("Morning!")
    await scenario.say("Husband", "morning")
    assert RULE_TEXT in scenario.primary.last_request.system  # in every request from now on


async def test_tapping_lock_it_in_locks_it(scenario: Scenario) -> None:
    queue_proposal(scenario)
    await scenario.say("Erin", "store promos can be archived")
    assert await scenario.tap("Erin", "Lock it in") == []  # the edited proposal is the answer
    assert [r.summary for r in scenario.app.rulebook.locked()] == ["Archive store promos"]


async def test_the_model_cant_lock_rules(scenario: Scenario) -> None:
    tool_names = scenario.app.services.tools.specs()
    assert "propose_rule" in [t.name for t in tool_names]
    assert not any("lock" in t.name for t in tool_names)


async def test_no_sets_the_idea_aside_and_not_now_keeps_it(scenario: Scenario) -> None:
    queue_proposal(scenario)
    await scenario.say("Erin", "maybe archive promos?")
    assert await scenario.say("Erin", "not now") == [
        "It's still a draft. We can come back to it whenever."
    ]
    assert len(scenario.app.rulebook.drafts(scenario.member("Erin"))) == 1
    assert await scenario.say("Erin", "no") == ["Okay, setting that idea aside."]
    assert scenario.app.rulebook.drafts(scenario.member("Erin")) == []
    assert scenario.edits("Erin")[-1]["text"] == "Set aside: Archive store promos."


async def test_refining_a_draft_retires_the_old_proposal(scenario: Scenario) -> None:
    queue_proposal(scenario)
    await scenario.say("Erin", "archive promos")
    (draft,) = scenario.app.rulebook.drafts(scenario.member("Erin"))
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Archive store promos, except Costco",
            "text": "Archive promos except Costco.",
            "kind": "policy",
            "category": "",
            "rule_id": draft.id,
        },
    )
    scenario.primary.queue_text("Updated.")
    replies = await scenario.say("Erin", "but keep the Costco ones")
    assert replies[0] == PROPOSAL_TEXT.format(summary="Archive store promos, except Costco")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Earlier version: Archive store promos. (Updated below.)"
    )
    (still_one,) = scenario.app.rulebook.drafts(scenario.member("Erin"))
    assert still_one.id == draft.id


async def test_an_autonomy_grant_rule_makes_its_category_automatic(scenario: Scenario) -> None:
    queue_proposal(scenario, "autonomy_grant", "email_archive_noise")
    await scenario.say("Erin", "you can just archive promos without asking")
    autonomy = scenario.app.services.autonomy
    assert autonomy.category("email_archive_noise").tier is Tier.SUPERVISED  # not until locked
    await scenario.say("Erin", "yes")
    category = autonomy.category("email_archive_noise")
    assert category.tier is Tier.AUTOMATIC
    assert category.granted_by_rule == scenario.app.rulebook.locked()[0].id


async def test_capped_categories_are_refused_gently_at_proposal(scenario: Scenario) -> None:
    queue_proposal(scenario, "autonomy_grant", "email_reply")
    replies = await scenario.say("Erin", "just send my email replies without asking")
    assert replies == ["Here's that as a draft rule."]  # no proposal was sent
    result = scenario.primary.last_request.messages[2].content[0]
    assert "Send an email reply always needs a yes from someone" in result.content  # type: ignore[union-attr]
    assert scenario.app.rulebook.drafts(scenario.member("Erin")) == []


async def test_autonomy_grants_need_an_admin(scenario: Scenario) -> None:
    queue_proposal(scenario, "autonomy_grant", "grocery_list_add")
    await scenario.say("Husband", "just add staples to the list yourself")
    result = scenario.primary.last_request.messages[2].content[0]
    assert "takes an admin" in result.content  # type: ignore[union-attr]
    assert scenario.app.rulebook.drafts(scenario.member("Husband")) == []


async def test_drafts_lapse_quietly_after_two_weeks(scenario: Scenario) -> None:
    queue_proposal(scenario)
    await scenario.say("Erin", "archive promos?")
    sent_before = len(scenario.inbox("Erin"))
    await scenario.advance(hours=24 * 13)
    assert await scenario.run_periodic("rules.expire_drafts") == 0
    await scenario.advance(hours=24)
    assert await scenario.run_periodic("rules.expire_drafts") == 1
    assert scenario.edits("Erin")[-1]["text"].startswith("This idea lapsed: Archive store promos.")
    assert len(scenario.inbox("Erin")) == sent_before


async def test_rules_command_lists_locked_rules_and_my_drafts(scenario: Scenario) -> None:
    assert (await scenario.say("Erin", "/rules"))[0].startswith("No household rules yet.")
    queue_proposal(scenario)
    await scenario.say("Erin", "archive promos")
    await scenario.say("Erin", "yes")
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Bins reminder on Tuesdays",
            "text": "Mention the bins on Tuesday evenings.",
            "kind": "policy",
            "category": "",
            "rule_id": 0,
        },
    )
    scenario.primary.queue_text("Drafted.")
    await scenario.say("Erin", "bins go out wednesday mornings")
    (listing,) = await scenario.say("Erin", "/rules")
    assert listing == (
        "Locked rules:\n• Archive store promos\n\nYour drafts:\n• Bins reminder on Tuesdays"
    )
    (his,) = await scenario.say("Husband", "/rules")
    assert his == "Locked rules:\n• Archive store promos"  # Erin's drafts are hers


async def test_unlocking_an_autonomy_rule_takes_the_permission_back(scenario: Scenario) -> None:
    queue_proposal(scenario, "autonomy_grant", "email_archive_noise")
    await scenario.say("Erin", "archive promos without asking")
    await scenario.say("Erin", "yes")
    (rule,) = scenario.app.rulebook.locked()
    scenario.app.rulebook.unlock(rule.id, scenario.member("Erin"))
    assert scenario.app.services.autonomy.category("email_archive_noise").tier is Tier.SUPERVISED
    assert scenario.app.rulebook.locked() == []


async def test_standing_reminders_lock_straight_away(scenario: Scenario) -> None:
    rule = scenario.app.rulebook.add_standing_reminder(
        scenario.member("Erin"), "Vet is on Tuesdays", "Luna's vet visits are always on Tuesdays."
    )
    assert rule.status == "locked" and rule.kind == "standing_reminder"
    assert "Luna's vet visits are always on Tuesdays." in scenario.app.services.rules()


async def test_proposals_need_content(scenario: Scenario) -> None:
    with pytest.raises(RuleError):
        await scenario.app.rulebook.propose(scenario.member("Erin"), " ", "text")
    with pytest.raises(RuleError):
        await scenario.app.rulebook.propose(scenario.member("Erin"), "x", "y", "standing_reminder")
