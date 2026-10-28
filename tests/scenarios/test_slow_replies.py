"""P2a: replies are timed (ideas #51 and #55), and a slow one gets a word first (Michael's
idea, 2026-10-28). The free Gemini tier has been taking 10 s a call, 49 s at most."""

from __future__ import annotations

from itertools import pairwise

from tests.scenarios.harness import Scenario
from themi.channels.events import Button
from themi.channels.outbox import Priority
from themi.core.timing import SLOW_NOTICES, medians, week_of_replies


def notices(texts: list[str]) -> list[str]:
    return [t for t in texts if t in SLOW_NOTICES]


async def test_a_slow_reply_gets_a_word_first(scenario: Scenario) -> None:
    scenario.primary.take(12).queue_text("The vet is on Tuesday.")
    replies = await scenario.say("Erin", "When's the vet?")
    assert len(replies) == 2
    assert replies[0] in SLOW_NOTICES
    assert replies[1] == "The vet is on Tuesday."


async def test_a_quick_reply_gets_none(scenario: Scenario) -> None:
    scenario.primary.take(9).queue_text("Tuesday.")
    assert await scenario.say("Erin", "When's the vet?") == ["Tuesday."]


async def test_a_reply_ready_just_as_the_word_would_go_gets_none(scenario: Scenario) -> None:
    scenario.primary.take(10).queue_text("Tuesday.")
    assert await scenario.say("Erin", "When's the vet?") == ["Tuesday."]


async def test_one_word_per_reply_however_slow(scenario: Scenario) -> None:
    scenario.primary.take(15).queue_tool_call("list_open_items", {})
    scenario.primary.take(15).queue_text("Nothing open.")
    replies = await scenario.say("Erin", "What's open?")
    assert len(notices(replies)) == 1 and replies[-1] == "Nothing open."


async def test_never_the_same_word_twice_in_a_row(scenario: Scenario) -> None:
    said = []
    for n in range(8):
        scenario.primary.take(11).queue_text(f"Answer {n}.")
        said += notices(await scenario.say("Erin", f"Question {n}?"))
    assert len(said) == 8
    assert all(a != b for a, b in pairwise(said))


async def test_the_word_isnt_counted_against_the_daily_limit(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    for n in range(erin.daily_limit):
        await scenario.app.outbox.send(erin, f"Note {n}", priority=Priority.NORMAL, kind="test")
    before = scenario.app.outbox.sent_today(erin.id)
    scenario.primary.take(12).queue_text("Tuesday.")
    replies = await scenario.say("Erin", "When's the vet?")
    assert len(notices(replies)) == 1
    assert scenario.app.outbox.sent_today(erin.id) == before


async def test_not_for_button_taps(scenario: Scenario) -> None:
    await scenario.app.outbox.send(
        scenario.member("Erin"),
        "Washer's done. Dryer now, or later tonight?",
        priority=Priority.NORMAL,
        buttons=[
            Button("Dryer now", "reply", {"text": "Dryer now"}),
            Button("Later tonight", "reply", {"text": "Later tonight"}),
        ],
    )
    scenario.primary.take(12).queue_text("Later tonight works.")
    assert await scenario.tap("Erin", "Later tonight") == ["Later tonight works."]


async def test_where_the_time_went_is_kept(scenario: Scenario) -> None:
    scenario.primary.take(6).queue_tool_call("list_open_items", {})
    scenario.primary.take(8).queue_text("Nothing open.")
    await scenario.say("Erin", "What's open?")
    scenario.primary.queue_text("Hi!")
    await scenario.say("Husband", "Hello")

    erin, husband = week_of_replies(scenario.app.db)
    assert erin.member_id == scenario.member("Erin").id
    assert (erin.seconds, erin.model_seconds, erin.tool_seconds) == (14.0, 14.0, 0.0)
    assert erin.slow_notice in SLOW_NOTICES
    assert [s.what for s in erin.steps] == ["Model", "Tool list_open_items", "Model", "Outbox"]
    assert husband.seconds == 0.0 and husband.slow_notice is None
    assert medians([erin, husband])["seconds"] == 7.0
