"""R1a: routines kept in Themi. Each person's routines have a name and a window; the check
comes as the window ends, listing what's open. Set up and changed in chat. The clock starts
on Wednesday 21 October 2026, 09:00 (Los Angeles); Erin's quiet hours start at 21:30."""

from __future__ import annotations

from datetime import date, time, timedelta

from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.routines import Routines

WED = date(2026, 10, 21)


def routines(scenario: Scenario) -> Routines:
    assert scenario.app.services.routines is not None
    return scenario.app.services.routines


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
    assert routines(scenario).describe(erin) == (
        "Erin's routines in Themi: Morning (8 am to 12 pm): nothing on it yet. "
        "Afternoon (12 pm to 5 pm): nothing on it yet. Evening (5 pm to an hour before your "
        "quiet hours): nothing on it yet."
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

    await scenario.tap("Erin", "✓ Vitamins")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Morning routine, still open:\n- Make the bed\nDone already?"
    )
    await scenario.tap("Erin", "✓ Make the bed")
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
    await at(scenario, WED, 15, 1)  # more than three hours after the window ended
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
    scenario.primary.queue_text("Nice.")
    await scenario.say("Erin", "took my vitamins")
    await at(scenario, WED, 12)
    assert checks(scenario, "Erin") == []

    scenario.primary.queue_tool_call("remove_routine_item", {"title": "vitamins", "routine": ""})
    scenario.primary.queue_text("Gone.")
    await scenario.say("Erin", "take vitamins off my routine")
    erin = scenario.member("Erin")
    morning = routines(scenario).find(erin, "Morning")
    assert morning is not None and routines(scenario).items(morning) == []


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
