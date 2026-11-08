"""R1b: Themi's routines on the Cozyla wall, both ways. The wall's routines come into Themi
first; then changes in either place reach the other, a change Themi hasn't sent wins, ticks
go both ways, and only Themi checks. The clock starts on Wednesday 21 October 2026, 09:00."""

from __future__ import annotations

from datetime import date, time, timedelta

from tests.fakes.cozyla import FakeCozyla
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi.standard.repeat import parse
from themi.standard.routines import Routines

WED = date(2026, 10, 21)


def routines(scenario: Scenario) -> Routines:
    assert scenario.app.services.maybe(keys.routines) is not None
    return scenario.app.services.get(keys.routines)


async def sync(scenario: Scenario) -> object:
    return await scenario.run_periodic("routines.wall")


def items(scenario: Scenario, name: str, routine: str) -> list[tuple[str, tuple[int, ...]]]:
    found = routines(scenario).find(scenario.member(name), routine)
    assert found is not None
    return [(i.title, i.days) for i in routines(scenario).items(found)]


def on_wall(fake: FakeCozyla, title: str) -> tuple[str, str, str]:
    routine = fake.routine_named(title)
    return routine["memberUid"], routine["routineType"], routine["repeatsIn"] or ""


async def test_the_walls_routines_come_into_themi_first(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    fake_cozyla.add_routine(
        "m-husband", "Cycle dishwasher", "Evening", every="Weekly", days="Tuesday,Thursday"
    )
    start = len(fake_cozyla.paths())
    await sync(scenario)
    assert items(scenario, "Erin", "Morning") == [("Walk dog", ())]
    assert items(scenario, "Husband", "Evening") == [("Cycle dishwasher", (1, 3))]
    writes = [p for p in fake_cozyla.paths()[start:] if "create" in p or "update" in p]
    assert writes == []  # as the wall has them: nothing to send back


async def test_an_item_made_in_themi_goes_on_the_wall_in_its_part(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    erin = scenario.member("Erin")
    before_school, _ = routines(scenario).set(erin, "Before school", time(7), time(8))
    routines(scenario).add_item(before_school, "Packed lunch")
    evening = routines(scenario).find(erin, "Evening")
    assert evening is not None
    routines(scenario).add_item(evening, "Gym bag", (1, 3))
    await sync(scenario)
    assert on_wall(fake_cozyla, "Packed lunch") == ("m-erin", "Morning", "")
    assert on_wall(fake_cozyla, "Gym bag") == ("m-erin", "Evening", "Tuesday,Thursday")

    routines(scenario).set(erin, "Before school", time(14), time(15))  # re-timed
    await sync(scenario)
    assert on_wall(fake_cozyla, "Packed lunch")[1] == "Afternoon"


async def test_changes_on_the_wall_come_into_themi(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    walk = fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    pills = fake_cozyla.add_routine("m-erin", "Take meds", "Morning")
    await sync(scenario)
    fake_cozyla.routines[walk].update(
        routineTitle="Walk the dog", repeatsEvery="Weekly", repeatsIn="Saturday,Sunday"
    )
    fake_cozyla.routines[pills]["routineType"] = "Evening"  # moved on the wall
    fake_cozyla.add_routine("m-erin", "Water plants", "Afternoon")  # made on the wall
    await sync(scenario)
    assert items(scenario, "Erin", "Morning") == [("Walk the dog", (5, 6))]
    assert items(scenario, "Erin", "Evening") == [("Take meds", ())]
    assert items(scenario, "Erin", "Afternoon") == [("Water plants", ())]

    del fake_cozyla.routines[pills]  # deleted on the wall
    await sync(scenario)
    assert items(scenario, "Erin", "Evening") == []


async def test_a_change_themi_hasnt_sent_wins(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    walk = fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    await sync(scenario)
    item = routines(scenario).find_item(scenario.member("Erin"), "walk dog")
    assert item is not None
    scenario.app.db.execute(
        "UPDATE routine_items SET title = 'Walk Mimi' WHERE id = ?", (item.id,)
    )  # changed in Themi...
    fake_cozyla.routines[walk]["routineTitle"] = "Walk the dog"  # ...and on the wall
    await sync(scenario)
    assert items(scenario, "Erin", "Morning") == [("Walk Mimi", ())]
    assert fake_cozyla.routines[walk]["routineTitle"] == "Walk Mimi"


async def test_removed_in_themi_removed_on_the_wall(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    walk = fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    pills = fake_cozyla.add_routine("m-erin", "Take meds", "Evening")
    await sync(scenario)
    item = routines(scenario).find_item(scenario.member("Erin"), "walk dog")
    assert item is not None
    routines(scenario).remove_item(item)
    evening = routines(scenario).find(scenario.member("Erin"), "Evening")
    assert evening is not None
    routines(scenario).remove(evening)  # a whole routine, with its items
    await sync(scenario)
    assert walk not in fake_cozyla.routines and pills not in fake_cozyla.routines


async def test_ticks_go_both_ways(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    walk = fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    pills = fake_cozyla.add_routine("m-erin", "Take meds", "Morning")
    await sync(scenario)
    fake_cozyla.tick_routine(walk, WED)  # on the wall
    await sync(scenario)
    r = routines(scenario)
    walk_item = r.find_item(scenario.member("Erin"), "walk dog")
    pills_item = r.find_item(scenario.member("Erin"), "take meds")
    assert walk_item is not None and pills_item is not None
    assert r.ticked(walk_item, WED)

    scenario.primary.queue_tool_call("tick_routine_item", {"title": "meds"})
    scenario.primary.queue_text("Nice.")
    await scenario.say("Erin", "took my meds")
    assert (pills, WED.isoformat()) in fake_cozyla.routine_ticks  # at once, not next sync


async def test_a_tick_on_the_wall_updates_the_check(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """F23b, bug #129: Cycle Dishwasher, ticked on the wall, stayed on the evening check."""
    meds = fake_cozyla.add_routine("m-erin", "Take meds", "Evening")
    dishwasher = fake_cozyla.add_routine("m-erin", "Cycle dishwasher", "Evening")
    await sync(scenario)
    clock.advance(time_until(20, 30))  # the evening ends an hour before her quiet hours
    await scenario.run_periodic("routines.check")
    await scenario.advance(minutes=20)
    assert scenario.inbox("Erin")[-1] == (
        "Evening routine, still open:\n- Take meds\n- Cycle dishwasher\nDone already?"
    )
    fake_cozyla.tick_routine(dishwasher, WED)
    await sync(scenario)
    edit = scenario.edits("Erin")[-1]
    assert edit["text"] == "Evening routine, still open:\n- Take meds\nDone already?"
    keyboard = edit["reply_markup"]["inline_keyboard"]
    assert [b["text"] for row in keyboard for b in row] == ["✓ Take meds", "Skip today"]
    fake_cozyla.tick_routine(meds, WED)
    await sync(scenario)
    assert scenario.edits("Erin")[-1]["text"] == "Evening routine: all done."


def time_until(hour: int, minute: int = 0) -> timedelta:
    now = clock.now()
    return now.replace(hour=hour, minute=minute) - now


async def test_a_tick_on_the_wall_at_night_gets_a_warm_word(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """Michael, 2026-10-30: three routine items ticked in the evening, no praise. Ticked on
    the wall, after quiet hours have started."""
    from datetime import timedelta

    from themi.standard.praise import PRAISE

    pills = fake_cozyla.add_routine("m-erin", "Take meds", "Evening")
    await sync(scenario)
    clock.advance(timedelta(hours=13, minutes=45))  # 22:45, her quiet hours started at 21:30
    fake_cozyla.tick_routine(pills, WED)
    await sync(scenario)
    await scenario.advance(minutes=2)
    ticked = [t for t in scenario.inbox("Erin") if t.startswith("Ticked off")]
    assert len(ticked) == 1
    assert any(ticked[0] == f"Ticked off on the wall: Take meds. {w}" for w in PRAISE)


async def test_only_themi_checks_the_routines(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")
    await sync(scenario)
    clock.advance(clock.now().replace(hour=12, minute=1) - clock.now())
    await scenario.run_periodic("cozyla.routines")
    await scenario.run_periodic("routines.check")
    await scenario.app.outbox.flush()
    rows = scenario.app.db.query("SELECT text FROM outbox WHERE kind = 'routine'")
    assert [r["text"] for r in rows] == ["Morning routine, still open:\n- Walk dog\nDone already?"]


async def test_themis_check_ins_stay_c3s(scenario: Scenario, fake_cozyla: FakeCozyla) -> None:
    board = scenario.app.services.maybe(keys.taskboard)
    assert board is not None
    erin = scenario.member("Erin")
    run = await board.create(erin, "Go for a run", "physical", 2, assignee=erin, check_in=True)
    await board.set_schedule(run.id, erin, repeat=parse("every Tue and Thu afternoon", WED))
    await scenario.run_periodic("cozyla.routines")  # C3 puts it on the wall
    await sync(scenario)
    assert items(scenario, "Erin", "Afternoon") == []  # not a routine item


async def test_an_untick_on_the_wall_stays_unticked(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    """F31a, bug #169: Cycle Dishwasher, ticked on the wall at night, unticked there in the
    morning, came back at every sync."""
    dishwasher = fake_cozyla.add_routine("m-erin", "Cycle dishwasher", "Evening")
    await sync(scenario)
    fake_cozyla.tick_routine(dishwasher, WED)
    await sync(scenario)
    item = routines(scenario).find_item(scenario.member("Erin"), "cycle dishwasher")
    assert item is not None and routines(scenario).ticked(item, WED)
    await scenario.advance(minutes=2)  # the tick's warm word goes
    sent = len(scenario.inbox("Erin"))
    fake_cozyla.tick_routine(dishwasher, WED, done=False)  # unticked on the wall
    await sync(scenario)
    await sync(scenario)
    assert (dishwasher, WED.isoformat()) not in fake_cozyla.routine_ticks
    assert not routines(scenario).ticked(item, WED)
    await scenario.advance(minutes=2)
    assert len(scenario.inbox("Erin")) == sent  # no message for an untick


async def test_a_tick_that_didnt_reach_the_wall_is_sent_next_sync(
    scenario: Scenario, fake_cozyla: FakeCozyla
) -> None:
    pills = fake_cozyla.add_routine("m-erin", "Take meds", "Morning")
    await sync(scenario)
    fake_cozyla.fail("checkUserRoutine")
    scenario.primary.queue_tool_call("tick_routine_item", {"title": "meds"})
    scenario.primary.queue_text("Nice.")
    await scenario.say("Erin", "took my meds")
    assert (pills, WED.isoformat()) not in fake_cozyla.routine_ticks
    await sync(scenario)
    assert (pills, WED.isoformat()) in fake_cozyla.routine_ticks
    item = routines(scenario).find_item(scenario.member("Erin"), "take meds")
    assert item is not None and routines(scenario).ticked(item, WED)
