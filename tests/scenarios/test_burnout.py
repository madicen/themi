"""F22d, Erin's ideas #33, #122 and #123: burnout mode. Everything held, no demands, the
time-sensitive things to her partner, and on until she says. The clock starts on Wednesday
21 October 2026 at 09:00, Pacific time."""

from __future__ import annotations

from datetime import time, timedelta

import pytest

from tests.scenarios.harness import Scenario
from tests.scenarios.test_focus import WED, board, task, tool_result, turn
from themi.channels.outbox import Priority
from themi.core.burnout import ENDED_TEXT, HANDED_TEXT, LIGHTEST_TEXT, SIGNAL, STARTED_TEXTS
from themi.core.focus import SIGNAL as FOCUS_SIGNAL
from themi.core.habits import HabitReserve


async def turn_on(scenario: Scenario, said: str = "Can you put me in burnout mode?") -> list[str]:
    scenario.primary.queue_tool_call("start_burnout", {})
    # What the model said on 2026-11-02, 8:18 am: a demand at the end.
    scenario.primary.queue_text("I understand. Resting is an option. Which sounds better?")
    return await scenario.say("Erin", said)


async def test_the_first_reply_has_nothing_to_do(scenario: Scenario) -> None:
    (reply,) = await turn_on(scenario)
    assert reply in STARTED_TEXTS
    assert "?" not in reply


async def test_task_nudges_wait_until_it_ends(scenario: Scenario) -> None:
    await turn_on(scenario)
    erin = scenario.member("Erin")
    await board(scenario).create(erin, "Sort the mail", "errand", 1, WED, assignee=erin)
    sent = await scenario.advance(hours=3)
    assert not any("Sort the mail" in t for t in sent)

    scenario.primary.queue_tool_call("end_burnout", {})
    scenario.primary.queue_text("Welcome back! Want to look at your list?")
    assert await scenario.say("Erin", "I'm out of burnout mode") == [ENDED_TEXT]
    sent = await scenario.advance(minutes=1)
    assert any("Sort the mail" in t for t in sent)  # held, never dropped


async def test_time_sensitive_things_go_to_her_partner_and_come_back(
    scenario: Scenario,
) -> None:
    vet = await task(scenario, "Erin", "Call the vet", due_time=time(14))
    bill = await task(scenario, "Erin", "Pay the water bill", importance="high")
    mail = await task(scenario, "Erin", "Sort the mail")  # can wait
    await turn_on(scenario)
    husband = scenario.member("Husband")
    assert board(scenario).get(vet.id).assignee == husband.id
    assert board(scenario).get(bill.id).assignee == husband.id
    assert board(scenario).get(mail.id).assignee == scenario.member("Erin").id
    await scenario.advance(hours=5, minutes=1)  # 14:01
    (nudge,) = [t for t in scenario.inbox("Husband") if "Call the vet" in t]
    assert HANDED_TEXT.format(name="Erin") in nudge  # why it's his (Michael, 2026-11-02)
    assert "burnout" not in nudge.lower() and "added this for you" not in nudge

    await board(scenario).complete(bill.id, husband)
    scenario.primary.queue_tool_call("end_burnout", {})
    scenario.primary.queue_text("")
    await scenario.say("Erin", "turn burnout mode off")
    erin = scenario.member("Erin")
    assert board(scenario).get(vet.id).assignee == erin.id  # still open: back to her
    assert board(scenario).get(bill.id).status == "done"


async def test_ones_due_later_are_handed_on_when_their_day_comes(scenario: Scenario) -> None:
    dentist = await task(
        scenario, "Erin", "Ring the dentist", WED + timedelta(days=1), due_time=time(10)
    )
    await turn_on(scenario)
    assert board(scenario).get(dentist.id).assignee == scenario.member("Erin").id
    await scenario.advance(hours=24)
    await scenario.run_periodic("burnout.hand_over")
    assert board(scenario).get(dentist.id).assignee == scenario.member("Husband").id


async def test_only_she_can_turn_it_on(scenario: Scenario) -> None:
    """F22a's case: Michael asking for Erin."""
    scenario.primary.queue_tool_call("start_burnout", {})
    scenario.primary.queue_text("Only Erin can turn that on.")
    await scenario.say("Husband", "Can you put Erin in burnout mode?")
    assert scenario.app.services.burnout is not None
    assert scenario.app.services.burnout.current(scenario.member("Erin")) is None
    assert scenario.app.services.burnout.current(scenario.member("Husband")) is None


