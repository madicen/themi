"""34b: the family group and alignment prompts. Erin is the admin; her quiet hours are
21:30-08:00, her husband's start at 23:00. The clock starts Wednesday 21 October 2026,
9 am Pacific."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from tests.scenarios.harness import GROUP_CHAT, START, Scenario
from themi.accounts import Member
from themi.ai.types import ToolResult
from themi.channels.outbox import Priority
from themi.channels.telegram import (
    GROUP_ADMIN_ONLY_TEXT,
    GROUP_LINKED_PRIVACY_TEXT,
    GROUP_LINKED_TEXT,
    GROUP_UNLINKED_TEXT,
)

BOT = "@themi_test_bot"
STRANGER = 3001
QUESTION = "A quick one for you both: How full should the feeders be?"


class Windows:
    """Receptivity: each person's next good window."""

    def __init__(self, **by_name: datetime) -> None:
        self.by_name = by_name

    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        return max(now, self.by_name.get(member.name, now))


def linked(scenario: Scenario) -> int | None:
    return scenario.app.outbox.family_group.chat_id()


def model_calls(scenario: Scenario) -> int:
    return len(scenario.primary.requests)


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


async def flag(scenario: Scenario, name: str = "Husband") -> list[str]:
    scenario.primary.queue_tool_call(
        "flag_expectation_conflict",
        {
            "topic": "How full the feeders should be",
            "question": "How full should the feeders be?",
            "option_a": "Half full",
            "option_b": "To the top",
        },
    )
    scenario.primary.queue_text("Okay.")
    return await scenario.say(name, "Erin keeps filling the feeders right to the top, I'd go half")


def alignments(scenario: Scenario) -> list[dict]:
    return scenario.app.db.query("SELECT * FROM liaison_items WHERE kind = 'alignment'")


# ----- linking --------------------------------------------------------------------


async def test_an_admin_links_the_family_group(scenario: Scenario) -> None:
    assert await scenario.link_group() == [GROUP_LINKED_TEXT]
    assert linked(scenario) == GROUP_CHAT
    # and unlinks it
    assert await scenario.say_in_group("Erin", "/familygroup off") == [GROUP_UNLINKED_TEXT]
    assert linked(scenario) is None


async def test_only_an_admin_links_it(scenario: Scenario) -> None:
    assert await scenario.say_in_group("Husband", "/familygroup") == [GROUP_ADMIN_ONLY_TEXT]
    assert linked(scenario) is None
    # someone outside the family gets nothing at all
    assert await scenario.say_in_group("", "/familygroup", user_id=STRANGER) == []
    assert linked(scenario) is None


async def test_a_link_command_for_another_bot_is_left_alone(scenario: Scenario) -> None:
    assert await scenario.say_in_group("Erin", "/familygroup@other_bot") == []
    assert linked(scenario) is None


async def test_an_unlinked_group_is_ignored(scenario: Scenario) -> None:
    before = model_calls(scenario)
    assert await scenario.say_in_group("Erin", f"{BOT} what's on today?") == []
    assert model_calls(scenario) == before


async def test_the_link_follows_the_group_when_it_becomes_a_supergroup(
    scenario: Scenario,
) -> None:
    await scenario.link_group()
    scenario.telegram.migrate(1001, GROUP_CHAT, -100_5001)
    await scenario.app.channel.poll_once()
    assert linked(scenario) == -100_5001


async def test_in_their_own_chat_familygroup_says_how(scenario: Scenario) -> None:
    (reply,) = await scenario.say("Husband", "/familygroup")
    assert "add me to it" in reply and "ask an admin" in reply


# ----- who's heard in the group ---------------------------------------------------


async def test_only_family_messages_meant_for_themi_are_handled(scenario: Scenario) -> None:
    await scenario.link_group()
    before = model_calls(scenario)
    logged = scenario.app.db.scalar("SELECT COUNT(*) FROM message_log")
    # someone outside the family, even mentioning Themi
    assert await scenario.say_in_group("", f"{BOT} hello", user_id=STRANGER) == []
    # the family talking among themselves
    assert await scenario.say_in_group("Erin", "Dinner at six?") == []
    assert model_calls(scenario) == before
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM message_log") == logged  # not kept


