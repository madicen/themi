"""A chore that waits for another (T2). Michael, 2026-10-31: "Any time you are going to assign
Erin to Clean the Kitchen, first send a task to Michael to declutter the kitchen. Once that
task is marked done, then Erin can be assigned a Clean the kitchen task."

The scenario starts on Wednesday 21 Oct; Erin cleans the kitchen that day, so the first round
that waits is Wednesday 28 Oct, and Michael's declutter is due Tuesday 27 Oct."""

from datetime import date, datetime, timedelta

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import START, Scenario
from themi import clock
from themi.ai.types import ToolResult
from themi.channels.pda import MAX_STRENGTH, find_demands
from themi.core.repeat import parse
from themi.core.tasks import Task, TaskBoard

MESSAGE = (
    "Any time you are going to assign Erin to Clean the Kitchen, first send a task to Michael "
    "to declutter the kitchen. Once that task is marked done, then Erin can be assigned a "
    "Clean the kitchen task."
)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def until(scenario: Scenario, day: date, hour: int = 10) -> None:
    """Let time pass to that day and hour, running the hourly schedule job each day."""
    while True:
        target = datetime(day.year, day.month, day.day, hour, tzinfo=START.tzinfo)
        step = min(target - clock.now(), timedelta(days=1))
        if step <= timedelta(0):
            return
        await scenario.advance(hours=step / timedelta(hours=1))
        await scenario.run_periodic("tasks.schedules")


def about(scenario: Scenario, name: str, words: str, since: int = 0) -> list[str]:
    return [t for t in scenario.inbox(name)[since:] if words in t]