async def test_asked_for_something_to_do_the_single_lightest(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Deep clean the oven", effort=3)
    await task(scenario, "Erin", "Water the plants", effort=1)
    await task(scenario, "Erin", "Sort the mail", effort=2)
    await turn_on(scenario)
    scenario.primary.queue_tool_call("burnout_task", {})
    scenario.primary.queue_text("You could also try the oven!")
    assert await scenario.say("Erin", "Give me one thing I could do") == [
        "If you'd like one thing: Water the plants. Nothing at all is fine too."
    ]


async def test_while_on_each_turn_says_so_and_offers_no_paring_down(scenario: Scenario) -> None:
    await turn_on(scenario)
    scenario.primary.queue_text("It's all handled.")
    await scenario.say("Erin", "I feel so burnt out and everything is falling apart")
    context = str(scenario.primary.requests[-1].messages[0].content[0])
    assert SIGNAL in context and FOCUS_SIGNAL not in context


async def test_no_signal_when_its_off(scenario: Scenario) -> None:
    scenario.primary.queue_text("Hi.")
    await scenario.say("Erin", "hi")
    assert SIGNAL not in turn(scenario)


async def test_the_command(scenario: Scenario) -> None:
    (on,) = await scenario.say("Erin", "/burnout")
    assert on in STARTED_TEXTS
    assert await scenario.say("Erin", "/burnout") == [
        "Burnout mode is still on. Everything's handled."
    ]
    assert await scenario.say("Erin", "/burnout off") == [ENDED_TEXT]
    assert await scenario.say("Erin", "/burnout off") == ["Burnout mode isn't on."]


@pytest.mark.parametrize(
    "text", [*STARTED_TEXTS, ENDED_TEXT, LIGHTEST_TEXT.format(title="Water the plants")]
)
async def test_the_shield_leaves_its_words_alone(scenario: Scenario, text: str) -> None:
    await scenario.app.services.outbox.send(scenario.member("Erin"), text, priority=Priority.REPLY)
    assert scenario.inbox("Erin")[-1] == text


# ----- check-ins: kept, in their burnout words, or only then ------------------------------


def water(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    HabitReserve(scenario.app.services).seed(erin)
    scenario.app.db.execute(
        "UPDATE habits SET status = 'active' WHERE member_id = ? AND idea LIKE '%water%'",
        (erin.id,),
    )


async def check_in_today(scenario: Scenario) -> list[str]:
    scenario.app.db.execute("UPDATE habits SET last_outbox_id = NULL")  # answered, say
    before = len(scenario.inbox("Erin"))
    await scenario.run_periodic("habits.send")
    for _ in range(30):  # a check-in waits for a good moment
        queued = scenario.app.db.scalar(
            "SELECT COUNT(*) FROM outbox WHERE status = 'queued' AND kind IN ('habit', 'selfcare')"
        )
        if not queued:
            break
        await scenario.advance(hours=1)
    return [t for t in scenario.inbox("Erin")[before:] if t.startswith("Check-in:")]


async def keep(scenario: Scenario, check_in: str, mode: str, words: str = "") -> list[str]:
    scenario.primary.queue_tool_call(
        "set_burnout_check_in", {"check_in": check_in, "mode": mode, "words": words}
    )
    scenario.primary.queue_text("Sure! Anything else you'd like?")
    return await scenario.say("Erin", f"in burnout mode, {mode} the {check_in} check-in")


async def test_check_ins_are_held_unless_kept(scenario: Scenario) -> None:
    water(scenario)
    await turn_on(scenario)
    assert await check_in_today(scenario) == []
    assert await keep(scenario, "water", "keep", "Water?") == [
        'In burnout mode, "a glass of water mid-morning" still comes as "Water?".'
    ]
    await scenario.advance(hours=24)
    assert await check_in_today(scenario) == ["Check-in: Water?"]


async def test_ignored_in_burnout_mode_never_retires_a_kept_one(scenario: Scenario) -> None:
    water(scenario)
    await keep(scenario, "water", "keep")
    await turn_on(scenario)
    for _ in range(5):  # never answered
        await scenario.advance(hours=24)
        await scenario.run_periodic("habits.send")
    status = scenario.app.db.scalar("SELECT status FROM habits WHERE idea LIKE '%water%'")
    assert status == "active"


async def test_a_burnout_only_check_in_waits_for_a_yes_and_comes_only_then(
    scenario: Scenario,
) -> None:
    replies = await keep(scenario, "a grounding minute", "only", "Feet on the floor?")
    assert replies[0] == (
        "A check-in just for burnout mode: a grounding minute\nGo ahead, or not now?"
    )
    await scenario.tap("Erin", "Go ahead")
    await scenario.advance(hours=24)
    assert await check_in_today(scenario) == []  # not in burnout mode
    await turn_on(scenario)
    await scenario.advance(hours=24)
    assert await check_in_today(scenario) == ["Check-in: Feet on the floor?"]

    scenario.primary.queue_tool_call("end_burnout", {})
    scenario.primary.queue_text("")
    await scenario.say("Erin", "I'm out of burnout mode")
    await scenario.advance(hours=24)
    assert await check_in_today(scenario) == []


async def test_a_new_everyday_check_in_isnt_made_here(scenario: Scenario) -> None:
    await keep(scenario, "stretching", "keep")
    assert "only a burnout-only one" in tool_result(scenario)