async def test_a_mention_is_answered_in_the_group(scenario: Scenario) -> None:
    await scenario.link_group()
    erin_before = len(scenario.inbox("Erin"))
    scenario.primary.queue_text("Nothing on the calendar today.")
    replies = await scenario.say_in_group("Erin", f"{BOT} what's on today?")
    assert replies == ["Nothing on the calendar today."]
    assert len(scenario.inbox("Erin")) == erin_before  # not in her own chat
    turn = scenario.primary.last_request.messages[0].text
    assert "Where: the family group" in turn
    assert "Erin says:\nwhat's on today?" in turn  # the mention taken out


async def test_themis_name_first_is_answered_in_the_group(scenario: Scenario) -> None:
    """Bug #143: "Themi, are you seeing this?" went unanswered."""
    await scenario.link_group()
    scenario.primary.queue_text("I am.")
    assert await scenario.say_in_group("Husband", "Themi, are you seeing this?") == ["I am."]
    turn = scenario.primary.last_request.messages[0].text
    assert "says:\nare you seeing this?" in turn  # the name taken out
    scenario.primary.queue_text("Nothing today.")
    assert await scenario.say_in_group("Erin", "hey themi what's on today") == ["Nothing today."]
    assert "says:\nwhat's on today" in scenario.primary.last_request.messages[0].text


async def test_themi_named_in_passing_isnt_for_themi(scenario: Scenario) -> None:
    await scenario.link_group()
    before = model_calls(scenario)
    assert await scenario.say_in_group("Erin", "I told Themi about the vet") == []
    assert await scenario.say_in_group("Erin", "Themis was a Titan") == []
    assert model_calls(scenario) == before


async def test_a_message_not_for_themi_leaves_a_trace_without_its_words(
    scenario: Scenario, caplog: pytest.LogCaptureFixture
) -> None:
    await scenario.link_group()
    caplog.set_level(logging.DEBUG, logger="themi.channels.telegram")
    await scenario.say_in_group("Erin", "Dinner at six?")
    assert "not meant for Themi" in caplog.text
    assert "Dinner" not in caplog.text


async def test_with_group_privacy_on_the_link_says_what_reaches_themi(
    scenario: Scenario,
) -> None:
    """Bug #143: the bot's privacy mode was on, so the mention never arrived, though the
    link message said mentions work."""
    scenario.telegram.state.group_privacy = True
    (linked_text,) = await scenario.link_group()
    assert linked_text == GROUP_LINKED_PRIVACY_TEXT
    assert "/setprivacy" in linked_text
    before = model_calls(scenario)
    assert await scenario.say_in_group("Husband", f"{BOT} are you seeing this?") == []
    assert model_calls(scenario) == before  # Telegram never delivered it
    scenario.primary.queue_text("Yes.")
    assert await scenario.say_in_group(
        "Husband", "Are you there?", reply_to_text=GROUP_LINKED_PRIVACY_TEXT
    ) == ["Yes."]


async def test_a_privacy_change_shows_at_the_next_link(scenario: Scenario) -> None:
    scenario.telegram.state.group_privacy = True
    assert await scenario.link_group() == [GROUP_LINKED_PRIVACY_TEXT]
    scenario.telegram.state.group_privacy = False  # turned off in @BotFather
    assert await scenario.link_group() == [GROUP_LINKED_TEXT]


async def test_a_reply_to_themi_in_the_group_is_answered_there(scenario: Scenario) -> None:
    await scenario.link_group()
    scenario.primary.queue_text("Happy to.")
    replies = await scenario.say_in_group(
        "Husband", "Thanks, glad you're here", reply_to_text=GROUP_LINKED_TEXT
    )
    assert replies == ["Happy to."]


async def test_their_own_chat_has_no_group_note(scenario: Scenario) -> None:
    scenario.primary.queue_text("Hi.")
    await scenario.say("Erin", "hello")
    assert "Where: the family group" not in scenario.primary.last_request.messages[0].text


