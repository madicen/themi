"""F9a, Erin's runs (bug #10): "Tuesday, Thursday, and Saturday or Sunday. If I miss a day,
prompt me the next day. Never two days in a row." The clock starts on Wednesday 21 October
2026, 09:00; Erin's quiet hours start at 21:30."""

from __future__ import annotations

from datetime import date

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.progression import parse_plan
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

RUNS = "every Tue, Thu and Sat or Sun at 2pm, never two days in a row"
WED = date(2026, 10, 21)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def runs(scenario: Scenario) -> tuple[Task, list[str]]:
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    scenario.primary.queue_tool_call(
        "set_task_schedule",
        {
            "task_id": task.id,
            "repeat": RUNS,
            "at_least_every_days": 0,
            "escalate_after_days": 0,
            "escalate_to": "owner",
            "missed": "next_day",
            "due_before_task": 0,
            "either": False,
            "holds_back": False,
            "once": False,
        },
    )
    scenario.primary.queue_text("All set.")
    replies = await scenario.say("Erin", "Runs: Tue, Thu and Sat or Sun, never two days in a row")
    return board(scenario).get(task.id), replies


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> None:
    """Move the clock to that local time, and let the hourly schedule check run."""
    target = clock.now().replace(
        year=day.year, month=day.month, day=day.day, hour=hour, minute=minute
    )
    clock.advance(target - clock.now())
    await scenario.run_periodic("tasks.schedules")
    await scenario.app.outbox.flush()


def run_nudges(scenario: Scenario) -> int:
    return sum("Go for a run" in t for t in scenario.inbox("Erin"))


async def done(scenario: Scenario, task: Task) -> str:
    return await board(scenario).complete(task.id, scenario.member("Erin"))


def due(scenario: Scenario, task: Task) -> date:
    found = board(scenario).get(task.id).due_on
    assert found is not None
    return found


async def test_saturday_or_sunday_is_one_round(scenario: Scenario) -> None:
    run, replies = await runs(scenario)
    assert replies[0] == (
        "Saved: Every Tuesday, Thursday and Saturday or Sunday at 2 pm, never two days in a "
        "row; a missed day moves to the next day. Next: Thu 22 Oct, 2 pm."
    )
    await at(scenario, date(2026, 10, 22), 15)
    await done(scenario, run)
    assert due(scenario, run) == date(2026, 10, 24)

    await at(scenario, date(2026, 10, 24), 23)  # Saturday night: still fine tomorrow
    await at(scenario, date(2026, 10, 25), 10)
    assert due(scenario, run) == date(2026, 10, 24)
    assert board(scenario).runs(run.id)[-1].due_on == date(2026, 10, 22)  # nothing missed

    await at(scenario, date(2026, 10, 25), 19, 30)  # two hours before her quiet hours
    await scenario.run_periodic("tasks.day_end")
    await scenario.app.outbox.flush()
    assert any(
        t.startswith("Still open today:") and "Go for a run" in t for t in scenario.inbox("Erin")
    )

    reply = await done(scenario, run)  # run on Sunday: that's the weekend's round, on time
    assert board(scenario).runs(run.id)[-1].on_time
    assert "Next round: Tue 27 Oct" in reply
    before = run_nudges(scenario)
    await at(scenario, date(2026, 10, 26), 22)  # Monday after a Sunday run: nothing
    assert run_nudges(scenario) == before


async def test_a_missed_day_moves_to_the_next_and_rest_days_are_kept(scenario: Scenario) -> None:
    run, _ = await runs(scenario)
    await at(scenario, date(2026, 10, 22), 15)
    await done(scenario, run)
    await at(scenario, date(2026, 10, 24), 15)
    await done(scenario, run)
    assert due(scenario, run) == date(2026, 10, 27)

    await at(scenario, date(2026, 10, 28), 1)  # Tuesday's passed undone: Wednesday, then
    assert due(scenario, run) == date(2026, 10, 28)
    assert not any(r.missed for r in board(scenario).runs(run.id))
    before = run_nudges(scenario)
    await at(scenario, date(2026, 10, 28), 14, 1)
    assert run_nudges(scenario) == before + 1  # prompted the next day

    reply = await done(scenario, run)  # ran Wednesday, so not Thursday too
    assert "Next round: Fri 30 Oct" in reply
    before = run_nudges(scenario)
    await at(scenario, date(2026, 10, 29), 22)
    assert run_nudges(scenario) == before

    await at(scenario, date(2026, 10, 30), 15)
    await done(scenario, run)  # ran Friday: the weekend's round is Sunday
    assert due(scenario, run) == date(2026, 11, 1)
    await at(scenario, date(2026, 11, 1), 15)
    await done(scenario, run)
    assert due(scenario, run) == date(2026, 11, 3)


