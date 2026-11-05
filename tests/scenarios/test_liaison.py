"""34a: notes passed on between partners. Erin's quiet hours are 21:30-08:00; the clock
starts Wednesday 21 October 2026, 9 am Pacific."""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.scenarios.harness import START, Scenario
from themi import clock
from themi.accounts import SYSTEM, Member
from themi.ai.types import ToolResult
from themi.channels.outbox import Priority


class Until:
    """A receptivity provider: their next good window is at `moment`."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def not_before(self, member: Member, priority: Priority, now: datetime) -> datetime:
        return max(now, self.moment)


def hold_until(scenario: Scenario, moment: datetime) -> None:
    scenario.app.outbox.receptivity = Until(moment)


async def relay(
    scenario: Scenario, name: str, said: str, to: str, message: str, urgency: str
) -> list[str]:
    scenario.primary.queue_tool_call(
        "relay_to_partner", {"to": to, "message": message, "urgency": urgency}
    )
    scenario.primary.queue_text("Okay.")
    return await scenario.say(name, said)


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


def notes(scenario: Scenario) -> list[dict]:
    return scenario.app.db.query("SELECT * FROM liaison_items ORDER BY id")


async def test_an_urgent_note_goes_at_once_even_in_quiet_hours(scenario: Scenario) -> None:
    clock.advance(timedelta(hours=13, minutes=30))  # 10:30 pm: Erin's quiet hours
    replies = await relay(
        scenario,
        "Husband",
        "Tell Erin it's urgent, the basement is flooding",
        "Erin",
        "The basement is flooding.",
        "urgent",
    )
    assert replies == ["Passed on to Erin."]
    assert scenario.inbox("Erin")[-1] == "Urgent, from Husband: The basement is flooding."
    (note,) = notes(scenario)
    assert note["urgency"] == "urgent" and note["delivered_at"] is not None


async def test_a_note_for_today_goes_by_early_evening(scenario: Scenario) -> None:
    hold_until(scenario, START + timedelta(hours=12))  # her next good window: 9 pm
    replies = await relay(
        scenario,
        "Husband",
        "Let Erin know I'll be home late tonight",
        "Erin",
        "I'll be home late tonight.",
        "today",
    )
    assert replies == ["I'll pass that on to Erin at a good moment today, by 6 pm at the latest."]
    before = len(scenario.inbox("Erin"))
    await scenario.advance(hours=8, minutes=59)  # 5:59 pm
    assert len(scenario.inbox("Erin")) == before
    await scenario.advance(minutes=1)
    assert scenario.inbox("Erin")[before:] == ["From Husband: I'll be home late tonight."]


async def test_a_note_for_whenever_waits_for_their_next_good_window(scenario: Scenario) -> None:
    hold_until(scenario, START + timedelta(hours=5))  # 2 pm
    replies = await relay(
        scenario,
        "Husband",
        "Ask Erin if she wants takeout tonight",
        "Erin",
        "Do you want takeout tonight?",
        "whenever",
    )
    assert replies == [
        "I'll pass that on to Erin at a good moment for them (likely today around 2 pm)."
    ]
    husband = scenario.member("Husband")
    waiting = [i.summary for i in scenario.app.services.open_items(husband)]
    assert "A note for Erin, not passed on yet: Do you want takeout tonight?" in waiting
    before = len(scenario.inbox("Erin"))
    await scenario.advance(hours=4, minutes=59)
    assert len(scenario.inbox("Erin")) == before
    await scenario.advance(minutes=1)
    assert scenario.inbox("Erin")[before:] == ["From Husband: Do you want takeout tonight?"]
    assert notes(scenario)[0]["delivered_at"] is not None
    waiting = [i.summary for i in scenario.app.services.open_items(husband)]
    assert not any(s.startswith("A note for Erin") for s in waiting)


async def test_the_note_is_shielded_with_the_recipients_settings(scenario: Scenario) -> None:
    hold_until(scenario, START)
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    scenario.app.store.update_settings(SYSTEM, husband.id, pda_enabled=False)
    # Erin has PDA shielding on: the demand is rewritten for her.
    scenario.primary.queue_tool_call(
        "relay_to_partner",
        {"to": "Erin", "message": "You need to call the vet back.", "urgency": "whenever"},
    )
    scenario.primary.queue_structured(
        {"text": "From Husband: the vet would like a call back.", "options": []}
    )
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "Tell Erin she needs to call the vet back")
    assert scenario.inbox("Erin")[-1] == "From Husband: the vet would like a call back."
    # Her husband has it off: the same words reach him as they were written.
    await relay(
        scenario,
        "Erin",
        "Tell him he needs to call the vet back",
        "partner",
        "You need to call the vet back.",
        "whenever",
    )
    assert scenario.inbox("Husband")[-1] == "From Erin: You need to call the vet back."
    assert erin.pda_enabled


async def test_a_nickname_the_notes_explain_finds_them(scenario: Scenario) -> None:
    """Found reading the reports of 2026-10-27: "can you tell Hundo 'I Wuv U'?" was saved as
    a note and answered "I've saved that for her"."""
    hold_until(scenario, START)
    memory = scenario.app.services.memory
    assert memory is not None
    memory.remember(
        scenario.member("Husband"), "nickname", 'Husband calls Erin "Hundo".', scope="family"
    )
    replies = await relay(
        scenario, "Husband", "Can you tell Hundo “I Wuv U ❤️”?", "Hundo", "I Wuv U ❤️", "whenever"
    )
    assert replies == ["Passed on to Erin."]
    assert scenario.inbox("Erin")[-1] == "From Husband: I Wuv U ❤️"
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM facts") == 1  # only the nickname


async def test_someone_outside_the_family_isnt_the_partner(scenario: Scenario) -> None:
    before = len(scenario.inbox("Erin"))
    await relay(
        scenario, "Husband", "Tell Mom I'll call her Sunday", "Mom", "I'll call Sunday.", "whenever"
    )
    assert "only passes notes between the family (Erin)" in tool_result(scenario)
    assert notes(scenario) == []
    assert len(scenario.inbox("Erin")) == before


async def test_nothing_is_passed_on_unless_they_asked(scenario: Scenario) -> None:
    before = len(scenario.inbox("Erin"))
    await relay(scenario, "Husband", "The vet called", "Erin", "The vet called.", "whenever")
    assert "doesn't ask Themi to pass anything on" in tool_result(scenario)
    assert notes(scenario) == []
    assert len(scenario.inbox("Erin")) == before


async def test_the_same_note_isnt_sent_twice(scenario: Scenario) -> None:
    hold_until(scenario, START)
    said = "Let Erin know the dog's been fed"
    await relay(scenario, "Husband", said, "Erin", "The dog's been fed.", "whenever")
    await relay(scenario, "Husband", said, "Erin", "The dog's been fed.", "whenever")
    assert "already went; it wasn't sent twice" in tool_result(scenario)
    assert scenario.inbox("Erin").count("From Husband: The dog's been fed.") == 1
