"""CK13, Michael's bug #192: while a session page is open (it asked for its state in the
last 2 minutes), Themi's lines go to the page only. The chat card is still edited in place.
A timer's "Time's up" still goes to Telegram, and a body double check-in nobody answered on
the page goes to chat once the page goes quiet. The clock starts Wednesday 21 October 2026,
9 am."""

from __future__ import annotations

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_company import start, tap
from themi.core import keys
from themi_home.body_double import BodyDouble
from themi_home.cooking import Cooking

STILL_RUNNING = "There's a timer still running. Keep it going?"


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def to_the_steps(scenario: Scenario, cooking: Cooking) -> int:
    session_id = await start(scenario, cooking)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await tap(cooking, scenario, session_id, action)
    await tap(cooking, scenario, session_id, "goto", to="3")
    return session_id


async def test_boundary_lines_stay_on_the_open_screen(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking)
    cooking.seen(erin)
    sent, edited = len(scenario.inbox("Erin")), len(scenario.edits("Erin"))
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")
    assert cooking.state(erin)["line"] == "Gathering first. Tap each one as it's out."
    assert len(scenario.inbox("Erin")) == sent  # nothing new in chat
    assert len(scenario.edits("Erin")) > edited  # the card is edited in place


async def test_whats_after_this_on_the_page_is_answered_there(
    scenario: Scenario, cooking: Cooking
) -> None:
    erin = scenario.member("Erin")
    session_id = await to_the_steps(scenario, cooking)
    await tap(cooking, scenario, session_id, "goto", to="1")  # step 3 is the last
    cooking.seen(erin)
    sent = len(scenario.inbox("Erin"))
    event = cooking.page_chat_event(erin, "what's after this?")
    assert event is not None and event.from_page
    assert await cooking.on_text(event, erin, "what's after this?")
    assert cooking.state(erin)["line"].startswith("After this, step ")
    assert len(scenario.inbox("Erin")) == sent

    # Asked in Telegram, it's answered in Telegram, page open or not.
    await scenario.say("Erin", "what's after this?")
    assert scenario.inbox("Erin")[-1].startswith("After this, step ")


async def test_next_typed_on_the_page_edits_the_card(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    await to_the_steps(scenario, cooking)
    cooking.seen(erin)
    sent, edited = len(scenario.inbox("Erin")), len(scenario.edits("Erin"))
    event = cooking.page_chat_event(erin, "next")
    assert event is not None
    assert await cooking.on_text(event, erin, "next")
    assert len(scenario.inbox("Erin")) == sent  # no fresh card
    assert len(scenario.edits("Erin")) == edited + 1


async def test_times_up_still_goes_to_telegram(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await to_the_steps(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="1", step="3")
    cooking.seen(erin)
    await scenario.advance(minutes=1)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1].startswith("Time's up: ")


async def test_the_open_screen_asks_about_timers_itself(
    scenario: Scenario, cooking: Cooking
) -> None:
    erin = scenario.member("Erin")
    session_id = await to_the_steps(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    cooking.seen(erin)
    await tap(cooking, scenario, session_id, "finish")
    assert STILL_RUNNING not in scenario.inbox("Erin")
    assert cooking.state(erin)["ask_timers"]  # on the screen instead


async def test_with_the_screen_closed_chat_asks_about_timers(
    scenario: Scenario, cooking: Cooking
) -> None:
    session_id = await to_the_steps(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    await scenario.advance(minutes=3)  # no state asked for: closed
    await tap(cooking, scenario, session_id, "finish")
    assert scenario.inbox("Erin")[-1] == STILL_RUNNING


def body_double(scenario: Scenario) -> BodyDouble:
    found = scenario.app.services.maybe(keys.body_double)
    assert found is not None
    return found


async def test_a_sprint_with_the_page_open_then_closed(scenario: Scenario) -> None:
    """The plan's scenario: the block ends with the page open, nothing reaches chat; the page
    closes, and the check-in arrives."""
    erin = scenario.member("Erin")
    bd = body_double(scenario)
    await scenario.say("Erin", "/bodydouble sprint")
    sent = len(scenario.inbox("Erin"))
    await scenario.advance(minutes=24)
    bd.seen(erin)
    await scenario.advance(minutes=1)
    bd.seen(erin)
    await scenario.run_jobs()
    assert len(scenario.inbox("Erin")) == sent  # the block ended: on the page only
    assert bd.state(erin)["line"] == "That's 25 minutes. Break for 5?"
    await scenario.advance(minutes=1)
    bd.seen(erin)  # still open
    await scenario.advance(minutes=2)
    await scenario.run_jobs()
    assert len(scenario.inbox("Erin")) == sent
    await scenario.advance(minutes=2)  # the page went quiet more than 2 minutes ago
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's 25 minutes. Break for 5?"
    assert scenario.last_buttons("Erin") == ["Break", "Keep going", "Stop here"]


async def test_a_check_in_answered_on_the_page_never_reaches_chat(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    bd = body_double(scenario)
    await scenario.say("Erin", "/bodydouble sprint")
    sent = len(scenario.inbox("Erin"))
    await scenario.advance(minutes=25)
    bd.seen(erin)
    await scenario.run_jobs()
    session = bd.current(erin)
    assert session is not None and session.phase == "asking"
    await bd.act(session, "break")
    await scenario.advance(minutes=4)
    await scenario.run_jobs()
    assert len(scenario.inbox("Erin")) == sent


async def test_with_the_page_closed_the_check_in_comes_as_before(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble sprint")
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's 25 minutes. Break for 5?"


async def test_a_timer_phrase_on_the_page_is_answered_there(
    scenario: Scenario, cooking: Cooking
) -> None:
    erin = scenario.member("Erin")
    session_id = await to_the_steps(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    cooking.seen(erin)
    sent = len(scenario.inbox("Erin"))
    event = cooking.page_chat_event(erin, "cancel the timer")
    assert event is not None and cooking.timers is not None
    assert await cooking.timers.on_text(event, erin, "cancel the timer")
    assert cooking.state(erin)["line"] == "Timer cancelled."
    assert len(scenario.inbox("Erin")) == sent
