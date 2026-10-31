"""O1 (Erin's idea #94): "only surfaces a small number of tasks to focus on for now ... and
reassures the user that all the other tasks are also being remembered". For anyone who
sounds overwhelmed, in any words. The clock starts on Wednesday 21 October 2026 at 09:00,
Pacific time."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult
from themi.core.focus import SIGNAL, overwhelmed
from themi.core.tasks import Task, TaskBoard

WED = date(2026, 10, 21)


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def task(
    scenario: Scenario,
    name: str,
    title: str,
    due: date | None = WED,
    *,
    effort: int = 2,
    importance: str = "normal",
    due_time: time | None = None,
) -> Task:
    member = scenario.member(name)
    return await board(scenario).create(
        member, title, "errand", effort, due, assignee=member, nudge=False,
        importance=importance, due_time=due_time,
    )  # fmt: skip


async def a_full_day(scenario: Scenario, name: str = "Erin") -> None:
    await task(scenario, name, "Sort the mail", effort=1)
    await task(scenario, name, "Deep clean the oven", effort=3)
    await task(scenario, name, "Water the plants", importance="low")
    await task(scenario, name, "Clean the kitchen", importance="high")
    await task(scenario, name, "Call the vet", due_time=time(14))
    await task(scenario, name, "Mimi pill")  # a medicine, from its title
    await task(scenario, name, "Pay the water bill", WED + timedelta(days=3))  # not today's
    await task(scenario, name, "Someday thing", None)  # no date


def tool_result(scenario: Scenario) -> str:
    return str(
        [
            b.content
            for m in scenario.primary.last_request.messages
            for b in m.content
            if isinstance(b, ToolResult)
        ][-1]
    )


def turn(scenario: Scenario) -> str:
    return str(scenario.primary.requests[0].messages[0].content[0])


@pytest.mark.parametrize("name", ["Erin", "Husband"])
async def test_a_few_things_for_now_and_the_rest_kept(scenario: Scenario, name: str) -> None:
    """Anyone in the family, not only the one who asked for it."""
    await a_full_day(scenario, name)
    scenario.primary.queue_tool_call("focus_now", {})
    scenario.primary.queue_text("One thing at a time.")
    replies = await scenario.say(name, "I'm completely overwhelmed today")
    assert SIGNAL in turn(scenario)
    assert replies == [
        "For now, just these:\n"
        "- Mimi pill\n"
        "- 2 pm: Call the vet\n"
        "- Clean the kitchen\n"
        "The other 3 are kept; nothing's dropped.",
        "One thing at a time.",
    ]
    assert "Don't repeat it" in tool_result(scenario)


async def test_a_long_reply_after_it_isnt_sent(scenario: Scenario) -> None:
    await a_full_day(scenario)
    scenario.primary.queue_tool_call("focus_now", {})
    scenario.primary.queue_text("Here are your tasks:\n- Mimi pill\n- Call the vet\n- The rest")
    replies = await scenario.say("Erin", "Can you pare today down?")
    assert len(replies) == 1 and replies[0].startswith("For now, just these:")


async def test_with_little_on_it_says_so(scenario: Scenario) -> None:
    await task(scenario, "Erin", "Call the vet")
    focus = scenario.app.services.focus
    assert focus is not None
    few, rest = focus.pick(scenario.member("Erin"))
    assert focus.text(scenario.member("Erin"), few, rest) == (
        "For now, just this:\n- Call the vet\nThat's all there is for today."
    )
    await board(scenario).complete(few[0].id, scenario.member("Erin"))
    few, rest = focus.pick(scenario.member("Erin"))
    assert focus.text(scenario.member("Erin"), few, rest) == "Nothing's due today. All clear."


async def test_medicines_are_never_left_out(scenario: Scenario) -> None:
    for n in range(4):
        await task(scenario, "Erin", f"Pill {n}")
    await task(scenario, "Erin", "Call the vet", due_time=time(14))
    focus = scenario.app.services.focus
    assert focus is not None
    few, rest = focus.pick(scenario.member("Erin"))
    assert [t.title for t in few] == [f"Pill {n}" for n in range(4)]
    assert [t.title for t in rest] == ["Call the vet"]


async def test_too_much_today_on_the_morning_list(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    await scenario.advance(hours=13)  # 22:00, quiet hours
    for title in ("Clean kitchen", "Bring bins in", "Call the vet", "Sort the mail"):
        await board(scenario).create(
            erin, title, "errand", 1, WED + timedelta(days=1), assignee=erin
        )
    await scenario.advance(hours=10, minutes=1)  # Thursday, 8:01
    assert scenario.last_buttons("Erin")[-1] == "Too much today"
    await scenario.tap("Erin", "Too much today")
    assert scenario.inbox("Erin")[-1].startswith("For now, just these:\n")
    assert scenario.inbox("Erin")[-1].endswith("The other one is kept; nothing's dropped.")


async def test_no_signal_without_the_words(scenario: Scenario) -> None:
    scenario.primary.queue_text("Sure.")
    await scenario.say("Husband", "What's for dinner?")
    assert SIGNAL not in turn(scenario)


@pytest.mark.parametrize(
    "said",
    [
        "I'm overwhelmed",
        "this is too much",
        "It's all too much right now",
        "I can't keep up",
        "today needs to be pared down",
        "pare it down please",
        "I'm swamped",
        "I'm drowning here",
        "so much to do and no time",
        "everything's too much",
    ],
)
def test_the_words_that_signal_it(said: str) -> None:
    assert overwhelmed(said)


@pytest.mark.parametrize("said", ["Too much salt in the soup", "Add milk to the list"])
def test_words_that_dont(said: str) -> None:
    assert not overwhelmed(said)
