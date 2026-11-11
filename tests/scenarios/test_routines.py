"""R1a: routines kept in Themi. Each person's routines have a name and a window; the check
comes as the window ends, listing what's open. Set up and changed in chat. The clock starts
on Wednesday 21 October 2026, 09:00 (Los Angeles); Erin's quiet hours start at 21:30."""

from __future__ import annotations

from datetime import date, time, timedelta

from tests.scenarios.harness import Scenario
from themi import clock
from themi.ai.types import ToolResult
from themi.channels.pauses import EVERYTHING
from themi.core import keys
from themi.standard.praise import PRAISE, TasksPreferences
from themi.standard.routines import Routines

WED = date(2026, 10, 21)


def routines(scenario: Scenario) -> Routines:
    assert scenario.app.services.maybe(keys.routines) is not None
    return scenario.app.services.get(keys.routines)


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> None:
    target = clock.now().replace(
        year=day.year, month=day.month, day=day.day, hour=hour, minute=minute
    )
    clock.advance(target - clock.now())
    await scenario.run_periodic("routines.check")
    await scenario.app.outbox.flush()


def checks(scenario: Scenario, name: str) -> list[str]:
    rows = scenario.app.db.query(
        "SELECT text FROM outbox WHERE member_id = ? AND kind = 'routine' ORDER BY id",
        (scenario.member(name).id,),
    )
    return [r["text"] for r in rows]


def signals(scenario: Scenario, name: str) -> list[tuple[float, str]]:
    rows = scenario.app.db.query(
        "SELECT value, note FROM energy_signals WHERE member_id = ? AND source = 'device_activity'",
        (scenario.member(name).id,),
    )
    return [(r["value"], r["note"]) for r in rows]


def add(scenario: Scenario, name: str, routine: str, title: str, **kw: object) -> None:
    r = routines(scenario)
    found = r.find(scenario.member(name), routine)
    assert found is not None
    r.add_item(found, title, **kw)  # type: ignore[arg-type]


