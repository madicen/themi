"""Conversations end to end: Telegram in, agent and tools, outbox and Telegram out."""

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.channels.events import Button
from themi.channels.outbox import Priority
from themi.core.agent import (
    BUSY_TEXT,
    DECLINED_TEXT,
    SETUP_NEEDED_TEXT,
    TANGLED_TEXT,
    VOICE_FAILED_TEXT,
)
from themi.core.prompts import STABLE_SYSTEM
from themi.core.services import AwaitingItem


async def test_hello_gets_a_reply(scenario: Scenario) -> None:
    scenario.primary.queue_text("Hi Erin! Quiet morning so far.")
    assert await scenario.say("Erin", "hello") == ["Hi Erin! Quiet morning so far."]

    request = scenario.primary.last_request
    assert request.system.startswith(STABLE_SYSTEM)
    turn = request.messages[0].text
    assert "Talking with: Erin (admin)" in turn
    assert "Local time: Wednesday 21 October 2026, 9:00 AM (America/Los_Angeles)" in turn
    assert turn.endswith("Erin says:\nhello")
    assert {"remember_fact", "log_energy_note", "list_open_items"} <= set(request.tool_names)


async def test_a_voice_note_is_transcribed_then_answered(scenario: Scenario) -> None:
    scenario.primary.queue_transcription("used the last of the olive oil")
    scenario.primary.queue_text("Thanks, I'll keep that in mind.")
    assert await scenario.voice("Erin", b"OggS-olive-oil") == ["Thanks, I'll keep that in mind."]
    transcribe, chat = scenario.primary.requests
    assert transcribe.op == "transcribe" and transcribe.audio == b"OggS-olive-oil"
    assert chat.messages[0].text.endswith("Erin says:\nused the last of the olive oil")
    texts = [m.text for m in scenario.app.store.recent_messages(scenario.member("Erin").id)]
    assert "used the last of the olive oil" in texts
    assert scenario.typing_shown("Erin")


async def test_an_unreadable_voice_note_gets_a_gentle_reply(scenario: Scenario) -> None:
    scenario.primary.queue_transcription("")
    scenario.fallback.queue_transcription("")
    assert await scenario.voice("Erin") == [VOICE_FAILED_TEXT]


async def test_tool_call_then_reply(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "remember_fact",
        {
            "subject": "vet",
            "fact": "Luna's vet appointments are on Tuesdays.",
            "about": "household",
        },
    )
    scenario.primary.queue_text("Got it, Tuesdays for Luna's vet.")
    assert await scenario.say("Erin", "the vet is always on tuesdays for Luna") == [
        "Got it, Tuesdays for Luna's vet."
    ]
    _first, second = scenario.primary.requests
    tool_result = second.messages[2].content[0]
    assert isinstance(tool_result, ToolResult)
    assert tool_result.content == "Remembered: Luna's vet appointments are on Tuesdays."
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM facts") == 1

    scenario.primary.queue_text("Tuesday it is.")
    await scenario.say("Husband", "when is the vet?")
    turn = scenario.primary.last_request.messages[0].text
    assert "- Luna's vet appointments are on Tuesdays." in turn  # retrieved for this message


