"""C3: the wall's routines: morning and evening checks, ticking from Telegram, and Themi's
check-ins as routines. The clock starts on Wednesday 21 October 2026, 09:00; Erin's quiet
hours start at 21:30, her husband's at 23:00."""

from __future__ import annotations

from datetime import date, timedelta

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.repeat import parse
from themi.core.tasks import TaskBoard

WED = date(2026, 10, 21)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> None:
    target = clock.now().replace(
        year=day.year, month=day.month, day=day.day, hour=hour, minute=minute
    )
    clock.advance(target - clock.now())
    await scenario.run_periodic("cozyla.routines")
    await scenario.app.outbox.flush()


def routine_texts(scenario: Scenario, name: str) -> list[str]:
    """Routine checks for `name`, sent or waiting for a good moment."""
    rows = scenario.app.db.query(
        "SELECT text FROM outbox WHERE member_id = ? AND kind = 'routine' ORDER BY id",
        (scenario.member(name).id,),
    )
    return [r["text"] for r in rows]


async def tap_edited(scenario: Scenario, name: str, label: str) -> None:
    """Tap a button on the latest edit of a message (scenario.tap sees sent ones only)."""
    edit = scenario.edits(name)[-1]
    (token,) = [
        b["callback_data"] for b in edit["reply_markup"]["inline_keyboard"][0] if b["text"] == label
    ]
    chat = scenario.member(name).telegram_user_id
    assert chat is not None
    scenario.telegram.tap(chat, token, int(edit["message_id"]))
    await scenario.app.channel.poll_once()


def signals(scenario: Scenario, name: str) -> list[tuple[float, str]]:
    rows = scenario.app.db.query(
        "SELECT value, note FROM energy_signals WHERE member_id = ? AND source = 'device_activity'",
        (scenario.member(name).id,),
    )
    return [(r["value"], r["note"]) for r in rows]


async def test_the_morning_check_lists_whats_open_and_ticks_from_a_button(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    walk = fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    fake_cozyla.add_routine("m-erin", "Make the bed", "Morning")
    fake_cozyla.add_routine("m-erin", "Cycle dishwasher", "Evening")
    await at(scenario, WED, 11, 59)
    assert routine_texts(scenario, "Erin") == []
    await at(scenario, WED, 12, 1)
    assert routine_texts(scenario, "Erin") == [
        "Morning routine: Walk dog and Make the bed still open. Done already?"
    ]
    assert scenario.last_buttons("Erin") == ["✓ Walk dog", "✓ Make the bed"]
    assert signals(scenario, "Erin") == [
        (-0.5, "morning routine not finished (Walk dog and Make the bed)")
    ]
    await at(scenario, WED, 13, 0)
    assert len(routine_texts(scenario, "Erin")) == 1  # once

    await scenario.tap("Erin", "✓ Walk dog")
    assert (walk, WED.isoformat()) in fake_cozyla.routine_ticks
    assert scenario.edits("Erin")[-1]["text"] == (
        "Morning routine: Make the bed still open. Done already?"
    )
    await tap_edited(scenario, "Erin", "✓ Make the bed")
    assert scenario.edits("Erin")[-1]["text"] == "Morning routine: all done."


async def test_nothing_is_sent_when_its_all_done(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    pills = fake_cozyla.add_routine("m-husband", "Take meds", "Evening")
    fake_cozyla.tick_routine(pills, WED)
    await at(scenario, WED, 22, 1)
    assert routine_texts(scenario, "Husband") == []
    assert signals(scenario, "Husband") == [(0.5, "evening routine done")]


async def test_the_evening_check_comes_an_hour_before_quiet_hours(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    fake_cozyla.add_routine("m-husband", "Cycle dishwasher", "Evening")
    await at(scenario, WED, 21, 59)
    assert routine_texts(scenario, "Husband") == []
    await at(scenario, WED, 22, 1)
    assert routine_texts(scenario, "Husband") == [
        "Evening routine: Cycle dishwasher still open. Done already?"
    ]


async def test_themis_check_ins_are_routines_on_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(
        run.id, erin, repeat=parse("every Tue, Thu and Sat afternoon", WED)
    )
    await scenario.run_periodic("cozyla.chores")
    await at(scenario, WED, 9, 30)
    routine = fake_cozyla.routine_named("Go for a run")
    assert (routine["memberUid"], routine["routineType"]) == ("m-erin", "Afternoon")
    assert (routine["repeatsEvery"], routine["repeatsIn"]) == (
        "Weekly",
        "Tuesday,Thursday,Saturday",
    )
    assert not any(c["choreName"] == "Go for a run" for c in fake_cozyla.chores.values())

    routine["routineTitle"] = "Run!!"  # changed on the wall: put back
    await at(scenario, WED, 9, 45)
    assert fake_cozyla.routines[routine["id"]]["routineTitle"] == "Go for a run"

    thursday = WED + timedelta(days=1)
    fake_cozyla.tick_routine(routine["id"], thursday)  # Erin ticks it on the wall on Thursday
    await at(scenario, thursday, 16)
    assert board(scenario).get(run.id).due_on == date(2026, 10, 24)  # Saturday's next
    await board(scenario).complete(run.id, erin)  # Saturday's, done in Themi
    await at(scenario, thursday, 16, 15)
    assert (routine["id"], "2026-10-24") in fake_cozyla.routine_ticks
    await at(scenario, thursday, 17)
    assert routine_texts(scenario, "Erin") == []  # Themi nudges for its own check-ins