async def test_everyone_starts_with_morning_afternoon_and_evening(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    assert [(r.name, r.starts, r.ends) for r in routines(scenario).of(erin)] == [
        ("Morning", time(8), time(12)),
        ("Afternoon", time(12), time(17)),
        ("Evening", time(17), None),
    ]
    assert routines(scenario).describe(erin) == (  # F40a: one plain line when all are empty
        "Erin's routines in Themi have nothing on them for today, Wednesday 21 October."
    )


async def test_the_check_comes_as_the_window_ends_and_ticks_from_buttons(
    scenario: Scenario,
) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    add(scenario, "Erin", "Morning", "Make the bed")
    await at(scenario, WED, 11, 59)
    assert checks(scenario, "Erin") == []
    await at(scenario, WED, 12, 0)
    assert checks(scenario, "Erin") == [
        "Morning routine, still open:\n- Vitamins\n- Make the bed\nDone already?"
    ]
    assert scenario.last_buttons("Erin") == ["✓ Vitamins", "✓ Make the bed", "Skip today"]
    assert signals(scenario, "Erin") == [
        (-0.5, "morning routine not finished (Vitamins and Make the bed)")
    ]
    await at(scenario, WED, 12, 30)
    assert len(checks(scenario, "Erin")) == 1  # once a day

    await scenario.tap("Erin", "✓ Vitamins")  # a warm word too, as for a task (F19b)
    edited = scenario.edits("Erin")[-1]["text"]
    assert any(
        edited
        == f"Marked done: Vitamins. {word}\n\n"
        + ("Morning routine, still open:\n- Make the bed\nDone already?")
        for word in PRAISE
    )
    await scenario.tap("Erin", "✓ Make the bed")
    edited = scenario.edits("Erin")[-1]["text"]
    assert any(
        edited == f"Marked done: Make the bed. {word} Morning routine: all done." for word in PRAISE
    )


async def test_no_warm_word_for_a_routine_tick_when_its_off(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, TasksPreferences, done_praise=False)
    add(scenario, "Erin", "Morning", "Vitamins")
    await at(scenario, WED, 12, 0)
    await scenario.tap("Erin", "✓ Vitamins")
    assert scenario.edits("Erin")[-1]["text"] == "Morning routine: all done."


async def test_skip_today(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    await at(scenario, WED, 12)
    await scenario.tap("Erin", "Skip today")
    assert scenario.edits("Erin")[-1]["text"] == "Morning routine: left for today."


async def test_all_done_sends_nothing_and_lifts_energy(scenario: Scenario) -> None:
    add(scenario, "Erin", "Afternoon", "Walk the dog")
    r = routines(scenario)
    item = r.find_item(scenario.member("Erin"), "walk the dog")
    assert item is not None
    r.tick(item, WED)
    await at(scenario, WED, 17)
    assert checks(scenario, "Erin") == []
    assert signals(scenario, "Erin") == [(0.5, "afternoon routine done")]


async def test_the_evening_ends_an_hour_before_quiet_hours(scenario: Scenario) -> None:
    add(scenario, "Erin", "Evening", "Lock the door")
    await at(scenario, WED, 20, 29)
    assert checks(scenario, "Erin") == []
    await at(scenario, WED, 20, 30)
    assert checks(scenario, "Erin") == [
        "Evening routine, still open:\n- Lock the door\nDone already?"
    ]


async def test_items_on_set_days_and_just_today(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Gym bag", days=(1, 3))  # Tuesdays and Thursdays
    add(scenario, "Erin", "Morning", "Sign the form", only_on=WED)
    await at(scenario, WED, 12)
    assert checks(scenario, "Erin") == [
        "Morning routine, still open:\n- Sign the form\nDone already?"
    ]
    await at(scenario, WED + timedelta(days=1), 12)  # Thursday
    assert checks(scenario, "Erin")[-1] == "Morning routine, still open:\n- Gym bag\nDone already?"


async def test_a_late_check_isnt_sent(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    await at(scenario, WED, 17, 1)  # more than five hours after the window ended
    assert checks(scenario, "Erin") == []


async def test_a_custom_routine_from_chat(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "set_routine", {"name": "Before school", "starts": "07:00", "ends": "08:00", "new_name": ""}
    )
    scenario.primary.queue_text("Done: Before school, 7 to 8.")
    await scenario.say("Erin", "add a Before school routine from 7 to 8")
    scenario.primary.queue_tool_call(
        "add_routine_item",
        {"routine": "Before school", "title": "Packed lunch", "days": [], "just_today": False,
         "person": ""},
    )  # fmt: skip
    scenario.primary.queue_text("Added.")
    await scenario.say("Erin", "add packed lunch to my before school routine")
    erin = scenario.member("Erin")
    found = routines(scenario).find(erin, "before school")
    assert found is not None and (found.starts, found.ends) == (time(7), time(8))
    assert [i.title for i in routines(scenario).items(found)] == ["Packed lunch"]  # no card

    await at(scenario, WED + timedelta(days=1), 8)
    assert checks(scenario, "Erin") == [
        "Before school routine, still open:\n- Packed lunch\nDone already?"
    ]


async def test_ticking_and_removing_from_chat(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "vitamins"})
    # F33a: done as they said it, the tool's line is the reply, with no second round
    assert await scenario.say("Erin", "took my vitamins") == ['Ticked "Vitamins" for today.']
    await at(scenario, WED, 12)
    assert checks(scenario, "Erin") == []

    scenario.primary.queue_tool_call("remove_routine_item", {"title": "vitamins", "routine": ""})
    assert await scenario.say("Erin", "take vitamins off my routine") == [
        'Removed "Vitamins" from your Morning routine.'
    ]
    erin = scenario.member("Erin")
    morning = routines(scenario).find(erin, "Morning")
    assert morning is not None and routines(scenario).items(morning) == []


async def test_a_tick_in_chat_updates_the_check(scenario: Scenario) -> None:
    """F23b, bug #129: the check follows a tick made anywhere, not only its own buttons."""
    add(scenario, "Erin", "Morning", "Vitamins")
    add(scenario, "Erin", "Morning", "Make the bed")
    await at(scenario, WED, 12)
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "vitamins"})
    scenario.primary.queue_text("Nice.")
    await scenario.say("Erin", "took my vitamins")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Morning routine, still open:\n- Make the bed\nDone already?"
    )


async def test_a_skipped_check_stays_skipped(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    add(scenario, "Erin", "Morning", "Make the bed")
    await at(scenario, WED, 12)
    await scenario.tap("Erin", "Skip today")
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "vitamins"})
    scenario.primary.queue_text("Nice.")
    await scenario.say("Erin", "took my vitamins")
    assert scenario.edits("Erin")[-1]["text"] == "Morning routine: left for today."