async def test_bad_tool_arguments_go_back_to_the_model(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("log_energy_note", {"effect": 9, "note": "huge"})
    scenario.primary.queue_text("Sounds like a big day.")
    await scenario.say("Erin", "today was a lot")
    result = scenario.primary.last_request.messages[2].content[0]
    assert isinstance(result, ToolResult)
    assert result.is_error and "Invalid arguments" in result.content
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM energy_signals") == 0


async def test_energy_notes_respect_tracking_toggles(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, tracking={"text_notes": False})
    scenario.primary.queue_tool_call("log_energy_note", {"effect": -2, "note": "long call"})
    scenario.primary.queue_text("That sounds draining.")
    await scenario.say("Erin", "that client call took a lot out of me")
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM energy_signals") == 0


async def test_no_ai_available_says_so_plainly(scenario: Scenario) -> None:
    scenario.primary.fail(3, status=503)
    scenario.fallback.fail(3, status=503)
    assert await scenario.say("Erin", "hello?") == [BUSY_TEXT]


async def test_a_new_member_without_a_key_hears_how_to_set_up(scenario: Scenario) -> None:
    scenario.clear_ai_settings(scenario.member("Husband"))
    assert await scenario.say("Husband", "hi") == [SETUP_NEEDED_TEXT]


async def test_refusals_are_brief(scenario: Scenario) -> None:
    scenario.primary.queue_refusal("cyber")
    scenario.fallback.queue_refusal("cyber")
    assert await scenario.say("Erin", "something off-limits") == [DECLINED_TEXT]


async def test_plan_scenario_3_overloaded_primary_falls_back_once(scenario: Scenario) -> None:
    """Gemini returns 503 three times during a chat: typing shows, the call falls back,
    and exactly one reply arrives."""
    scenario.primary.fail(3, status=503)
    scenario.fallback.queue_text("Here's that answer.")
    replies = await scenario.say("Erin", "what's on today?")
    assert replies == ["Here's that answer."]
    assert len(scenario.primary.requests) == 3
    assert scenario.typing_shown("Erin")


async def test_the_step_limit_stops_runaway_tool_loops(scenario: Scenario) -> None:
    for _ in range(8):
        scenario.primary.queue_tool_call("list_open_items", {})
    assert await scenario.say("Erin", "loop please") == [TANGLED_TEXT]


async def test_choice_buttons_answer_as_if_typed(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await scenario.app.outbox.send(
        erin,
        "Washer's done. Dryer now, or later tonight?",
        priority=Priority.NORMAL,
        buttons=[
            Button("Dryer now", "reply", {"text": "Dryer now"}),
            Button("Later tonight", "reply", {"text": "Later tonight"}),
        ],
    )
    scenario.primary.queue_text("Later tonight works.")
    assert await scenario.tap("Erin", "Later tonight") == ["Later tonight works."]
    assert scenario.primary.last_request.messages[0].text.endswith("Erin says:\nLater tonight")


async def test_feedback_about_tone_calibrates_shielding(scenario: Scenario) -> None:
    scenario.primary.queue_text("Understood, I'll keep things lighter.")
    await scenario.say("Erin", "that last message was too pushy")
    assert scenario.app.store.get_member(scenario.member("Erin").id).pda_strength == 3


async def test_replies_are_pda_shielded(scenario: Scenario) -> None:
    scenario.primary.queue_text("You need to move the laundry.")
    scenario.primary.queue_structured(
        {"text": "The laundry's ready whenever you are.", "options": []}
    )
    assert await scenario.say("Erin", "anything?") == ["The laundry's ready whenever you are."]


async def test_yes_resolves_the_single_waiting_item_without_the_model(scenario: Scenario) -> None:
    decisions: list[str] = []

    async def resolve(decision: str) -> str:
        decisions.append(decision)
        return "Done, the cart is staged."

    scenario.app.services.awaiting_sources.append(
        lambda member: (
            [AwaitingItem("cart:1", "Stage the Safeway cart", resolve)]
            if member.name == "Erin"
            else []
        )
    )
    assert await scenario.say("Erin", "Yes!") == ["Done, the cart is staged."]
    assert decisions == ["yes"] and scenario.primary.requests == []


async def test_yes_with_nothing_waiting_goes_to_the_model(scenario: Scenario) -> None:
    scenario.primary.queue_text("Yes to what? Happy to help.")
    await scenario.say("Erin", "yes")
    assert len(scenario.primary.requests) == 1


async def test_recent_conversation_is_in_the_next_turn(scenario: Scenario) -> None:
    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "good morning")
    scenario.primary.queue_text("Toast or soup?")
    await scenario.say("Erin", "lunch ideas?")
    turn = scenario.primary.last_request.messages[0].text
    assert "Erin: good morning\nThemi: Morning!" in turn
    assert "Erin: lunch ideas?" not in turn  # the current message isn't repeated as history


async def test_strangers_never_reach_the_agent(scenario: Scenario) -> None:
    scenario.telegram.send_text(4242, "hello")
    await scenario.app.channel.poll_once()
    assert scenario.primary.requests == []


async def test_plan_scenario_5_a_forgotten_fact_is_pinned_and_used(scenario: Scenario) -> None:
    """Erin says "you keep forgetting the cat's vet is on Tuesdays". The fact gets pinned
    and appears in the next request."""
    scenario.primary.queue_tool_call(
        "report_forgotten_context",
        {
            "what_was_forgotten": "the cat's vet is on Tuesdays",
            "correct_version": "The cat's vet appointments are on Tuesdays.",
        },
    )
    scenario.primary.queue_text("Sorry about that. It's saved now and I'll keep it in mind.")
    await scenario.say("Erin", "you keep forgetting the cat's vet is on Tuesdays")
    result = scenario.primary.last_request.messages[2].content[0]
    assert isinstance(result, ToolResult) and result.content.startswith("Diagnosis: never_stored")

    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "good morning")
    assert "The cat's vet appointments are on Tuesdays." in scenario.primary.last_request.system
    (repair,) = scenario.app.services.memory.repairs()  # type: ignore[union-attr]
    assert repair["diagnosis"] == "never_stored"


async def test_a_question_about_a_suggestion_isnt_a_forgotten_fact(scenario: Scenario) -> None:
    """Idea #8: Erin asked why Themi offered a water check-in. The model reported it as
    forgotten context, and a note about the offer was pinned for the whole family."""
    scenario.primary.queue_tool_call(
        "report_forgotten_context",
        {
            "what_was_forgotten": "that you didn't configure the water check-in yourself",
            "correct_version": "Water check-ins were suggested, not configured by you.",
        },
    )
    scenario.primary.queue_text("It was just an idea to try.")
    await scenario.say(
        "Erin", "What prompted you to send me the water check in? I did not configure that"
    )
    result = scenario.primary.last_request.messages[2].content[0]
    assert isinstance(result, ToolResult) and result.is_error
    assert scenario.app.services.memory.repairs() == []  # type: ignore[union-attr]
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM facts") == 0


