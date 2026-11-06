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
    # R1b: the wall's routines are Themi's now, and Themi checks them.
    await scenario.run_periodic("routines.wall")
    await scenario.run_periodic("routines.check")
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
        b["callback_data"]
        for b in (b for row in edit["reply_markup"]["inline_keyboard"] for b in row)
        if b["text"] == label
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
        "Morning routine, still open:\n- Walk dog\n- Make the bed\nDone already?"
    ]
    assert scenario.last_buttons("Erin") == ["✓ Walk dog", "✓ Make the bed", "Skip today"]
    assert signals(scenario, "Erin") == [
        (-0.5, "morning routine not finished (Walk dog and Make the bed)")
    ]
    await at(scenario, WED, 13, 0)
    assert len(routine_texts(scenario, "Erin")) == 1  # once

    await scenario.tap("Erin", "✓ Walk dog")
    assert (walk, WED.isoformat()) in fake_cozyla.routine_ticks
    assert scenario.edits("Erin")[-1]["text"].endswith(  # after a warm word (F19b)
        "\n\nMorning routine, still open:\n- Make the bed\nDone already?"
    )
    await tap_edited(scenario, "Erin", "✓ Make the bed")
    assert scenario.edits("Erin")[-1]["text"].endswith(" Morning routine: all done.")


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
        "Evening routine, still open:\n- Cycle dishwasher\nDone already?"
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


# ----- bug #22: items added to a routine ----------------------------------------------------


async def add(scenario: Scenario, said: str, args: dict[str, str | int]) -> list[str]:
    scenario.primary.queue_tool_call(
        "add_to_wall_routine", {"position": "end", "task_id": 0, **args}
    )
    scenario.primary.queue_text("Done.")
    return await scenario.say("Erin", said)


