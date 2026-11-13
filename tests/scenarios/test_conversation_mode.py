"""CM1a: conversation mode, a plain chat reply with no tools for remarks and chat, while
requests keep the tool agent."""

from __future__ import annotations

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.types import CallKind
from themi.core import keys
from themi.standard.conversation_mode import (
    CHAT_SYSTEM,
    NOT_OFFERED_TEXT,
    OFF_TEXT,
    ON_TEXT,
    STATUS_TEXT,
    ConversationPreferences,
)


async def chat_on(scenario: Scenario, name: str = "Erin") -> None:
    assert await scenario.say(name, "/chat on") == [ON_TEXT]


def queue_nothing_picked_out(scenario: Scenario) -> None:
    """CM1b's sidecar reads each chat turn after its reply; here it finds nothing."""
    scenario.primary.queue_text("nothing")


async def test_chat_on_and_off(scenario: Scenario) -> None:
    assert await scenario.say("Erin", "/chat") == [STATUS_TEXT[False]]
    await chat_on(scenario)
    assert scenario.app.store.preferences(
        scenario.member("Erin").id, ConversationPreferences
    ).conversation_mode
    assert not scenario.app.store.preferences(
        scenario.member("Husband").id, ConversationPreferences
    ).conversation_mode  # theirs alone
    assert await scenario.say("Erin", "/chat") == [STATUS_TEXT[True]]
    assert await scenario.say("Erin", "/chat off") == [OFF_TEXT]
    assert not scenario.app.store.preferences(
        scenario.member("Erin").id, ConversationPreferences
    ).conversation_mode


