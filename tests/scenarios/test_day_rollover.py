"""F34j (Michael's idea #182): "allow users to define when a day rolls over. Beneficial for
doing chores after midnight." The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts import SYSTEM
from themi.core import keys
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard
from themi.localtime import member_day

PACIFIC = ZoneInfo("America/Los_Angeles")
WED, FRI, SAT = date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 24)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> None:
    target = datetime(day.year, day.month, day.day, hour, minute, tzinfo=PACIFIC)
    clock.advance(target - clock.now())
    await scenario.run_periodic("tasks.schedules")


async def kitchen(scenario: Scenario, name: str) -> Task:
    who = scenario.member(name)
    task = await board(scenario).create(who, "Clean the kitchen", "physical", 2, assignee=who)
    return await board(scenario).set_schedule(task.id, who, repeat=parse("every day", WED))


def rollover(scenario: Scenario, hour: int = 3) -> None:
    scenario.app.store.update_settings(SYSTEM, scenario.member("Husband").id, day_ends=hour)


def test_the_helper() -> None:
    class Someone:
        day_ends = 3

    late = datetime(2026, 10, 24, 0, 40, tzinfo=PACIFIC)
    assert member_day(Someone(), late, PACIFIC) == FRI
    assert member_day(Someone(), datetime(2026, 10, 24, 3, 1, tzinfo=PACIFIC), PACIFIC) == SAT


async def test_a_chore_done_after_midnight_counts_for_the_day_before(scenario: Scenario) -> None:
    rollover(scenario)
    await at(scenario, FRI, 9)
    task = await kitchen(scenario, "Husband")
    assert board(scenario).get(task.id).due_on == FRI
    await at(scenario, SAT, 0, 40)  # the hourly check: Friday's round isn't missed yet
    assert not any(r.missed for r in board(scenario).runs(task.id))
    said = await board(scenario).complete(task.id, scenario.member("Husband"))
    assert "yesterday" not in said.lower()
    (run,) = [r for r in board(scenario).runs(task.id) if not r.missed and r.due_on == FRI]
    assert run.on_time
    assert board(scenario).get(task.id).due_on == SAT  # Saturday's round is still to come


async def test_with_midnight_nothing_changes(scenario: Scenario) -> None:
    await at(scenario, FRI, 9)
    task = await kitchen(scenario, "Erin")
    assert board(scenario).get(task.id).due_on == FRI
    await at(scenario, SAT, 0, 40)
    assert any(r.missed and r.due_on == FRI for r in board(scenario).runs(task.id))


async def test_routines_tick_for_the_day_before_until_the_rollover(scenario: Scenario) -> None:
    rollover(scenario)
    routines = scenario.app.services.maybe(keys.routines)
    assert routines is not None
    michael = scenario.member("Husband")
    evening, morning = routines.find(michael, "Evening"), routines.find(michael, "Morning")
    assert evening is not None and morning is not None
    dishes = routines.add_item(evening, "Run the dishwasher")
    coffee = routines.add_item(morning, "Make coffee")
    await at(scenario, SAT, 0, 40)
    assert routines.today(michael) == FRI
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "Run the dishwasher"})
    await scenario.say("Husband", "ran the dishwasher")
    assert routines.ticked(dishes, FRI) and not routines.ticked(dishes, SAT)
    assert not routines.ticked(coffee, SAT)
    await at(scenario, SAT, 3, 1)
    assert routines.today(michael) == SAT


async def test_the_daily_limit_counts_from_their_rollover(scenario: Scenario) -> None:
    rollover(scenario)
    outbox = scenario.app.outbox
    michael = scenario.member("Husband")
    await at(scenario, SAT, 0, 30)
    scenario.app.db.execute(
        "INSERT INTO outbox (member_id, text, priority, status, kind, created_at, sent_at, "
        "send_after) VALUES (?, 'late', 'normal', 'sent', 'task', ?, ?, ?)",
        (michael.id, *[clock.now().astimezone(UTC).isoformat()] * 3),
    )
    assert outbox.sent_today(michael.id) == 1  # still Friday for him
    await at(scenario, SAT, 3, 1)
    assert outbox.sent_today(michael.id) == 0


async def test_the_setting_on_my_settings(scenario: Scenario) -> None:
    rollover(scenario, 2)
    assert scenario.app.store.get_member(scenario.member("Husband").id).day_ends == 2


def test_the_models_context_says_its_still_friday(scenario: Scenario) -> None:
    from themi.core.prompts import day_note

    rollover(scenario)
    michael = scenario.app.store.get_member(scenario.member("Husband").id)
    late = datetime(2026, 10, 24, 0, 40, tzinfo=PACIFIC)
    assert day_note(michael, late).startswith(" (For Husband it's still Friday until 3 am")
    assert "'tonight' means now" in day_note(michael, late)
    assert day_note(michael, datetime(2026, 10, 24, 3, 5, tzinfo=PACIFIC)) == ""
    assert day_note(scenario.member("Erin"), late) == ""


async def test_a_habit_check_in_is_once_for_their_day(scenario: Scenario) -> None:
    rollover(scenario)
    habits = scenario.app.services.maybe(keys.habits)
    assert habits is not None
    michael = scenario.member("Husband")
    await at(scenario, SAT, 0, 40)
    assert habits._today(michael) == FRI