async def test_a_held_check_is_written_again_as_it_goes(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    add(scenario, "Erin", "Morning", "Vitamins")
    add(scenario, "Erin", "Morning", "Make the bed")
    scenario.app.outbox.pauses.pause(erin, EVERYTHING, clock.now().replace(hour=13))
    await at(scenario, WED, 12)
    r = routines(scenario)
    vitamins = r.find_item(erin, "vitamins")
    assert vitamins is not None
    await r.tick_now(vitamins, WED)
    await at(scenario, WED, 13)
    assert (
        scenario.inbox("Erin")[-1] == "Morning routine, still open:\n- Make the bed\nDone already?"
    )
    assert scenario.last_buttons("Erin") == ["✓ Make the bed", "Skip today"]


async def test_a_held_check_with_nothing_left_is_dropped(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    add(scenario, "Erin", "Morning", "Vitamins")
    scenario.app.outbox.pauses.pause(erin, EVERYTHING, clock.now().replace(hour=13))
    await at(scenario, WED, 12)
    vitamins = routines(scenario).find_item(erin, "vitamins")
    assert vitamins is not None
    await routines(scenario).tick_now(vitamins, WED)
    await at(scenario, WED, 13)
    assert not any("routine" in t for t in scenario.inbox("Erin"))


async def test_an_item_for_someone_elses_routine_asks_first(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "add_routine_item",
        {"routine": "Evening", "title": "Feed the birds", "days": [], "just_today": False,
         "person": "Husband"},
    )  # fmt: skip
    scenario.primary.queue_text("I'll check first.")
    await scenario.say("Erin", "put feed the birds on his evening routine")
    husband = scenario.member("Husband")
    evening = routines(scenario).find(husband, "Evening")
    assert evening is not None and routines(scenario).items(evening) == []
    await scenario.tap("Erin", "Go ahead")
    assert [i.title for i in routines(scenario).items(evening)] == ["Feed the birds"]


# ----- F33c (reply 237): a near name is found, and a miss says what's there --------------


def tool_results(scenario: Scenario, name: str) -> list[str]:
    rows = scenario.app.db.query(
        "SELECT result FROM reply_tools WHERE name = ? ORDER BY id", (name,)
    )
    return [r["result"] for r in rows]


def evening_items(scenario: Scenario, name: str = "Erin") -> list[str]:
    evening = routines(scenario).find(scenario.member(name), "Evening")
    assert evening is not None
    return [i.title for i in routines(scenario).items(evening)]


async def test_reply_237_a_near_name_is_removed(scenario: Scenario) -> None:
    for title in ("Cycle Dishwasher", "Take Meds", "Cover the birdcage", "Refill cat feeders"):
        add(scenario, "Erin", "Evening", title)
    scenario.primary.queue_tool_call(
        "remove_routine_item", {"title": "regular cat feeders", "routine": "Evening"}
    )
    scenario.primary.queue_text("Removed Refill cat feeders.")
    replies = await scenario.say("Erin", "Remove the regular cat feeders from my evening routine")
    assert evening_items(scenario) == ["Cycle Dishwasher", "Take Meds", "Cover the birdcage"]
    # a near match isn't in her words (F33a), so the model's round names the real item
    assert scenario.primary.pending() == 0
    assert replies == ["Removed Refill cat feeders."]
    assert tool_results(scenario, "remove_routine_item") == [
        'Removed "Refill cat feeders" from your Evening routine.'
    ]


async def test_two_near_names_remove_neither_and_are_named(scenario: Scenario) -> None:
    add(scenario, "Erin", "Evening", "Refill cat feeders")
    add(scenario, "Erin", "Evening", "Clean cat feeders")
    scenario.primary.queue_tool_call(
        "remove_routine_item", {"title": "wash cat feeders", "routine": "Evening"}
    )
    scenario.primary.queue_text("Which one?")
    await scenario.say("Erin", "Remove wash cat feeders from my evening routine")
    assert evening_items(scenario) == ["Refill cat feeders", "Clean cat feeders"]
    (result,) = tool_results(scenario, "remove_routine_item")
    assert result.startswith("No item like wash cat feeders on Erin's Evening routine.")
    assert "More than one is close: Refill cat feeders, Clean cat feeders." in result


async def test_a_miss_lists_the_routine_closest_first(scenario: Scenario) -> None:
    for title in ("Cycle Dishwasher", "Take Meds", "Refill the vacuum's clean water"):
        add(scenario, "Erin", "Evening", title)
    scenario.primary.queue_tool_call(
        "remove_routine_item", {"title": "empty the vacuum", "routine": "Evening"}
    )
    scenario.primary.queue_text("I couldn't find that one.")
    await scenario.say("Erin", "Take empty the vacuum off my evening routine")
    (result,) = tool_results(scenario, "remove_routine_item")
    assert result == (
        "No item like empty the vacuum on Erin's Evening routine. It has: Refill the "
        "vacuum's clean water, Cycle Dishwasher, Take Meds. Nothing was changed."
    )


async def test_a_miss_with_no_routine_named_lists_each(scenario: Scenario) -> None:
    add(scenario, "Erin", "Morning", "Vitamins")
    add(scenario, "Erin", "Evening", "Take Meds")
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "stretches"})
    scenario.primary.queue_text("That isn't on your routines.")
    await scenario.say("Erin", "did my stretches")
    (result,) = tool_results(scenario, "tick_routine_item")
    assert result == (
        "No item like stretches on Erin's routines. Morning: Vitamins. Evening: Take Meds. "
        "Nothing was changed."
    )


