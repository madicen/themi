"""The habit reserve: when an offer is made, and how an ignored habit retires itself."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import pytest

from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts import SYSTEM, Member
from themi.autonomy import Decision
from themi.channels.events import InboundEvent
from themi.channels.outbox import Priority
from themi.channels.pda import find_demands
from themi.core.habits import IDEAS, HabitReserve


@pytest.fixture
def erin(scenario: Scenario) -> Member:
    # With no energy read, nothing waits for a window, so timing stays simple here.
    return scenario.app.store.update_settings(
        SYSTEM,
        scenario.member("Erin").id,
        tracking={"text_notes": False, "message_timing": False, "device_activity": False},
    )


@pytest.fixture
def reserve(scenario: Scenario) -> HabitReserve:
    habits = scenario.app.services.habits
    assert habits is not None
    return habits


async def answer_prompts(scenario: Scenario, member: Member, replies: Sequence[str]) -> None:
    """Themi nudges `member` once per reply, and they answer each one like this."""
    outcomes = scenario.app.services.outcomes
    assert outcomes is not None
    for words in replies:
        await scenario.app.outbox.send(
            member, "Washer's done, if it's handy.", priority=Priority.NORMAL, kind="laundry"
        )
        event = InboundEvent(
            "text", member, member.telegram_user_id or 0, 1, clock.now(), 1, text=words
        )
        outcomes.observe(member, event)


def statuses(reserve: HabitReserve, member: Member) -> list[str]:
    return [h["status"] for h in reserve.habits(member)]


async def test_no_offer_without_enough_to_go_on(
    scenario: Scenario, erin: Member, reserve: HabitReserve
) -> None:
    await answer_prompts(scenario, erin, ["ok", "done"])
    assert await reserve.offer_due() == 0
    assert set(statuses(reserve, erin)) == {"reserve"}


async def test_no_offer_when_prompts_are_mostly_set_aside(
    scenario: Scenario, erin: Member, reserve: HabitReserve
) -> None:
    await answer_prompts(scenario, erin, ["ok", "not now", "not now", "ok", "not now"])
    assert await reserve.offer_due() == 0


async def test_one_offer_at_a_time_and_at_most_every_two_weeks(
    scenario: Scenario, erin: Member, reserve: HabitReserve
) -> None:
    await answer_prompts(scenario, erin, ["ok", "done", "sure", "ok", "thanks"])
    assert await reserve.offer_due() == 1
    habit = reserve.habits(erin)[0]
    assert habit["status"] == "offered"
    action = scenario.app.services.autonomy.action(habit["action_id"])
    assert (action.category, action.status) == ("habit_trial", "pending")
    assert habit["idea"] in scenario.inbox("Erin")[-1]  # the approval request

    assert await reserve.offer_due() == 0  # an offer is already open
    await scenario.app.services.autonomy.resolve(action.id, Decision.DECLINE, by=erin)
    clock.advance(timedelta(days=13))
    await answer_prompts(scenario, erin, ["ok", "done", "sure", "ok", "thanks"])
    assert await reserve.offer_due() == 0  # declined, and too soon for another
    assert statuses(reserve, erin)[0] == "declined"

    clock.advance(timedelta(days=1, hours=1))
    assert await reserve.offer_due() == 1
    assert statuses(reserve, erin)[:2] == ["declined", "offered"]  # never the declined one again


async def test_an_ignored_habit_retires_quietly(
    scenario: Scenario, erin: Member, reserve: HabitReserve
) -> None:
    await answer_prompts(scenario, erin, ["ok", "done", "sure", "ok", "thanks"])
    await reserve.offer_due()
    habit = reserve.habits(erin)[0]
    await scenario.app.services.autonomy.resolve(habit["action_id"], Decision.APPROVE, by=erin)
    assert statuses(reserve, erin)[0] == "active"

    outcomes = scenario.app.services.outcomes
    assert outcomes is not None
    sent = []
    clock.advance(timedelta(days=1))  # 09:00 the next day
    for _ in range(4):
        before = len(scenario.inbox("Erin"))
        await reserve.send_due()
        assert await reserve.send_due() == 0  # once a day at most
        sent.append(scenario.inbox("Erin")[before:])
        clock.advance(timedelta(hours=13))
        outcomes.expire()  # nobody answered
        clock.advance(timedelta(hours=11))

    plain = f"Check-in: {habit['idea'][:1].upper()}{habit['idea'][1:]}."  # idea #12: plain
    assert sent[:3] == [[plain]] * 3  # Erin's rules 7 and 8, built in
    assert sent[3] == []  # retired, and nothing was said about it
    assert statuses(reserve, erin)[0] == "retired"


async def test_answering_keeps_a_habit_going(
    scenario: Scenario, erin: Member, reserve: HabitReserve
) -> None:
    await answer_prompts(scenario, erin, ["ok", "done", "sure", "ok", "thanks"])
    await reserve.offer_due()
    habit = reserve.habits(erin)[0]
    await scenario.app.services.autonomy.resolve(habit["action_id"], Decision.APPROVE, by=erin)
    outcomes = scenario.app.services.outcomes
    assert outcomes is not None
    clock.advance(timedelta(days=1))
    for day in range(5):
        assert await reserve.send_due() == 1
        if day % 2:
            outcomes.observe(
                erin, InboundEvent("text", erin, 1001, 1, clock.now(), 1, text="done, thanks")
            )
        clock.advance(timedelta(hours=13))
        outcomes.expire()  # the unanswered ones count as ignored
        clock.advance(timedelta(hours=11))
    assert statuses(reserve, erin)[0] == "active"


@pytest.mark.parametrize(("idea", "prompt"), IDEAS)
def test_habit_texts_are_never_demands(idea: str, prompt: str) -> None:
    assert find_demands(prompt, strength=3) == []
    assert find_demands(f"A small daily check-in to try: {idea}", strength=3) == []