def last_tool_result(scenario: Scenario) -> ToolResult:
    return [
        block
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


NEXT_TIME = (
    "Next time Erin has Clean the Kitchen, first send Michael a task to declutter the "
    "kitchen; once that's done she can clean it."
)


async def kitchen_and_declutter(
    scenario: Scenario, *, once: bool = False, wall: bool = False, message: str = MESSAGE
) -> tuple[Task, Task, list[str]]:
    erin, michael = scenario.member("Erin"), scenario.member("Husband")
    kitchen = await board(scenario).create(erin, "Clean kitchen", "physical", 2, assignee=erin)
    await board(scenario).set_schedule(
        kitchen.id, erin, repeat=parse("every Wednesday", scenario.today())
    )
    if wall:
        await scenario.run_periodic("cozyla.chores")
    await board(scenario).complete(kitchen.id, erin)  # this week's, done
    declutter = await board(scenario).create(
        michael, "Declutter the kitchen", "physical", 1, assignee=michael, nudge=False
    )
    scenario.primary.queue_tool_call(
        "set_task_schedule",
        {
            "task_id": declutter.id,
            "repeat": "",
            "at_least_every_days": 0,
            "escalate_after_days": 0,
            "escalate_to": "owner",
            "missed": "roll",
            "due_before_task": kitchen.id,
            "either": False,
            "holds_back": True,
            "once": once,
        },
    )
    scenario.primary.queue_text("All set.")
    replies = await scenario.say("Husband", message)
    return board(scenario).get(kitchen.id), board(scenario).get(declutter.id), replies


async def test_michaels_timeline(scenario: Scenario) -> None:
    """Declutter due Tuesday; nothing for Erin Wednesday or Thursday; Michael finishes Friday
    and the kitchen comes up for Erin that day."""
    kitchen, declutter, replies = await kitchen_and_declutter(scenario)
    assert replies[0] == (
        "Saved: Due the day before Clean kitchen (Every Wednesday); Clean kitchen waits until "
        "it's done, every time. Next: Tue 27 Oct."
    )
    assert declutter.due_on == date(2026, 10, 27)
    erin_seen = len(scenario.inbox("Erin"))

    await until(scenario, date(2026, 10, 27), 18)
    (nudge,) = about(scenario, "Husband", "Declutter the kitchen")
    assert 'It clears the way for Erin\'s "Clean kitchen".' in nudge

    await until(scenario, date(2026, 10, 30), 10)  # Wednesday and Thursday pass
    assert not about(scenario, "Erin", "kitchen", erin_seen)
    assert board(scenario).get(kitchen.id).due_on == date(2026, 10, 28)  # not rolled on
    assert [r.missed for r in board(scenario).runs(kitchen.id)] == [False]  # no miss for her
    assert not any(r.missed for r in board(scenario).runs(declutter.id))

    await board(scenario).complete(declutter.id, scenario.member("Husband"))  # Friday
    await scenario.advance(hours=4)
    assert about(scenario, "Erin", "Clean kitchen", erin_seen)
    now = board(scenario).get(kitchen.id)
    assert now.due_on == date(2026, 10, 30) and now.round_until == date(2026, 11, 3)
    assert board(scenario).get(declutter.id).due_on == date(2026, 11, 3)  # next week's


async def test_a_round_that_came_up_late_runs_until_the_next(scenario: Scenario) -> None:
    kitchen, declutter, _ = await kitchen_and_declutter(scenario)
    await until(scenario, date(2026, 10, 30))
    await board(scenario).complete(declutter.id, scenario.member("Husband"))
    await until(scenario, date(2026, 11, 3), 23)
    assert board(scenario).get(kitchen.id).due_on == date(2026, 10, 30)  # still hers to do
    await until(scenario, date(2026, 11, 4), 1)  # the next round's day: hers was missed
    now = board(scenario).get(kitchen.id)
    assert now.due_on == date(2026, 11, 4) and now.round_until is None
    assert [r.missed for r in board(scenario).runs(kitchen.id)] == [False, True]
    assert board(scenario).waiting_on(now)  # and it waits for this week's declutter


async def test_done_early_the_kitchen_still_waits_for_wednesday(scenario: Scenario) -> None:
    kitchen, declutter, _ = await kitchen_and_declutter(scenario)
    erin_seen = len(scenario.inbox("Erin"))
    await until(scenario, date(2026, 10, 27), 9)
    await board(scenario).complete(declutter.id, scenario.member("Husband"))  # Tuesday
    await until(scenario, date(2026, 10, 27), 21)
    assert not about(scenario, "Erin", "kitchen", erin_seen)
    await until(scenario, date(2026, 10, 28), 18)
    assert about(scenario, "Erin", "Clean kitchen", erin_seen)
    assert board(scenario).get(kitchen.id).due_on == date(2026, 10, 28)


async def test_undone_into_the_next_week_one_declutter_is_owed(scenario: Scenario) -> None:
    kitchen, declutter, _ = await kitchen_and_declutter(scenario)
    erin_seen = len(scenario.inbox("Erin"))
    await until(scenario, date(2026, 11, 4), 12)
    assert not about(scenario, "Erin", "kitchen", erin_seen)
    assert board(scenario).get(kitchen.id).due_on == date(2026, 11, 4)  # moved on quietly
    assert [r.missed for r in board(scenario).runs(kitchen.id)] == [False]
    owed = board(scenario).get(declutter.id)
    assert owed.status == "open" and owed.due_on == date(2026, 11, 3)  # for the new round
    assert board(scenario).runs(declutter.id) == []  # not missed: still owed
    titles = [t.title for t in board(scenario).open_for(scenario.member("Husband"))]
    assert titles.count("Declutter the kitchen") == 1

    await board(scenario).complete(declutter.id, scenario.member("Husband"))
    await scenario.advance(hours=4)
    assert about(scenario, "Erin", "Clean kitchen", erin_seen)
    assert board(scenario).get(kitchen.id).due_on == date(2026, 11, 4)  # today's round


async def test_next_time_holds_one_round(scenario: Scenario) -> None:
    kitchen, declutter, replies = await kitchen_and_declutter(
        scenario, once=True, message=NEXT_TIME
    )
    assert "Clean kitchen waits until it's done, this once." in replies[0]
    await until(scenario, date(2026, 10, 27))
    await board(scenario).complete(declutter.id, scenario.member("Husband"))
    assert board(scenario).get(declutter.id).status == "done"
    await until(scenario, date(2026, 10, 28))
    await board(scenario).complete(kitchen.id, scenario.member("Erin"))
    after = board(scenario).get(kitchen.id)
    assert after.due_on == date(2026, 11, 4) and not board(scenario).waiting_on(after)


async def test_any_time_is_every_time_whatever_once_says(scenario: Scenario) -> None:
    """Bug #110: Michael's "Any time…" was saved "this once", since the model passed once."""
    _, declutter, replies = await kitchen_and_declutter(scenario, once=True)
    assert "Clean kitchen waits until it's done, every time." in replies[0]
    assert declutter.holds_target and not declutter.hold_once


async def test_the_hold_is_on_the_chore_whoever_has_it(scenario: Scenario) -> None:
    kitchen, _, _ = await kitchen_and_declutter(scenario)
    store = scenario.app.store
    store.db.execute(
        "UPDATE tasks SET assignee = ? WHERE id = ?", (scenario.member("Husband").id, kitchen.id)
    )
    seen = len(scenario.inbox("Husband"))
    await until(scenario, date(2026, 10, 28), 20)
    assert not about(scenario, "Husband", ": Clean kitchen", seen)  # not just its mention
    assert board(scenario).waiting_on(board(scenario).get(kitchen.id))


async def test_a_waiting_chore_doesnt_take_the_charts_one_place(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    await kitchen_and_declutter(scenario)
    upstairs = await board(scenario).create(erin, "Clean upstairs", "physical", 2, assignee=erin)
    await board(scenario).set_schedule(
        upstairs.id, erin, repeat=parse("every Wednesday", scenario.today())
    )
    await board(scenario).complete(upstairs.id, erin)
    scenario.app.store.update_settings(erin, erin.id, chart_limit=1)
    await until(scenario, date(2026, 10, 28))
    await scenario.run_periodic("cozyla.chores")
    names = [c["choreName"] for c in fake_cozyla.chores.values()]
    assert "Clean upstairs" in names and "Clean kitchen" not in names


async def test_off_the_wall_while_it_waits(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    _, declutter, _ = await kitchen_and_declutter(scenario, wall=True)
    await scenario.run_periodic("cozyla.chores")
    assert "Clean kitchen" not in [c["choreName"] for c in fake_cozyla.chores.values()]
    await until(scenario, date(2026, 10, 27))
    await board(scenario).complete(declutter.id, scenario.member("Husband"))
    await scenario.run_periodic("cozyla.chores")
    assert "Clean kitchen" in [c["choreName"] for c in fake_cozyla.chores.values()]


async def test_the_model_knows_why_it_waits(scenario: Scenario) -> None:
    await kitchen_and_declutter(scenario)
    items = [i.summary for i in board(scenario).open_items(scenario.member("Erin"))]
    (line,) = [t for t in items if "Clean kitchen" in t]
    assert "Waits until Declutter the kitchen is done first" in line


async def test_the_clears_the_way_line_isnt_a_demand() -> None:
    for line in (
        'It clears the way for Erin\'s "Clean kitchen".',
        'It clears the way for your "Clean kitchen".',
        'It clears the way for "Clean kitchen".',
    ):
        assert find_demands(line, MAX_STRENGTH) == []


async def test_said_as_a_rule_it_goes_to_the_schedule(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Declutter before the kitchen",
            "text": MESSAGE,
            "kind": "policy",
            "category": "",
            "rule_id": 0,
            "applies_to": "household",
        },
    )
    scenario.primary.queue_text("Let me set that up as chores instead.")
    await scenario.say("Husband", MESSAGE)
    result = last_tool_result(scenario)
    assert result.is_error and "holds_back" in result.content
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM rules") == 0


async def test_holding_back_needs_a_chore_to_hold(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Declutter", "physical", 1, assignee=erin)
    try:
        await board(scenario).set_schedule(
            task.id, erin, repeat=parse("every Tuesday", scenario.today()), holds_target=True
        )
    except ValueError as exc:
        assert "due_before_task" in str(exc)
    else:
        raise AssertionError("a hold without a chore to hold was saved")