async def test_an_add_in_a_removal_message_is_declined(scenario: Scenario) -> None:
    # F33d (reply 237): asked to remove it, the model staged adding it
    add(scenario, "Erin", "Evening", "Refill cat feeders")
    scenario.primary.queue_tool_call(
        "add_routine_item",
        {"title": "Refill cat feeders", "routine": "Evening", "days": [], "person": "",
         "just_today": False},
    )  # fmt: skip
    scenario.primary.queue_text("Which one did you mean?")
    await scenario.say("Erin", "Remove the regular cat feeders from my evening routine")
    assert scenario.app.db.query("SELECT * FROM pending_actions") == []
    assert evening_items(scenario) == ["Refill cat feeders"]
    (result,) = tool_results(scenario, "add_routine_item")
    assert result.startswith("Refill cat feeders is already on the Evening routine")


# ----- F40a, bug #195: "What's my routine for tomorrow?" --------------------------------

MON = date(2026, 10, 26)


def michaels_evening(scenario: Scenario) -> None:
    """Michael's evening on the Pi: bins on Tuesdays, Take Meds ticked tonight."""
    add(scenario, "Husband", "Evening", "Cycle Dishwasher")
    add(scenario, "Husband", "Evening", "Take out bins", days=(1,))
    add(scenario, "Husband", "Evening", "Take Meds")
    add(scenario, "Husband", "Evening", "Cover the birdcage")


async def at_night(scenario: Scenario, day: date) -> None:
    target = clock.now().replace(year=day.year, month=day.month, day=day.day, hour=23, minute=7)
    clock.advance(target - clock.now())


async def test_tomorrows_routine_lists_tomorrows_items(scenario: Scenario) -> None:
    michaels_evening(scenario)
    await at_night(scenario, MON)
    michael = scenario.member("Husband")
    r = routines(scenario)
    evening = r.find(michael, "Evening")
    assert evening is not None
    meds = next(i for i in r.items(evening) if i.title == "Take Meds")
    r.tick(meds, MON)

    assert r.describe(michael, MON + timedelta(days=1)) == (
        "Husband's routines in Themi for Tuesday 27 October: Evening (5 pm to an hour before "
        "your quiet hours): Cycle Dishwasher, Take out bins, Take Meds, Cover the birdcage. "
        "Morning and Afternoon have nothing on them that day."
    )
    assert r.describe(michael, MON + timedelta(days=2)) == (
        "Husband's routines in Themi for Wednesday 28 October: Evening (5 pm to an hour "
        "before your quiet hours): Cycle Dishwasher, Take Meds, Cover the birdcage. "
        "Morning and Afternoon have nothing on them that day."
    )
    assert r.describe(michael) == (
        "Husband's routines in Themi for today, Monday 26 October: Evening (5 pm to an hour "
        "before your quiet hours): Cycle Dishwasher, Take Meds (done), Cover the birdcage. "
        "Morning and Afternoon have nothing on them today."
    )


async def test_asked_in_chat_for_tomorrow(scenario: Scenario) -> None:
    michaels_evening(scenario)
    await at_night(scenario, MON)
    scenario.primary.queue_tool_call("show_routines", {"day": "tomorrow"})
    scenario.primary.queue_text("Tomorrow evening: dishwasher, bins, meds, birdcage.")
    await scenario.say("Husband", "What's my routine for tomorrow?")
    result = [
        block
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1].content
    assert result.startswith("Husband's routines in Themi for Tuesday 27 October: Evening")
    assert "Take out bins," in result and "(on Tuesdays)" not in result
    assert "done" not in result.split(":", 1)[1].split(".")[0]


async def test_the_day_argument_reads_weekdays_and_dates(scenario: Scenario) -> None:
    from themi.standard.routines import routine_day

    assert routine_day("", MON) == MON
    assert routine_day("today", MON) == MON
    assert routine_day("Tomorrow", MON) == MON + timedelta(days=1)
    assert routine_day("wednesday", MON) == MON + timedelta(days=2)
    assert routine_day("Monday", MON) == MON  # its own name: today
    assert routine_day("2026-10-30", MON) == date(2026, 10, 30)


async def test_nothing_at_all_that_day_is_one_plain_line(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    assert routines(scenario).describe(erin, WED + timedelta(days=1)) == (
        "Erin's routines in Themi have nothing on them for Thursday 22 October."
    )
