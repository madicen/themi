"""Personal rules (F2): a rule can be just for the person who locks it."""

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.core.rules import PERSONAL_PROPOSAL_TEXT, PROPOSAL_TEXT

WORK = "Don't suggest chores during my work hours."
BINS = "Bins go out on Tuesday nights."


def queue(scenario: Scenario, summary: str, text: str, applies_to: str, **extra: object) -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": summary,
            "text": text,
            "kind": "policy",
            "category": "",
            "rule_id": 0,
            "applies_to": applies_to,
            **extra,
        },
    )
    scenario.primary.queue_text("Sent over for you to lock in.")


async def lock(scenario: Scenario, name: str, summary: str, text: str, applies_to: str) -> None:
    queue(scenario, summary, text, applies_to)
    await scenario.say(name, "let's make that a rule")
    await scenario.tap(name, "Lock it in")


async def test_a_personal_rule_shapes_only_its_owners_chats(scenario: Scenario) -> None:
    queue(scenario, "No chores during work", WORK, "personal")
    replies = await scenario.say("Erin", "a rule just for me: no chores during work hours")
    assert replies[0] == PERSONAL_PROPOSAL_TEXT.format(summary="No chores during work")
    await scenario.tap("Erin", "Lock it in")
    await lock(scenario, "Erin", "Bins on Tuesday", BINS, "household")

    scenario.primary.queue_text("Hi Erin.")
    await scenario.say("Erin", "hi")
    erin_system = scenario.primary.last_request.system
    assert WORK in erin_system and BINS in erin_system
    assert "Erin's personal rules (only in conversations with Erin):" in erin_system

    scenario.primary.queue_text("Hi.")
    await scenario.say("Husband", "hi")
    husband_system = scenario.primary.last_request.system
    assert BINS in husband_system and WORK not in husband_system


async def test_household_proposals_keep_the_plan_wording(scenario: Scenario) -> None:
    queue(scenario, "Bins on Tuesday", BINS, "household")
    replies = await scenario.say("Erin", "bins go out on Tuesdays")
    assert replies[0] == PROPOSAL_TEXT.format(summary="Bins on Tuesday")


async def test_rules_command_shows_your_personal_rules_only(scenario: Scenario) -> None:
    await lock(scenario, "Erin", "No chores during work", WORK, "personal")
    await lock(scenario, "Erin", "Bins on Tuesday", BINS, "household")

    (erin_view,) = await scenario.say("Erin", "/rules")
    assert "Household rules:\n• Bins on Tuesday" in erin_view
    assert "Just for you:\n• No chores during work" in erin_view
    (husband_view,) = await scenario.say("Husband", "/rules")
    assert "Bins on Tuesday" in husband_view and "No chores during work" not in husband_view


async def test_an_automatic_action_rule_takes_its_categorys_scope(scenario: Scenario) -> None:
    # F16a: archiving is about her own email, so the grant is personal whatever was asked.
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Archive promos automatically",
            "text": "Archive store promos without asking.",
            "kind": "autonomy_grant",
            "category": "email_archive_noise",
            "rule_id": 0,
            "applies_to": "household",
        },
    )
    scenario.primary.queue_text("Here it is.")
    await scenario.say("Erin", "archive my promos automatically")
    (draft,) = scenario.app.rulebook.drafts(scenario.member("Erin"))
    assert draft.scope == "personal"


async def test_refining_a_draft_can_change_its_scope(scenario: Scenario) -> None:
    queue(scenario, "Bins on Tuesday", BINS, "household")
    await scenario.say("Erin", "bins go out on Tuesdays")
    (draft,) = scenario.app.rulebook.drafts(scenario.member("Erin"))
    assert draft.scope == "household"

    queue(scenario, "Bins on Tuesday", BINS, "personal", rule_id=draft.id)
    await scenario.say("Erin", "actually just for me")
    assert scenario.app.rulebook.get(draft.id).scope == "personal"


async def test_the_website_shows_personal_rules_to_their_owner(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await lock(scenario, "Erin", "No chores during work", WORK, "personal")
    await lock(scenario, "Erin", "Bins on Tuesday", BINS, "household")

    await sign_in(scenario, site, "Erin")
    page = (await site.get("/knowledge")).text
    assert "Just for you" in page and "No chores during work" in page and "Bins on Tuesday" in page

    async with httpx.AsyncClient(transport=site._transport, base_url=str(site.base_url)) as other:
        await sign_in(scenario, other, "Husband")
        husband_page = (await other.get("/knowledge")).text
    assert "Bins on Tuesday" in husband_page and "No chores during work" not in husband_page