async def test_an_item_for_tonight_goes_on_the_evening_routine_and_off_tomorrow(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #22: it went to the calendar, then the chore chart, then a new list."""
    await at(scenario, WED, 9, 30)  # a first sync: the wall's members are known
    await add(
        scenario,
        "Add replace vacuum water as an item in my evening routine for tonight",
        {"title": "Replace vacuum water", "part": "Evening", "repeat": ""},
    )
    routine = fake_cozyla.routine_named("Replace vacuum water")
    assert (routine["memberUid"], routine["routineType"]) == ("m-erin", "Evening")
    assert scenario.app.db.query("SELECT 1 FROM pending_actions WHERE status = 'pending'") == []
    assert not any(c["choreName"] == "Replace vacuum water" for c in fake_cozyla.chores.values())

    await at(scenario, WED, 20, 30)  # an hour before her quiet hours: the evening check
    assert any("Replace vacuum water" in t for t in routine_texts(scenario, "Erin"))
    await at(scenario, WED + timedelta(days=1), 9)
    assert not any(
        r["routineTitle"] == "Replace vacuum water" for r in fake_cozyla.routines.values()
    )


MOVE_IT = (
    "I'll handle the vacuum water task that Erin has. Can you move it to my evening "
    "routine for today?"
)
VACUUM_ITEM = {"position": "end", "title": "Vacuum water", "part": "Evening", "repeat": "today"}


async def test_a_task_moved_to_a_routine_is_the_routine_item_and_no_longer_a_task(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #133: Michael took on Erin's vacuum chore for his evening routine, and a new
    routine item was made beside it: Erin's task stayed, and neither knew of the other.
    Moved, it's a just-for-today item on his routine, and the task is closed."""
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Refill the vacuum's clean water", "physical", 1, assignee=erin
    )
    await at(scenario, WED, 9, 30)
    scenario.primary.queue_tool_call("add_to_wall_routine", {**VACUUM_ITEM, "task_id": 0})
    scenario.primary.queue_tool_call("add_to_wall_routine", {**VACUUM_ITEM, "task_id": task.id})
    scenario.primary.queue_text("Done.")
    await scenario.say("Husband", MOVE_IT)

    refused = str(scenario.primary.requests[-2].messages[-1])
    assert f"task {task.id}" in refused and "Erin's" in refused
    routine = fake_cozyla.routine_named("Vacuum water")
    assert (routine["memberUid"], routine["routineType"]) == ("m-husband", "Evening")
    assert board(scenario).get(task.id).status == "cancelled"
    assert board(scenario).open_for(erin) == []
    await at(scenario, WED + timedelta(days=1), 9)
    assert not any(r["routineTitle"] == "Vacuum water" for r in fake_cozyla.routines.values())


async def test_one_off_items_go_the_next_day_though_one_is_gone_already(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #141: three just-for-today items on an evening routine. One was removed
    that day, so deleting it the next day got the wall's 30005, which stopped the whole
    sync, every time: the other two stayed on the routine, and check-ins stopped
    syncing too."""
    await at(scenario, WED, 9, 30)
    for title in ("Vacuum water", "Refill cat feeders", "Cover the birdcage"):
        await add(scenario, f"Add {title} to my evening routine tonight", {
            "title": title, "part": "Evening", "repeat": "today",
        })  # fmt: skip
    gone = fake_cozyla.routine_named("Vacuum water")["id"]
    del fake_cozyla.routines[gone]  # removed on the wall (or in chat) that day

    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(run.id, erin, repeat=parse("every Saturday", WED))
    await at(scenario, WED + timedelta(days=1), 9)

    titles = {r["routineTitle"] for r in fake_cozyla.routines.values()}
    assert not titles & {"Refill cat feeders", "Cover the birdcage"}
    assert "Go for a run" in titles  # the rest of the sync ran
    assert scenario.app.db.query("SELECT * FROM wall_routine_once") == []


async def test_a_one_off_item_from_the_wall_is_just_for_its_day_in_themi(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #141: R1b brought add_to_wall_routine's item into Themi as every day, so until
    the wall let it go, Themi's own evening check kept listing it."""
    await at(scenario, WED, 9, 30)
    await add(scenario, "Add refill cat feeders to my evening routine tonight", {
        "title": "Refill cat feeders", "part": "Evening", "repeat": "today",
    })  # fmt: skip
    fake_cozyla.fail("delRoutine", times=50)  # the wall won't let it go for now
    await at(scenario, WED, 9, 45)
    thursday = WED + timedelta(days=1)
    await at(scenario, thursday, 20, 30)  # Thursday's evening check
    assert not any("Refill cat feeders" in t for t in routine_texts(scenario, "Erin"))
    row = scenario.app.db.one("SELECT only_on FROM routine_items WHERE title = ?", (
        "Refill cat feeders",
    ))  # fmt: skip
    assert row is not None and row["only_on"] == WED.isoformat()


async def test_a_new_routine_item_like_an_open_task_leaves_the_task_alone(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Refill the vacuum's clean water", "physical", 1, assignee=erin
    )
    await at(scenario, WED, 9, 30)
    await add(
        scenario,
        "Add vacuum water to my evening routine tonight",
        {"title": "Vacuum water", "part": "Evening", "repeat": "today", "task_id": 0},
    )
    assert fake_cozyla.routine_named("Vacuum water")
    assert board(scenario).get(task.id).status == "open"


async def test_a_repeating_chore_isnt_moved_to_a_routine(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Water the plants", "physical", 1, assignee=erin)
    await board(scenario).set_schedule(task.id, erin, repeat=parse("every Tuesday", WED))
    await at(scenario, WED, 9, 30)
    await add(
        scenario,
        "Move the water the plants task to my morning routine",
        {"title": "Water the plants", "part": "Morning", "repeat": "", "task_id": task.id},
    )
    assert "repeating chore" in last_result(scenario)
    assert board(scenario).get(task.id).status == "open"


async def test_a_repeating_item_stays(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    await at(scenario, WED, 9, 30)
    await add(
        scenario,
        "Put water the plants in my morning routine every Tue and Thu",
        {"title": "Water the plants", "part": "Morning", "repeat": "every Tue and Thu"},
    )
    routine = fake_cozyla.routine_named("Water the plants")
    assert routine["repeatsIn"] == "Tuesday,Thursday"
    await at(scenario, WED + timedelta(days=1), 9)
    assert fake_cozyla.routine_named("Water the plants")  # still there


async def test_until_further_notice_stays_even_if_the_model_says_today(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #47: the two items from #38 had gone in just for today, and "add them until
    further notice" didn't put them back."""
    await at(scenario, WED, 9, 30)
    await add(
        scenario,
        "Yes, add take wegovy to my morning routine until further notice",
        {"title": "Take wegovy", "part": "Morning", "repeat": "today"},
    )
    await at(scenario, WED + timedelta(days=1), 9)
    assert fake_cozyla.routine_named("Take wegovy")  # still there


async def test_mentioned_but_not_asked_its_a_card(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    await at(scenario, WED, 9, 30)
    replies = await add(
        scenario,
        "I keep forgetting the vacuum",
        {"title": "Replace vacuum water", "part": "Evening", "repeat": ""},
    )
    assert replies[0] == (
        "Replace vacuum water for the evening routine, every day\nGo ahead, or not now?"
    )


async def test_items_go_where_they_were_asked_and_stay(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bug #38: "add take wegovy and drug a bean as the first two tasks of my morning
    routine" put them at the end, and only for today."""
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    fake_cozyla.add_routine("m-erin", "Make the bed", "Morning")
    await at(scenario, WED, 9, 30)
    said = "Add take wegovy and drug a bean as the first two tasks of my morning routine"
    scenario.primary.queue_tool_calls(
        [
            (
                "add_to_wall_routine",
                {
                    "title": "Take wegovy",
                    "part": "Morning",
                    "repeat": "",
                    "position": "start",
                    "task_id": 0,
                },
                None,
            ),
            (
                "add_to_wall_routine",
                {
                    "title": "Drug a bean",
                    "part": "Morning",
                    "repeat": "",
                    "position": "after: take wegovy",
                    "task_id": 0,
                },
                None,
            ),
        ]
    )
    scenario.primary.queue_text("Done.")
    await scenario.say("Erin", said)
    assert fake_cozyla.routine_order("m-erin", "Morning") == [
        "Take wegovy", "Drug a bean", "Walk dog", "Make the bed",
    ]  # fmt: skip
    assert scenario.app.db.query("SELECT * FROM wall_routine_once") == []  # every day
    await at(scenario, WED + timedelta(days=1), 9)
    assert "Take wegovy" in fake_cozyla.routine_order("m-erin", "Morning")


async def test_a_wall_that_keeps_its_own_order_is_said_so(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    fake_cozyla.takes_order = False
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    await at(scenario, WED, 9, 30)
    await add(
        scenario,
        "Put take wegovy first in my morning routine",
        {"title": "Take wegovy", "part": "Morning", "repeat": "", "position": "start"},
    )
    result = scenario.primary.last_request.messages[-1].content[0].content  # type: ignore[union-attr]
    assert "went at the end" in result
    assert fake_cozyla.routine_order("m-erin", "Morning") == ["Walk dog", "Take wegovy"]


# ----- F18b: asking about a routine, and a morning check that's too late -----------------


async def test_the_morning_check_isnt_sent_in_the_evening(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Erin got "Morning routine, still open: Walk dog" at 21:15: queued in the evening (or
    held until its deadline), it went out just before quiet hours."""
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    fake_cozyla.add_routine("m-erin", "Cycle dishwasher", "Evening")
    await at(scenario, WED, 20, 43)  # the first sync of the day after a restart
    assert routine_texts(scenario, "Erin") == [
        "Evening routine, still open:\n- Cycle dishwasher\nDone already?"
    ]


async def test_a_morning_check_held_back_lapses_when_the_evening_starts(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Idea #96: held all afternoon, Erin's morning check went at 8:15 pm."""
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    await at(scenario, WED, 12, 1)
    (row,) = scenario.app.db.query("SELECT expires_at, deadline FROM outbox WHERE kind = 'routine'")
    assert row["expires_at"] == "2026-10-22T00:00:00+00:00"  # 5 pm Pacific
    assert row["deadline"] < row["expires_at"]


async def test_no_morning_check_after_the_afternoon(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    await at(scenario, WED, 17, 30)  # the first sync of the day after a restart
    assert routine_texts(scenario, "Erin") == []


async def test_a_routine_check_can_be_skipped_for_today(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Idea #96: "Themi should never offer a single push button. This should have been
    'walk dog' or 'skip today'"."""
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    await at(scenario, WED, 12, 1)
    assert scenario.last_buttons("Erin") == ["✓ Walk dog", "Skip today"]
    await scenario.tap("Erin", "Skip today")
    edit = scenario.edits("Erin")[-1]
    assert edit["text"] == "Morning routine: left for today."
    assert not edit.get("reply_markup", {}).get("inline_keyboard")
    assert fake_cozyla.routine_ticks == set()  # nothing ticked on the wall


def routine_question(scenario: Scenario, part: str) -> None:
    scenario.primary.queue_tool_call("show_routine", {"part": part})
    scenario.primary.queue_text("Here it is.")


def last_result(scenario: Scenario) -> str:
    return str(scenario.primary.last_request.messages[-1])


async def test_asking_about_a_routine_reads_it_from_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Bugs #76 and #78: "What is my morning routine?" got the day's summary, then "The
    morning routine board has no items", though it had Walk dog."""
    walk = fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    fake_cozyla.add_routine("m-erin", "Make the bed", "Morning")
    fake_cozyla.add_routine("m-erin", "Cycle dishwasher", "Evening")
    fake_cozyla.add_routine("m-husband", "Take meds", "Morning")
    fake_cozyla.tick_routine(walk, WED)
    routine_question(scenario, "Morning")
    await scenario.say("Erin", "What is my morning routine?")
    result = last_result(scenario)
    assert "Morning routine on the wall, today: Walk dog (done), Make the bed" in result
    assert "Take meds" not in result and "Cycle dishwasher" not in result

    routine_question(scenario, "")
    await scenario.say("Erin", "What are my routines?")
    result = last_result(scenario)
    assert "Morning routine" in result and "Evening routine" in result

    routine_question(scenario, "Afternoon")
    await scenario.say("Erin", "And my afternoon routine?")
    assert "Nothing on the afternoon routine on the wall" in last_result(scenario)


async def test_a_routine_question_brings_the_wall_tools_not_the_day(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "What is my morning routine?")
    names = {t.name for t in scenario.primary.last_request.tools}
    assert "show_routine" in names
    assert "day_summary" not in names


async def test_a_check_in_unticked_on_the_wall_isnt_ticked_again(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """F31a pins today's behaviour: a check-in round ticked on the wall and then unticked
    there stays done in Themi (undoing a repeating round is a follow-up), and Themi doesn't
    tick the wall again."""
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
    thursday = WED + timedelta(days=1)
    fake_cozyla.tick_routine(routine["id"], thursday)
    await at(scenario, thursday, 16)
    assert board(scenario).get(run.id).due_on == date(2026, 10, 24)
    fake_cozyla.tick_routine(routine["id"], thursday, done=False)
    await at(scenario, thursday, 16, 30)
    assert (routine["id"], thursday.isoformat()) not in fake_cozyla.routine_ticks
    assert board(scenario).get(run.id).due_on == date(2026, 10, 24)