async def test_missed_twice_it_rolls_on_to_the_next_round(scenario: Scenario) -> None:
    run, _ = await runs(scenario)
    await at(scenario, date(2026, 10, 23), 1)  # Thursday's missed: Friday
    assert due(scenario, run) == date(2026, 10, 23)
    await at(scenario, date(2026, 10, 24), 1)  # Friday's too: Saturday's round is next
    assert due(scenario, run) == date(2026, 10, 24)
    (missed,) = board(scenario).runs(run.id)
    assert missed.missed and missed.due_on == date(2026, 10, 23)


async def test_on_the_wall_both_days_show_and_either_tick_counts(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(run.id, erin, repeat=parse(RUNS, WED), missed="next_day")
    await scenario.run_periodic("cozyla.routines")
    routine = fake_cozyla.routine_named("Go for a run")
    assert routine["repeatsIn"] == "Tuesday,Thursday,Saturday,Sunday"

    await at(scenario, date(2026, 10, 22), 15)
    await done(scenario, run)
    sunday = date(2026, 10, 25)
    await at(scenario, sunday, 15)
    fake_cozyla.tick_routine(routine["id"], sunday)  # ticked on the wall on Sunday
    await scenario.run_periodic("cozyla.routines")
    assert due(scenario, run) == date(2026, 10, 27)

    await at(scenario, date(2026, 10, 27), 15)
    await done(scenario, run)
    await at(scenario, date(2026, 10, 29), 15)
    await done(scenario, run)
    await at(scenario, date(2026, 11, 1), 15)
    await done(scenario, run)  # Sunday's run, done in Themi: Sunday is ticked
    await scenario.run_periodic("cozyla.routines")
    assert (routine["id"], "2026-11-01") in fake_cozyla.routine_ticks


async def test_the_distance_plan_steps_up_on_tuesdays(scenario: Scenario) -> None:
    """F9c: "Next week is 1.3 miles, then 1.5, then up 0.25 a week, stepping up on Tuesdays"."""
    run, _ = await runs(scenario)
    scenario.primary.queue_tool_call(
        "set_task_plan",
        {"task_id": run.id, "plan": "1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays"},
    )
    scenario.primary.queue_text("Got it.")
    replies = await scenario.say("Erin", "Next week is 1.3 miles, then 1.5, then up 0.25")
    assert replies[0] == (
        "Saved for Go for a run: 1.3 miles from Tue 27 Oct, then 1.5, then up 0.25 a week; "
        "it steps up on Tuesdays."
    )  # it starts next week, so there's no amount yet

    def latest() -> str:
        return [t for t in scenario.inbox("Erin") if "Go for a run" in t][-1]

    await at(scenario, date(2026, 10, 22), 14, 1)
    assert latest().startswith("Check-in: Go for a run. ")  # before the plan starts
    await done(scenario, run)
    await at(scenario, date(2026, 10, 24), 15)
    await done(scenario, run)
    await at(scenario, date(2026, 10, 27), 14, 1)
    assert latest().startswith("Check-in: Go for a run (1.3 miles this week).")
    await done(scenario, run)
    await at(scenario, date(2026, 10, 29), 14, 1)
    assert "(1.3 miles this week)" in latest()
    await done(scenario, run)
    await at(scenario, date(2026, 10, 31), 15)
    await done(scenario, run)
    await at(scenario, date(2026, 11, 3), 14, 1)
    assert latest().startswith("Check-in: Go for a run (1.5 miles this week).")
    (item,) = [
        i.summary for i in board(scenario).open_items(scenario.member("Erin")) if "run" in i.summary
    ]
    assert "Plan: 1.3 miles from Tue 27 Oct" in item and "; 1.5 miles this week." in item


async def test_by_sunset(scenario: Scenario) -> None:
    """F9b: "at least an hour before sunset". The clock starts Wednesday 21 October, 9 am in
    California; sunset at home is about 6:24 pm."""
    scenario.app.db.execute(
        "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES "
        "(1, 'Home', 37.7749, -122.4194, '2026-10-21T00:00:00+00:00')"
    )
    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    task = await board(scenario).set_schedule(
        run.id,
        erin,
        repeat=parse("every Tue, Thu and Sat or Sun at 2pm, at least an hour before sunset", WED),
    )
    assert board(scenario).summary(task) == (
        "Every Tuesday, Thursday and Saturday or Sunday at 2 pm, at least an hour before sunset; "
        "today that's about 2 pm"
    )  # 2 pm is earlier than 5:20
    walk = await board(scenario).create(
        erin, "Walk the dog", "physical", 1, assignee=erin, nudge=False
    )
    walk = await board(scenario).set_schedule(
        walk.id, erin, repeat=parse("every day an hour before sunset", WED)
    )
    assert board(scenario).summary(walk).endswith("today that's about 5:20 pm")
    await at(scenario, WED, 17, 15)
    assert not any("Walk the dog" in t for t in scenario.inbox("Erin"))
    await at(scenario, WED, 17, 21)
    assert any("Walk the dog" in t for t in scenario.inbox("Erin"))


async def test_her_open_items_say_the_next_day_and_when_she_last_ran(scenario: Scenario) -> None:
    # Bug #64: she ran on Tuesday and the next run was due Thursday, but Themi said
    # "Saturday ... Tuesday was missed". It had only "due 2026-10-29", nothing on the run.
    run, _ = await runs(scenario)
    await at(scenario, date(2026, 10, 22), 15)
    await done(scenario, run)
    (line,) = [i.summary for i in board(scenario).open_items(scenario.member("Erin"))]
    assert line.startswith("Task ") and "due Sat 24 Oct" in line
    assert "Last done Thu 22 Oct." in line


async def test_a_round_moved_off_its_days_shows_on_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """F34c, bug #172: Wednesday's run moved Thursday's round to Friday, Themi nudged on
    Friday, and the wall didn't show the run on Friday."""
    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(run.id, erin, repeat=parse(RUNS, WED), missed="next_day")
    await at(scenario, date(2026, 10, 23), 1)  # Thursday's missed: the round is Friday's
    assert due(scenario, run) == date(2026, 10, 23)
    await scenario.run_periodic("cozyla.routines")
    routine = fake_cozyla.routine_named("Go for a run")
    assert routine["repeatsIn"] == "Tuesday,Thursday,Friday,Saturday,Sunday"

    await at(scenario, date(2026, 10, 23), 15)
    await done(scenario, run)  # Friday: the weekend's round is Sunday, and Friday goes
    assert due(scenario, run) == date(2026, 10, 25)
    await scenario.run_periodic("cozyla.routines")
    routine = fake_cozyla.routine_named("Go for a run")
    assert routine["repeatsIn"] == "Tuesday,Thursday,Saturday,Sunday"


async def test_no_run_today_moves_the_round_and_it_isnt_on_the_evening_list(
    scenario: Scenario,
) -> None:
    """F34c, bug #178: "No run today. I plan to run ... tomorrow or Sunday" left Friday's
    round where it was, and the 9:15 pm list still had it."""
    run, _ = await runs(scenario)
    await at(scenario, date(2026, 10, 23), 12)  # Thursday's missed: Friday's round
    scenario.primary.queue_tool_call("skip_round", {"task_id": run.id, "day": ""})
    replies = await scenario.say("Erin", "No run today. I plan to run tomorrow or Sunday")
    assert due(scenario, run) == date(2026, 10, 24)
    assert replies[-1] == '"Go for a run" moved to Sat 24 Oct (or Sun 25 Oct).'
    await at(scenario, date(2026, 10, 23), 19, 30)
    await scenario.run_periodic("tasks.day_end")
    await scenario.app.outbox.flush()
    assert not any(
        t.startswith("Still open today:") and "Go for a run" in t for t in scenario.inbox("Erin")
    )
    assert not any(r.missed for r in board(scenario).runs(run.id))


async def test_skipping_to_a_day_after_the_next_round_skips_this_round(
    scenario: Scenario,
) -> None:
    run, _ = await runs(scenario)
    await at(scenario, date(2026, 10, 23), 12)  # Thursday's missed: Friday's round
    scenario.primary.queue_tool_call("skip_round", {"task_id": run.id, "day": "2026-10-27"})
    replies = await scenario.say("Erin", "skip the run until Tuesday")
    assert due(scenario, run) == date(2026, 10, 27)
    assert replies[-1] == '"Go for a run" moved to Tue 27 Oct.'


async def test_after_a_saturday_run_sunday_is_ticked_on_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """F9a's known gap (F34cb): a weekend run done on Saturday left Sunday unticked on the
    wall, so the run looked undone on Sunday."""
    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(run.id, erin, repeat=parse(RUNS, WED), missed="next_day")
    await scenario.run_periodic("cozyla.routines")
    routine = fake_cozyla.routine_named("Go for a run")
    await at(scenario, date(2026, 10, 22), 15)
    await done(scenario, run)
    await at(scenario, date(2026, 10, 24), 15)
    await done(scenario, run)  # Saturday's run, done in Themi
    await scenario.run_periodic("cozyla.routines")
    assert (routine["id"], "2026-10-24") in fake_cozyla.routine_ticks
    await at(scenario, date(2026, 10, 25), 8)
    await scenario.run_periodic("cozyla.routines")
    assert (routine["id"], "2026-10-25") in fake_cozyla.routine_ticks
    assert due(scenario, run) == date(2026, 10, 27)  # Sunday's tick isn't another run
    assert len([r for r in board(scenario).runs(run.id) if not r.missed]) == 2


async def test_a_saturday_tick_on_the_wall_ticks_sunday_too(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    run = await board(scenario).create(
        erin, "Go for a run", "physical", 2, assignee=erin, check_in=True
    )
    await board(scenario).set_schedule(run.id, erin, repeat=parse(RUNS, WED), missed="next_day")
    await scenario.run_periodic("cozyla.routines")
    routine = fake_cozyla.routine_named("Go for a run")
    await at(scenario, date(2026, 10, 22), 15)
    await done(scenario, run)
    saturday = date(2026, 10, 24)
    await at(scenario, saturday, 15)
    fake_cozyla.tick_routine(routine["id"], saturday)
    await scenario.run_periodic("cozyla.routines")
    await at(scenario, date(2026, 10, 25), 8)
    await scenario.run_periodic("cozyla.routines")
    assert (routine["id"], "2026-10-25") in fake_cozyla.routine_ticks
    assert due(scenario, run) == date(2026, 10, 27)


async def plan_week_of_nov_3(scenario: Scenario) -> Task:
    """Erin's run with her plan, on Friday 6 November: this week's amount is 1.5 miles."""
    run, _ = await runs(scenario)
    board(scenario).set_progression(
        run.id,
        scenario.member("Erin"),
        parse_plan("1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays", WED),
    )
    await at(scenario, date(2026, 11, 6), 12)
    return run


async def test_a_distance_that_isnt_the_plans_is_asked_about(scenario: Scenario) -> None:
    """F34c, bug #178: "I plan to run 1.3 miles either tomorrow or Sunday" when this week's
    plan says 1.5. One choice, not a change."""
    run = await plan_week_of_nov_3(scenario)
    scenario.primary.queue_tool_call("skip_round", {"task_id": run.id, "day": ""})
    replies = await scenario.say(
        "Erin", "No run today. I plan to run 1.3 miles either tomorrow or Sunday"
    )
    assert "This week's plan says 1.5 miles. Keep 1.3 this week, or keep the plan?" in replies
    assert scenario.last_buttons("Erin") == ["1.3 this week", "Keep the plan"]
    plan = board(scenario).get(run.id).progression
    assert plan is not None and plan.amount_on(date(2026, 11, 6)) == 1.5  # nothing changed yet

    await scenario.tap("Erin", "1.3 this week")
    plan = board(scenario).get(run.id).progression
    assert plan is not None
    assert plan.amount_on(date(2026, 11, 7)) == 1.3
    assert plan.amount_on(date(2026, 11, 10)) == 1.75  # the next step is from the plan
    (item,) = [
        i.summary for i in board(scenario).open_items(scenario.member("Erin")) if "run" in i.summary
    ]
    assert "Plan: 1.3 miles from Tue 27 Oct" in item and "; 1.3 miles this week." in item


async def test_keep_the_plan_changes_nothing(scenario: Scenario) -> None:
    run = await plan_week_of_nov_3(scenario)
    scenario.primary.queue_tool_call("skip_round", {"task_id": run.id, "day": ""})
    await scenario.say("Erin", "No run today, I'll do 1.3 miles tomorrow")
    replies = await scenario.tap("Erin", "Keep the plan")
    assert any("1.5 miles" in r for r in [*replies, *[e["text"] for e in scenario.edits("Erin")]])
    plan = board(scenario).get(run.id).progression
    assert plan is not None and plan.amount_on(date(2026, 11, 7)) == 1.5


async def test_the_plans_own_distance_isnt_asked_about(scenario: Scenario) -> None:
    run = await plan_week_of_nov_3(scenario)
    scenario.primary.queue_tool_call("skip_round", {"task_id": run.id, "day": ""})
    replies = await scenario.say("Erin", "No run today, I'll do the 1.5 miles tomorrow")
    assert not any("Keep" in r for r in replies)