async def test_ignored_twice_becomes_a_standing_rule(scenario: Scenario) -> None:
    memory = scenario.app.services.memory
    assert memory is not None
    memory.remember(scenario.member("Erin"), "vet", "The cat's vet is on Tuesdays.", pinned=True)
    scenario.primary.queue_tool_call(
        "report_forgotten_context",
        {
            "what_was_forgotten": "cat vet Tuesdays",
            "correct_version": "The cat's vet is on Tuesdays.",
        },
    )
    scenario.primary.queue_text("I'm sorry. It's a standing reminder now.")
    await scenario.say("Erin", "you forgot the vet AGAIN")
    household, _ = scenario.app.services.rules(scenario.member("Erin"))
    assert "Always keep in mind: The cat's vet is on Tuesdays." in household
    (listing,) = await scenario.say("Erin", "/rules")
    assert "Keep in mind: vet" in listing


async def test_a_draining_remark_changes_how_themi_reads_erin(scenario: Scenario) -> None:
    import re

    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "morning")
    assert "How Erin seems: steady" in scenario.primary.last_request.messages[0].text

    scenario.primary.queue_tool_call("log_energy_note", {"effect": -3, "note": "long client call"})
    scenario.primary.queue_text("That sounds like a lot. Go gently.")
    await scenario.say("Erin", "that client call took a lot out of me")

    scenario.primary.queue_text("Toast or soup?")
    await scenario.say("Erin", "lunch ideas?")
    turn = scenario.primary.last_request.messages[0].text
    line = next(row for row in turn.splitlines() if row.startswith("How Erin seems:"))
    assert line == "How Erin seems: seems like a low stretch"
    assert not re.search(r"\d", line)

    scenario.primary.queue_text("Hey!")
    await scenario.say("Husband", "hi")
    assert "How Husband seems: steady" in scenario.primary.last_request.messages[0].text


async def test_replies_to_themis_nudges_teach_the_shadow_calendar(scenario: Scenario) -> None:
    from themi.channels.outbox import Priority

    erin = scenario.member("Erin")
    tracker = scenario.app.services.outcomes
    assert tracker is not None
    await scenario.app.outbox.send(erin, "The feeders are getting low.", priority=Priority.NORMAL)
    scenario.primary.queue_text("Thanks for topping them up!")
    await scenario.say("Erin", "just refilled them")
    await scenario.app.outbox.send(erin, "The filter change is due.", priority=Priority.NORMAL)
    await scenario.advance(hours=3)
    assert await scenario.run_periodic("energy.expire_outcomes") == 1
    assert [r["outcome"] for r in tracker.history(erin.id)] == ["acted", "ignored"]


async def test_a_message_to_pass_on_isnt_saved_as_a_note(scenario: Scenario) -> None:
    """Found reading the reports of 2026-10-27: "can you tell Hundo 'I Wuv U'?" was saved as
    a note and answered "I've saved that for her". Themi can't pass messages on yet."""
    scenario.primary.queue_tool_call(
        "remember_fact",
        {"subject": "message", "fact": "Michael says I Wuv U to Erin.", "about": "household"},
    )
    scenario.primary.queue_text("I can't pass messages on yet.")
    await scenario.say("Husband", "Can you tell Hundo “I Wuv U ❤️”?")
    result = scenario.primary.last_request.messages[2].content[0]
    assert isinstance(result, ToolResult)
    assert "can't pass messages on yet" in result.content
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM facts") == 0


def test_a_busy_reply_doesnt_promise_a_retry() -> None:
    # Bug #77's thread: "Will you retry automatically?" got "Yes, I will retry that
    # automatically as soon as the service is clear." Nothing retries it.
    assert "I won't retry it on my own" in BUSY_TEXT
    from themi.core.prompts import STABLE_SYSTEM

    assert "isn't retried by Themi" in STABLE_SYSTEM


async def test_a_reply_in_quotes_is_sent_without_them(scenario: Scenario) -> None:
    """Bugs #98 and #100 ("why are there quotes around the whole thing?")."""
    erin = scenario.member("Erin")
    board = scenario.app.services.taskboard
    assert board is not None
    task = await board.create(erin, "Refill whoosh litter", "errand", 1, assignee=erin)
    scenario.primary.queue_text(f"'Task {task.id} is set up for both of you.'")
    replies = await scenario.say("Erin", "For both of us, refill whoosh litter")
    assert replies == ['"Refill whoosh litter" is set up for both of you.']


async def test_a_reply_opening_with_a_tasks_title_keeps_it_in_quotes(scenario: Scenario) -> None:
    """The evals of 2026-10-31: '"Renew the car registration is on both lists..."' lost its
    quotes (#98), and the title then read as a command to renew it."""
    erin = scenario.member("Erin")
    board = scenario.app.services.taskboard
    assert board is not None
    task = await board.create(erin, "Renew the car registration", "errand", 1, assignee=erin)
    scenario.primary.queue_tool_call("complete_task", {"task_id": task.id})
    scenario.primary.queue_text('"Renew the car registration is done now."')
    replies = await scenario.say("Erin", "I renewed the car registration")
    assert replies == ['"Renew the car registration" is done now.']
