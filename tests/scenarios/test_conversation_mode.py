"""CM1a: conversation mode, a plain chat reply with no tools for remarks and chat, while
requests keep the tool agent."""

from __future__ import annotations

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.core.conversation_mode import (
    CHAT_SYSTEM,
    NOT_OFFERED_TEXT,
    OFF_TEXT,
    ON_TEXT,
    STATUS_TEXT,
)


async def chat_on(scenario: Scenario, name: str = "Erin") -> None:
    assert await scenario.say(name, "/chat on") == [ON_TEXT]


def queue_nothing_picked_out(scenario: Scenario) -> None:
    """CM1b's sidecar reads each chat turn after its reply; here it finds nothing."""
    sidecar = getattr(scenario, "queue_sidecar", None)
    if sidecar is not None:
        sidecar({})


async def test_chat_on_and_off(scenario: Scenario) -> None:
    assert await scenario.say("Erin", "/chat") == [STATUS_TEXT[False]]
    await chat_on(scenario)
    assert scenario.member("Erin").conversation_mode
    assert not scenario.member("Husband").conversation_mode  # theirs alone
    assert await scenario.say("Erin", "/chat") == [STATUS_TEXT[True]]
    assert await scenario.say("Erin", "/chat off") == [OFF_TEXT]
    assert not scenario.member("Erin").conversation_mode


async def test_a_remark_gets_one_call_with_no_tools(scenario: Scenario) -> None:
    await chat_on(scenario)
    scenario.primary.queue_text("That sounds like a lot. How are you holding up?")
    queue_nothing_picked_out(scenario)
    replies = await scenario.say("Erin", "long day, the kids were a lot")
    assert replies == ["That sounds like a lot. How are you holding up?"]
    chats = [r for r in scenario.primary.requests if r.op == "chat"]
    assert len(chats) == 1
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
    assert not scenario.member("Erin").conversation_mode


async def test_with_the_rollout_on_everyone_sees_the_switch(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    scenario.app.services.conversation_rollout = "on"
    csrf = await sign_in(scenario, site, "Husband")
    assert 'name="conversation_mode"' in (await site.get("/settings")).text
    await site.post("/settings", data={"csrf": csrf, "conversation_mode": "on"})
    assert scenario.member("Husband").conversation_mode
    assert not scenario.member("Erin").conversation_mode


async def test_the_ai_page_has_the_two_new_routes(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/ai")).text
    assert "Conversation mode: the chat reply" in page
    assert "Conversation mode: picking out tasks in the background" in page


async def test_the_family_group_always_has_the_tool_agent(scenario: Scenario) -> None:
    await chat_on(scenario)
    conversation = scenario.app.services.conversation
    assert conversation is not None
    erin = scenario.member("Erin")
    assert conversation.takes(erin, "long day", in_group=False)
    assert not conversation.takes(erin, "long day", in_group=True)
