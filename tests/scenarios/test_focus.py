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
    scenario.primary.queue_tool_call("focus_now", {"spread": False})
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
    scenario.primary.queue_tool_call("focus_now", {"spread": False})
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


# ----- O1b: the rest spread out ------------------------------------------------------------

SPREAD_DAY = (
    "For now, just these:\n"
    "- Mimi pill\n"
    "- 2 pm: Call the vet\n"
    "- Clean the kitchen\n"
    "The rest are spread out, no more than 2 on a day:\n"
    "- Thu 22 Oct: Sort the mail\n"
    "- Fri 23 Oct: Deep clean the oven, Water the plants"
)


async def busy_week(scenario: Scenario) -> None:
    """Erin's full day, at most two a day, and Thursday has one already."""
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, day_budget=2)
    await a_full_day(scenario)
    await task(scenario, "Erin", "Return the library books", WED + timedelta(days=1))


def due_on(scenario: Scenario, title: str) -> date | None:
    erin = scenario.member("Erin")
    return next(t for t in board(scenario).open_for(erin) if t.title == title).due_on


async def test_pare_it_down_and_move_the_rest_in_one_go(scenario: Scenario) -> None:
    """The morning of 2026-10-29 (bugs #84, #85): "pare it down", then "snooze everything
    except...", then one more, each read back; now one exchange."""
    await busy_week(scenario)
    scenario.primary.queue_tool_call("focus_now", {"spread": True})
    scenario.primary.queue_text("Done.")
    replies = await scenario.say("Erin", "Too much today. Pare it down and move the rest")
    assert replies == [SPREAD_DAY, "Done."]
    assert due_on(scenario, "Sort the mail") == WED + timedelta(days=1)
    assert due_on(scenario, "Deep clean the oven") == WED + timedelta(days=2)
    assert due_on(scenario, "Mimi pill") == WED  # the few for now stay


async def test_the_spread_is_offered_and_waits_for_a_yes(scenario: Scenario) -> None:
    await busy_week(scenario)
    scenario.primary.queue_tool_call("focus_now", {"spread": False})
    scenario.primary.queue_text("")
    await scenario.say("Erin", "I'm overwhelmed")
    assert scenario.last_buttons("Erin") == ["Spread them out", "Leave them for now"]
    assert due_on(scenario, "Sort the mail") == WED  # nothing moved yet
    await scenario.tap("Erin", "Spread them out")
    assert scenario.edits("Erin")[-1]["text"] == SPREAD_DAY
    assert due_on(scenario, "Water the plants") == WED + timedelta(days=2)


async def test_left_as_they_are(scenario: Scenario) -> None:
    await busy_week(scenario)
    scenario.primary.queue_tool_call("focus_now", {"spread": False})
    scenario.primary.queue_text("")
    await scenario.say("Erin", "I'm overwhelmed")
    await scenario.tap("Erin", "Leave them for now")
    edit = scenario.edits("Erin")[-1]
    assert edit["text"].endswith("The other 3 stay where they are; nothing's dropped.")
    assert not edit.get("reply_markup", {}).get("inline_keyboard")
    assert due_on(scenario, "Sort the mail") == WED


async def test_a_chore_goes_to_its_next_round_and_a_shared_one_stays_with_the_other(
    scenario: Scenario,
) -> None:
    from themi.core.repeat import parse

    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    scenario.app.store.update_settings(erin, erin.id, day_budget=2)
    for n in range(3):
        await task(scenario, "Erin", f"Errand {n}", importance="high")
    bins = await task(scenario, "Erin", "Bring bins in", None)
    await board(scenario).set_schedule(bins.id, erin, repeat=parse("every Wednesday", WED))
    laundry = await task(scenario, "Erin", "Cycle the laundry")
    await board(scenario).make_either(laundry.id)
    focus = scenario.app.services.focus
    assert focus is not None
    text = await focus.spread_now(erin)
    assert "Wed 28 Oct: Bring bins in" in text  # its next round, not stacked on a day
    assert board(scenario).get(bins.id).due_on == WED + timedelta(days=7)
    assert board(scenario).get(laundry.id).due_on == WED  # still today, for him
    summary = scenario.app.services.day_summary
    assert summary is not None
    assert "Cycle the laundry" in (summary.text(husband, WED) or "")
    assert "Cycle the laundry" not in (summary.text(erin, WED) or "")


async def test_the_budget_is_what_usually_gets_done(scenario: Scenario) -> None:
    from themi import clock

    erin = scenario.member("Erin")
    focus = scenario.app.services.focus
    assert focus is not None
    assert focus.budget(erin) == 4  # nothing done yet to go by
    for day in range(3):  # two things done on each of three days
        for n in range(2):
            done = await task(scenario, "Erin", f"Thing {day}-{n}")
            await board(scenario).complete(done.id, erin)
        clock.advance(timedelta(days=1))
    assert focus.budget(erin) == 2
    scenario.app.store.update_settings(erin, erin.id, day_budget=5)
    assert focus.budget(scenario.member("Erin")) == 5


async def test_how_few_is_their_own_number(scenario: Scenario) -> None:
    """The family's answer to "how few?": each person sets it (three unless they do)."""
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, focus_count=2)
    await a_full_day(scenario)
    focus = scenario.app.services.focus
    assert focus is not None
    few, rest = focus.pick(scenario.member("Erin"))
    assert [t.title for t in few] == ["Mimi pill", "Call the vet"]
    assert len(rest) == 4