# ----- alignment prompts ----------------------------------------------------------


async def test_without_a_group_the_question_isnt_asked(scenario: Scenario) -> None:
    await flag(scenario)
    assert "no family group yet" in tool_result(scenario)
    assert alignments(scenario) == []


async def test_an_alignment_question_waits_for_both_windows(scenario: Scenario) -> None:
    await scenario.link_group()
    scenario.app.outbox.receptivity = Windows(
        Erin=START + timedelta(hours=2), Husband=START + timedelta(hours=6)
    )
    replies = await flag(scenario)
    assert replies == [
        "I'll ask you both in the family group when it's a good moment for you both "
        "(likely today around 3 pm)."
    ]
    husband = scenario.member("Husband")
    waiting = [i.summary for i in scenario.app.services.open_items(husband)]
    assert any(s.startswith("A question for you both in the family group") for s in waiting)
    await scenario.advance(hours=2)  # Erin's window, not his
    assert QUESTION not in scenario.group_texts()
    await scenario.advance(hours=4)
    assert scenario.group_texts()[-1] == QUESTION
    (item,) = alignments(scenario)
    assert item["delivered_at"] is not None and item["to_member_id"] is None


async def test_the_same_question_isnt_asked_twice(scenario: Scenario) -> None:
    await scenario.link_group()
    await flag(scenario)
    await flag(scenario, "Erin")
    assert "already a question for you both" in tool_result(scenario)
    assert len(alignments(scenario)) == 1


async def test_an_agreement_becomes_a_rule_proposal(scenario: Scenario) -> None:
    await scenario.link_group()
    assert await flag(scenario) == ["I've asked you both in the family group."]
    assert scenario.group_texts()[-1] == QUESTION
    # each tap is recorded; a change of mind counts until both have answered
    await scenario.tap_in_group("Erin", "To the top")
    await scenario.tap_in_group("Erin", "Half full")
    assert (
        scenario.group_edits()[-1] == f"{QUESTION}\n\nErin picked: Half full. Waiting on Husband."
    )
    proposals = await scenario.tap_in_group("Husband", "Half full")
    assert scenario.group_edits()[-1] == (
        f"{QUESTION}\n\nYou both picked: Half full. I've put it forward as a household rule "
        "below; a YES locks it in."
    )
    summary = "How full the feeders should be: Half full"
    assert proposals == [
        f"Proposed Rule: {summary}. A YES locks this in, or we keep brainstorming."
    ]
    (item,) = alignments(scenario)
    rule = scenario.app.db.one("SELECT * FROM rules WHERE id = ?", (item["rule_id"],))
    assert rule is not None
    assert item["outcome"] == "agreed" and rule["summary"] == summary
    assert rule["status"] == "draft"
    # the person whose tap settled it locks it in, right there
    await scenario.tap_in_group("Husband", "Lock it in")
    status = scenario.app.db.scalar("SELECT status FROM rules WHERE id = ?", (item["rule_id"],))
    assert status == "locked"


async def test_different_picks_change_nothing(scenario: Scenario) -> None:
    await scenario.link_group()
    await flag(scenario)
    await scenario.tap_in_group("Erin", "To the top")
    await scenario.tap_in_group("Husband", "Half full")
    assert scenario.group_edits()[-1] == (
        f"{QUESTION}\n\nYou picked differently (Erin: To the top; Husband: Half full). "
        "Nothing changes for now; it's yours to talk over whenever suits."
    )
    (item,) = alignments(scenario)
    assert item["outcome"] == "different" and item["rule_id"] is None
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM rules") == 0
    # a late tap on a settled question does nothing
    edits = len(scenario.group_edits())
    await scenario.tap_in_group("Erin", "Half full")
    assert len(scenario.group_edits()) == edits


async def test_a_pause_on_notes_holds_the_question_for_both(scenario: Scenario) -> None:
    await scenario.link_group()
    await scenario.say("Erin", "/pause notes 2h")
    await flag(scenario)
    assert QUESTION not in scenario.group_texts()
    await scenario.advance(hours=2, minutes=1)
    assert scenario.group_texts()[-1] == QUESTION
