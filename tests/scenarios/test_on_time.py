"""F15b: summaries and cards on time (bug #57, Michael's held cards), one nudge per task and
one morning list (bug #49). The clock starts on Wednesday 21 October 2026 at 09:00, Pacific;
Erin's quiet hours are 21:30-08:00, Husband's 23:00-07:00."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tests.scenarios.harness import Scenario
from themi import clock
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Priority
from themi.core.tasks import TaskBoard

PACIFIC = ZoneInfo("America/Los_Angeles")
THURSDAY = date(2026, 10, 22)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def until(scenario: Scenario, day: date, hour: int, minute: int = 0) -> list[str]:
    target = datetime(day.year, day.month, day.day, hour, minute, tzinfo=PACIFIC)
    return await scenario.advance(minutes=(target - clock.now()).total_seconds() / 60)


async def use_up_the_limit(scenario: Scenario, name: str) -> None:
    member = scenario.member(name)
    for n in range(member.daily_limit):
        await scenario.app.outbox.send(member, f"Note {n}", priority=Priority.NORMAL, kind="test")


def stage_card(scenario: Scenario, name: str, summary: str, **kw: Any) -> Any:
    autonomy = scenario.app.services.autonomy

    async def noop(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        return "Done."

    if "test.noop" not in autonomy.executors:
        autonomy.executors.register("test.noop")(noop)
    return autonomy.stage("email_mark_read", scenario.member(name), summary, {}, "test.noop", **kw)


# ----- bug #57 and the held cards -----------------------------------------------------------


async def test_the_summary_comes_at_its_time_past_the_daily_limit(scenario: Scenario) -> None:
    """Bug #57: Michael's 9 am summary waited for the next morning, behind his daily limit,
    still headed with the day before."""
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(husband, husband.id, morning_summary="10:00")
    await board(scenario).create(
        husband, "Bring the bins in", "physical", 1, date(2026, 10, 21), assignee=husband
    )
    await use_up_the_limit(scenario, "Husband")
    await until(scenario, date(2026, 10, 21), 10)
    await scenario.run_periodic("calendar.morning")
    assert any(t.startswith("Wed 21 Oct:") for t in scenario.inbox("Husband"))


async def test_a_message_too_late_to_be_any_use_is_dropped(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    soon = clock.now() + timedelta(hours=1)
    await scenario.app.outbox.send(
        erin, "Today's list", priority=Priority.NORMAL, not_before=soon + timedelta(hours=1),
        expires=soon,
    )  # fmt: skip
    sent = await scenario.advance(hours=3)
    assert "Today's list" not in sent
    assert scenario.app.outbox.queued(erin.id) == []


async def test_a_card_comes_the_same_day_past_the_daily_limit(scenario: Scenario) -> None:
    """Michael's reply draft and confirmations waited for the next morning."""
    await use_up_the_limit(scenario, "Husband")
    await stage_card(scenario, "Husband", "A confirmation to mark as read: UPS")
    sent = await scenario.advance(hours=2, minutes=1)
    assert "A confirmation to mark as read: UPS\nGo ahead, or not now?" in sent


async def test_a_card_about_something_over_lapses_unsent(scenario: Scenario) -> None:
    """A calendar card for that day's 12:45-4:45 delivery was held to the next morning."""
    await scenario.advance(hours=14, minutes=30)  # 23:30: Husband's quiet hours
    outcome = await stage_card(
        scenario, "Husband", "From an email: UPS delivery", expires=clock.now() + timedelta(hours=1)
    )
    sent = await until(scenario, THURSDAY, 7, 30)
    await scenario.run_periodic("approvals.expire")
    sent += await scenario.advance(minutes=1)
    assert not any("UPS delivery" in t for t in sent)
    action = scenario.app.services.autonomy.action(outcome.action.id)
    assert action.status == "expired"


# ----- bug #49 ---------------------------------------------------------------------------------


async def test_one_waiting_nudge_per_task(scenario: Scenario) -> None:
    """Bug #49: "Was due yesterday" and "Overdue" for the same task, both at 8:00."""
    erin = scenario.member("Erin")
    await scenario.advance(hours=13)  # 22:00, quiet hours
    task = await board(scenario).create(
        erin, "Copy the notes", "errand", 1, date(2026, 10, 21), assignee=erin
    )
    await until(scenario, THURSDAY, 2)
    await scenario.run_periodic("tasks.overdue")
    waiting = [r for r in scenario.app.outbox.queued(erin.id) if "Copy the notes" in r["text"]]
    assert [r["text"].split(",")[0] for r in waiting] == ["Overdue: Copy the notes"]
    assert board(scenario).get(task.id).status == "open"


async def test_nudges_waiting_for_the_morning_go_as_one_list(scenario: Scenario) -> None:
    """Bug #49: "The morning summary should be a single message with a list of what's
    happening today, not a whole bunch of prompts"."""
    erin = scenario.member("Erin")
    await scenario.advance(hours=13)  # 22:00, quiet hours
    for title in ("Clean kitchen", "Bring bins in", "Call the vet"):
        await board(scenario).create(erin, title, "errand", 1, THURSDAY, assignee=erin)
    sent = await until(scenario, THURSDAY, 8, 1)
    assert sent == [
        "This morning:\n- Due today: Clean kitchen\n- Due today: Bring bins in\n"
        "- Due today: Call the vet\nTap any that are done; the rest can wait."
    ]
    assert scenario.last_buttons("Erin") == ["✓ Clean kitchen", "✓ Bring bins in", "✓ Call the vet"]

    await scenario.tap("Erin", "✓ Bring bins in")
    edit = scenario.edits("Erin")[-1]
    assert edit["text"] == (  # bug #103: a tick only took the line away; was it done?
        "Marked done: Bring bins in.\n\n"
        "This morning:\n- Due today: Clean kitchen\n- Due today: Call the vet\n"
        "Tap any that are done; the rest can wait."
    )
    assert [
        b["text"] for b in (b for row in edit["reply_markup"]["inline_keyboard"] for b in row)
    ] == [
        "✓ Clean kitchen",
        "✓ Call the vet",
    ]
    assert not any(t.startswith("Due today:") for t in await scenario.advance(hours=1))

    await scenario.tap("Erin", "✓ Clean kitchen")
    await scenario.tap("Erin", "✓ Call the vet")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Marked done: Call the vet. This morning's list: all done."
    )


async def test_later_in_the_day_nudges_still_come_one_at_a_time(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    for title in ("Clean kitchen", "Bring bins in"):
        await board(scenario).create(erin, title, "errand", 1, date(2026, 10, 21), assignee=erin)
    sent = await scenario.advance(minutes=1)
    assert not any(t.startswith("This morning") for t in scenario.inbox("Erin") + sent)
    assert len([t for t in scenario.inbox("Erin") if t.startswith("Due today:")]) == 1
