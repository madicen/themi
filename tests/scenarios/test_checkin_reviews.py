"""Idea #13: now and then, Themi asks whether a check-in is helping."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.core.habits import HabitReserve
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

ASK = 'Check-in review: is "Go for a run" helping?'


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def run_check_in(scenario: Scenario) -> Task:
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(task.id, erin, repeat=parse("every day", scenario.today()))
    await scenario.run_periodic("checkins.reviews")  # counting starts here
    return task


async def check_ins(scenario: Scenario, task: Task, times: int) -> None:
    for _ in range(times):
        await board(scenario).complete(task.id, scenario.member("Erin"))
        await scenario.run_periodic("checkins.reviews")
        await scenario.app.outbox.flush()


def asks(scenario: Scenario) -> list[str]:
    rows = scenario.app.db.query("SELECT text FROM outbox WHERE kind = 'review' ORDER BY id")
    return [r["text"] for r in rows]


async def tap_edited(scenario: Scenario, name: str, label: str) -> None:
    edit = scenario.edits(name)[-1]
    (token,) = [
        b["callback_data"]
        for b in (b for row in edit["reply_markup"]["inline_keyboard"] for b in row)
        if b["text"] == label
    ]
    chat = scenario.member(name).telegram_user_id
    assert chat is not None
    scenario.telegram.tap(chat, token, int(edit["message_id"]))
    await scenario.app.channel.poll_once()


async def test_asks_after_four_then_less_often_then_stops(scenario: Scenario) -> None:
    run = await run_check_in(scenario)
    await check_ins(scenario, run, 3)
    assert asks(scenario) == []
    await check_ins(scenario, run, 1)
    assert asks(scenario) == [ASK]
    assert scenario.last_buttons("Erin") == [
        "Helpful",
        "Not really",
        "Let's talk later",
        "Stop asking",
    ]
    await scenario.tap("Erin", "Helpful")
    assert scenario.edits("Erin")[-1]["text"] == "Good to hear. I'll ask again in a while."

    await check_ins(scenario, run, 7)
    assert len(asks(scenario)) == 1  # twice as long now
    await check_ins(scenario, run, 1)
    assert len(asks(scenario)) == 2
    await scenario.tap("Erin", "Helpful")
    await check_ins(scenario, run, 16)
    assert len(asks(scenario)) == 3
    await scenario.tap("Erin", "Helpful")
    assert "won't ask about it again" in scenario.edits("Erin")[-1]["text"]
    await check_ins(scenario, run, 40)
    assert len(asks(scenario)) == 3


async def test_later_keeps_the_interval(scenario: Scenario) -> None:
    run = await run_check_in(scenario)
    await check_ins(scenario, run, 4)
    await scenario.tap("Erin", "Let's talk later")
    await check_ins(scenario, run, 3)
    assert len(asks(scenario)) == 1
    await check_ins(scenario, run, 1)
    assert len(asks(scenario)) == 2


async def test_not_really_offers_to_stop_it(scenario: Scenario) -> None:
    run = await run_check_in(scenario)
    await check_ins(scenario, run, 4)
    await scenario.tap("Erin", "Not really")
    assert scenario.edits("Erin")[-1]["text"] == (
        'Thanks for saying. Stop "Go for a run", or keep it as it is?'
    )
    await tap_edited(scenario, "Erin", "Stop it")
    assert board(scenario).get(run.id).status == "cancelled"


async def test_stop_asking_for_one_or_for_all(scenario: Scenario) -> None:
    run = await run_check_in(scenario)
    await check_ins(scenario, run, 4)
    await scenario.tap("Erin", "Stop asking")
    await check_ins(scenario, run, 20)
    assert len(asks(scenario)) == 1

    scenario.primary.queue_tool_call(
        "set_check_in_reviews", {"check_in": "", "after": 0, "stop_asking": True}
    )
    scenario.primary.queue_text("No more check-in reviews.")
    await scenario.say("Erin", "please stop asking whether check-ins help")
    assert not scenario.member("Erin").checkin_reviews


async def test_a_check_in_can_ask_sooner_and_habits_count(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    HabitReserve(scenario.app.services).seed(erin)
    scenario.app.db.execute(
        "UPDATE habits SET status = 'active' WHERE member_id = ? AND idea LIKE '%water%'",
        (erin.id,),
    )
    await scenario.run_periodic("checkins.reviews")
    scenario.primary.queue_tool_call(
        "set_check_in_reviews", {"check_in": "water", "after": 2, "stop_asking": False}
    )
    scenario.primary.queue_text("I'll ask after two.")
    await scenario.say("Erin", "ask me about the water one after two check-ins")
    for _ in range(2):
        await scenario.advance(hours=24)
        await scenario.run_periodic("habits.send")
        scenario.app.db.execute("UPDATE habits SET last_outbox_id = NULL")  # answered, say
    await scenario.run_periodic("checkins.reviews")
    assert asks(scenario) == ['Check-in review: is "A glass of water mid-morning" helping?']
