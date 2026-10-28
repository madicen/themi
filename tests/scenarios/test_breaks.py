"""B1, Erin's idea #42: a break holds task nudges and check-ins, then asks whether to end it
or extend it. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.core.tasks import TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def dentist_nudges(scenario: Scenario) -> list[str]:
    return [t for t in scenario.inbox("Erin") if "Book the dentist" in t]


async def take_a_break(scenario: Scenario, minutes: int) -> list[str]:
    scenario.primary.queue_tool_call("start_break", {"minutes": minutes})
    scenario.primary.queue_text("Enjoy it.")
    return await scenario.say("Erin", f"I'm taking a break for {minutes} minutes")


async def test_a_break_holds_nudges_then_asks(scenario: Scenario) -> None:
    await take_a_break(scenario, 30)
    erin = scenario.member("Erin")
    await board(scenario).create(erin, "Book the dentist", "errand", 1, date(2026, 10, 21))
    await scenario.advance(minutes=20)
    assert dentist_nudges(scenario) == []  # held while she rests

    sent = await scenario.advance(minutes=11)  # 9:31
    assert "Break's up. Ready to carry on, or a little longer?" in sent
    assert scenario.last_buttons("Erin") == ["End break", "Extend by 15 min"]
    await scenario.tap("Erin", "Extend by 15 min")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Longer it is: no task nudges or check-ins until 9:46 am."
    )
    await scenario.advance(minutes=5)
    assert dentist_nudges(scenario) == []

    await scenario.advance(minutes=11)
    await scenario.tap("Erin", "End break")
    assert scenario.edits("Erin")[-1]["text"] == "Welcome back."
    await scenario.advance(minutes=1)
    assert dentist_nudges(scenario) == ["Due today: Book the dentist. Done already, or later?"]


async def test_back_early_ends_it(scenario: Scenario) -> None:
    await take_a_break(scenario, 60)
    scenario.primary.queue_tool_call("end_break", {})
    scenario.primary.queue_text("Welcome back.")
    await scenario.say("Erin", "I'm back")
    sent = await scenario.advance(hours=2)
    assert not any(t.startswith("Break's up") for t in sent)  # no question for a break over
    assert scenario.app.services.outbox.pauses.active(scenario.member("Erin")) == []


async def test_a_reply_still_comes_during_a_break(scenario: Scenario) -> None:
    await take_a_break(scenario, 30)
    scenario.primary.queue_text("Tuesday.")
    assert await scenario.say("Erin", "When's the vet?") == ["Tuesday."]


async def test_the_command_and_the_extension_setting(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = await site.get("/settings")
    assert 'name="break_extend_minutes"' in page.text
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, break_extend_minutes=25)
    assert csrf
    replies = await scenario.say("Erin", "/break 10")
    assert replies == [
        "Enjoy the break. No task nudges or check-ins until 9:10 am; I'll check in then."
    ]
    await scenario.advance(minutes=11)
    assert scenario.last_buttons("Erin") == ["End break", "Extend by 25 min"]