async def test_a_remark_gets_one_call_with_no_tools(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.queue_text("That sounds like a lot. How are you holding up?")
    queue_nothing_picked_out(scenario)
    replies = await scenario.say("Erin", "long day, the kids were a lot")
    assert replies == ["That sounds like a lot. How are you holding up?"]
    chats = [r for r in scenario.primary.requests if r.kind is CallKind.INTERACTIVE]
    assert len(chats) == 1  # the reply; the sidecar's pass is a background call (CM1b)
    assert chats[0].tools == () and chats[0].system == CHAT_SYSTEM
    turn = chats[0].messages[0].text
    assert "long day, the kids were a lot" in turn and "seems" not in turn


async def test_a_request_still_goes_to_the_tool_agent(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.queue_text("Which list?")
    await scenario.say("Erin", "add milk")
    assert scenario.primary.requests[0].tools  # the usual tools
    assert scenario.primary.requests[0].system != CHAT_SYSTEM


async def test_mode_off_is_the_usual_agent(scenario: Scenario) -> None:
    scenario.primary.queue_text("Sounds like a long day.")
    await scenario.say("Erin", "long day, the kids were a lot")
    assert scenario.primary.requests[0].tools


async def test_the_chat_reply_never_says_it_did_something(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.queue_text("I've added a reminder for the vet. That sounds stressful.")
    queue_nothing_picked_out(scenario)
    replies = await scenario.say("Erin", "ugh, the cat's been off her food all week")
    assert replies == ["That sounds stressful."]


async def test_burnout_mode_is_in_the_chat_context(scenario: Scenario) -> None:
    await scenario.say("Erin", "/burnout")
    await chat_on(scenario)
    scenario.primary.queue_text("I'm here.")
    queue_nothing_picked_out(scenario)
    await scenario.say("Erin", "everything is too much")
    chat = next(r for r in scenario.primary.requests if r.op == "chat")
    assert "Modes they're in: burnout mode" in chat.messages[0].text


async def test_no_ai_backend_is_said_plainly(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.fail(5, status=503)
    scenario.fallback.fail(5, status=503)
    replies = await scenario.say("Erin", "what a week")
    assert replies and "{" not in replies[-1] and "503" not in replies[-1]


async def test_the_rollout_can_turn_it_off(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.app.services.conversation_rollout = "off"
    assert await scenario.say("Erin", "/chat on") == [NOT_OFFERED_TEXT]
    scenario.primary.queue_text("Sounds like a long day.")
    await scenario.say("Erin", "long day")
    assert scenario.primary.requests[0].tools  # the usual agent, whatever the setting


async def test_the_switch_shows_in_a_trial_only_once_its_on(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    assert 'name="conversation_mode"' not in (await site.get("/settings")).text
    await chat_on(scenario)
    page = await site.get("/settings")
    assert 'name="conversation_mode" checked' in page.text
    await site.post("/settings", data={"csrf": csrf, "pda_enabled": "on"})  # unticked
    assert not scenario.app.store.preferences(
        scenario.member("Erin").id, ConversationPreferences
    ).conversation_mode


async def test_with_the_rollout_on_everyone_sees_the_switch(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    scenario.app.services.conversation_rollout = "on"
    csrf = await sign_in(scenario, site, "Husband")
    assert 'name="conversation_mode"' in (await site.get("/settings")).text
    await site.post("/settings", data={"csrf": csrf, "conversation_mode": "on"})
    assert scenario.app.store.preferences(
        scenario.member("Husband").id, ConversationPreferences
    ).conversation_mode
    assert not scenario.app.store.preferences(
        scenario.member("Erin").id, ConversationPreferences
    ).conversation_mode


async def test_the_ai_page_has_the_two_new_routes(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/ai")).text
    assert "Conversation mode: the chat reply" in page
    assert "Conversation mode: picking out tasks in the background" in page


async def test_the_family_group_always_has_the_tool_agent(scenario: Scenario) -> None:
    await chat_on(scenario)
    conversation = scenario.app.services.maybe(keys.conversation)
    assert conversation is not None
    erin = scenario.member("Erin")
    assert conversation.takes(erin, "long day", in_group=False)
    assert not conversation.takes(erin, "long day", in_group=True)


async def test_no_run_today_goes_to_the_tools(scenario: Scenario) -> None:
    """F34a, bug #178: with conversation mode on, "No run today ..." about her open run went
    to the tool-less chat, which said "Got it", and the run stayed due."""
    board = scenario.app.services.maybe(keys.taskboard)
    assert board is not None
    erin = scenario.member("Erin")
    await board.create(erin, "Go for a run", "physical", 2, assignee=erin, check_in=True)
    await chat_on(scenario)
    scenario.primary.queue_text("Moved it.")
    await scenario.say("Erin", "No run today. I plan to run 1.3 miles either tomorrow or Sunday")
    assert scenario.primary.requests[0].tools
    assert scenario.primary.requests[0].system != CHAT_SYSTEM


async def test_can_we_body_double_goes_to_the_tools(scenario: Scenario) -> None:
    """F34a, bug #179: "Can we body double the bird cage?" got a chat reply, no session."""
    await chat_on(scenario)
    scenario.primary.queue_text("Sure.")
    await scenario.say("Erin", "Can we body double the bird cage?")
    assert scenario.primary.requests[0].tools


# ----- F36a (ideas #185, #186) ----------------------------------------------------------


def things_to_buy(scenario: Scenario) -> list[tuple[str, str]]:
    rows = scenario.app.db.query(
        "SELECT i.name, m.name AS who FROM list_items i JOIN lists l ON l.id = i.list_id "
        "LEFT JOIN members m ON m.id = i.added_by WHERE l.purpose = 'things_to_buy' "
        "AND i.done = 0 ORDER BY i.id"
    )
    return [(r["name"], r["who"]) for r in rows]


async def test_things_to_research_buy_goes_on_things_to_buy(scenario: Scenario) -> None:
    """Sun 9:54 am: "Things to research buy. VNS device" got "Got it." and was on no list."""
    await chat_on(scenario)
    scenario.primary.queue_tool_call(
        "add_to_things_to_buy", {"items": [{"name": "VNS device", "store": ""}]}
    )
    scenario.primary.queue_text("Added the VNS device to Things to Buy.")
    await scenario.say("Erin", "Things to research buy. VNS device")
    assert scenario.primary.requests[0].system != CHAT_SYSTEM  # the tool agent
    assert things_to_buy(scenario) == [("VNS device", "Erin")]

    scenario.primary.queue_text("On Things to Buy: the VNS device.")
    await scenario.say("Erin", "What are the things I need to research buy?")
    assert scenario.primary.requests[-1].system != CHAT_SYSTEM


async def test_a_correction_to_her_draft_rule_rewords_it(scenario: Scenario) -> None:
    """Sun 9:21 am: draft rule 29 kept its broader wording; the chat had no tools."""
    erin = scenario.member("Erin")
    first = await scenario.app.rulebook.propose(
        erin, "Track who added items to Things to Buy and prompt only that person", "x",
        scope="personal",
    )  # fmt: skip
    await chat_on(scenario)
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "For research or someday buys, prompt only the person who added them",
            "text": "Only for research or someday purchases: track who added them.",
            "kind": "policy", "category": "", "rule_id": first.id, "applies_to": "personal",
        },
    )  # fmt: skip
    scenario.primary.queue_text("Reworded it.")
    await scenario.say(
        "Erin",
        "That rule is too general. Specifically for purchases that require research or are "
        'for "someday", track which user added them and only prompt that user',
    )
    (draft,) = scenario.app.rulebook.drafts(erin)
    assert draft.id == first.id and draft.summary.startswith("For research or someday buys")


async def test_with_no_draft_too_general_stays_chat(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.queue_text("Fair enough.")
    queue_nothing_picked_out(scenario)
    await scenario.say("Erin", "that's too general")
    assert scenario.primary.requests[0].system == CHAT_SYSTEM
