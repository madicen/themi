"""V1: the robot vacuum's chores. When it needs a hand (stuck, a jam, the dock's water, a worn
part) whoever has more room hears about it, 5 minutes on, with the room it's in; the robot
sorting itself takes the nudge back; once sorted, Themi offers to clear its alert and send
it home. The clock starts on Wednesday 21 October 2026, 09:00 (Los Angeles); the vacuum is
a Roborock S8 MaxV Ultra."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from tests.fakes.roborock import CODE, EMAIL, FakeRoborock
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_appliance_status import ask, tool_names
from themi import clock
from themi.core.vacuum import CATEGORY, EXPIRED_TEXT

ROBOT = "rr-duid-1"
STUCK_IN_KITCHEN = (
    "The vacuum's stuck in the kitchen (it's trapped). Free it and pop it back on the dock?"
)


@pytest.fixture
async def robot(scenario: Scenario, fake_roborock: FakeRoborock) -> FakeRoborock:
    """The vacuum, linked and read once (the starting point: on its dock)."""
    fake_roborock.add_robot(ROBOT, "Robbie")
    fake_roborock.rooms[ROBOT] = "Kitchen"
    watcher = scenario.app.services.roborock
    assert watcher is not None
    await watcher.send_code(EMAIL)
    await watcher.link(scenario.member("Erin"), EMAIL, CODE)
    await scenario.run_periodic("devices.vacuum")
    return fake_roborock


async def seen(scenario: Scenario, fake: FakeRoborock, status: str, **changes: object) -> None:
    """The robot reports `status`, and a read comes round (at most 5 minutes on)."""
    fake.set_status(ROBOT, status, **changes)
    clock.advance(timedelta(minutes=5))
    await scenario.run_periodic("devices.vacuum")
    await scenario.app.outbox.flush()


def tasks(scenario: Scenario) -> list[tuple[str, str, int]]:
    return [
        (r["title"], r["status"], r["assignee"])
        for r in scenario.app.db.query("SELECT * FROM tasks ORDER BY id")
    ]


def tired(scenario: Scenario) -> None:
    scenario.app.services.energy.record(scenario.member("Erin"), "text_note", -3, "worn out")


async def test_linking_from_the_family_page(
    scenario: Scenario, site: httpx.AsyncClient, fake_roborock: FakeRoborock
) -> None:
    fake_roborock.add_robot(ROBOT, "Robbie")
    await sign_in(scenario, site, "Erin")
    page = await site.get("/family")
    assert "Robot vacuum" in page.text and "Send code" in page.text
    asked = await site.post(
        "/family/roborock/code", data={"csrf": csrf_of(page.text), "email": EMAIL}
    )
    assert asked.status_code == 200
    assert f"The code Roborock emailed to {EMAIL}" in asked.text
    done = await site.post(
        "/family/roborock/link",
        data={"csrf": csrf_of(asked.text), "email": EMAIL, "code": CODE},
    )
    assert done.status_code == 303
    page_text = await flash(site, "/family")
    assert "Linked Roborock. Found Robbie." in page_text
    assert f"Signed in as {EMAIL}" in page_text


async def test_only_an_admin_links_it(
    scenario: Scenario, site: httpx.AsyncClient, fake_roborock: FakeRoborock
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    response = await site.post("/family/roborock/code", data={"csrf": csrf, "email": EMAIL})
    assert response.status_code == 403
    assert fake_roborock.codes_sent == []


async def test_stuck_in_the_kitchen_goes_to_whoever_has_more_room(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)
    husband = scenario.member("Husband")
    await seen(scenario, robot, "trapped")
    assert tasks(scenario) == [("Free the stuck vacuum", "open", husband.id)]
    assert await scenario.advance(minutes=4) == []  # it might free itself
    assert await scenario.advance(minutes=1) == [STUCK_IN_KITCHEN]
    assert scenario.inbox("Husband") == [STUCK_IN_KITCHEN]
    assert scenario.last_buttons("Husband") == ["Done", "Later"]
    assert scenario.inbox("Erin") == []
    clock.advance(timedelta(minutes=1))
    await scenario.run_periodic("devices.vacuum")  # still stuck: no second task
    assert len(tasks(scenario)) == 1


async def test_freeing_itself_in_five_minutes_sends_nothing(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    await seen(scenario, robot, "trapped")
    clock.advance(timedelta(minutes=2))
    robot.set_status(ROBOT, "cleaning")
    await scenario.run_periodic("devices.vacuum")
    assert tasks(scenario)[0][1] == "cancelled"
    assert await scenario.advance(hours=1) == []
    assert scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'vacuum'") == []
    assert scenario.app.db.query("SELECT 1 FROM pending_actions") == []  # it's cleaning: no offer


async def test_out_of_clean_water_and_the_alert_cleared_after_done(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)
    await seen(scenario, robot, "clean_water_empty")
    assert tasks(scenario)[0][0] == "Refill the vacuum's clean water"
    assert await scenario.advance(minutes=5) == [
        "The vacuum's dock is out of clean water. Refill the tank?"
    ]
    # Refilled; the dock's alert stays until it's cleared.
    await scenario.tap("Husband", "Done")
    assert tasks(scenario)[0][1] == "done"
    assert scenario.inbox("Husband")[-1] == "Clear the vacuum's alert\nGo ahead, or not now?"
    await scenario.tap("Husband", "Go ahead")
    assert robot.resolved == [(ROBOT, 38)]
    assert robot.sent_home == []  # it's on its dock
    await seen(scenario, robot, "docked")
    assert len(tasks(scenario)) == 1  # gone now; nothing new


async def test_a_done_alert_isnt_raised_again_until_its_gone(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    await seen(scenario, robot, "dirty_water_full")
    await scenario.advance(minutes=5)
    who = "Erin" if scenario.inbox("Erin") else "Husband"
    await scenario.tap(who, "Done")
    await scenario.tap(who, "Not now")  # the alert stays on the robot
    await seen(scenario, robot, "dirty_water_full")
    assert len(tasks(scenario)) == 1
    await seen(scenario, robot, "docked")
    await seen(scenario, robot, "dirty_water_full")  # full again: a new chore
    assert [t[0] for t in tasks(scenario)] == ["Empty the vacuum's dirty water"] * 2


async def test_the_robot_showing_it_sorted_closes_a_sent_nudge(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)
    await seen(scenario, robot, "clean_water_empty")
    await scenario.advance(minutes=5)
    await seen(scenario, robot, "docked")  # refilled, and cleared in the app
    assert tasks(scenario)[0][1] == "done"
    assert scenario.edits("Husband")[-1]["text"] == (
        "Marked done: Refill the vacuum's clean water. Thank you."
    )


async def test_a_jam_sorted_then_sent_home_with_a_yes(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)
    await seen(scenario, robot, "main_brush_jammed")
    assert await scenario.advance(minutes=5) == [
        "The vacuum needs a hand: the main brush is jammed. Clear it when you can?"
    ]
    clock.advance(timedelta(minutes=10))
    robot.set_status(ROBOT, "idle_away")  # cleared, left where it stopped
    await scenario.run_periodic("devices.vacuum")
    await scenario.app.outbox.flush()
    assert tasks(scenario)[0][1] == "done"
    assert scenario.inbox("Husband")[-1] == (
        "Send the vacuum back to its dock\nGo ahead, or not now?"
    )
    await scenario.tap("Husband", "Go ahead")
    assert robot.sent_home == [ROBOT]
    # Heading home, the "not back on its dock" chore goes before it was ever sent.
    await scenario.run_periodic("devices.vacuum")
    assert await scenario.advance(hours=1) == []
    assert [t[1] for t in tasks(scenario)] == ["done", "cancelled"]


async def test_with_the_rule_on_its_sent_home_without_asking(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)
    scenario.app.services.autonomy.grant_tier2(CATEGORY, via_rule_id=1, by=scenario.member("Erin"))
    await seen(scenario, robot, "trapped")
    await scenario.advance(minutes=5)
    await scenario.tap("Husband", "Done")  # freed, but it still shows the alert
    assert robot.resolved == [(ROBOT, 8)]
    assert robot.sent_home == [ROBOT]
    assert not any("Go ahead" in text for text in scenario.inbox("Husband"))


async def test_left_off_its_dock_waits_half_an_hour_then_names_the_room(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)
    robot.rooms[ROBOT] = "Erin's office"
    await seen(scenario, robot, "battery_flat_away")
    assert tasks(scenario)[0][0] == "Put the vacuum back on its dock"
    assert await scenario.advance(minutes=29) == []
    assert await scenario.advance(minutes=1) == [
        "The vacuum didn't make it back to its dock in Erin's office (its battery ran low). "
        "Carry it back?"
    ]


async def test_paused_vacuum_nudges_wait(scenario: Scenario, robot: FakeRoborock) -> None:
    tired(scenario)
    await scenario.say("Husband", "/pause vacuum 2 hours")
    await seen(scenario, robot, "trapped")
    assert STUCK_IN_KITCHEN not in await scenario.advance(minutes=30)
    assert STUCK_IN_KITCHEN in await scenario.advance(hours=2)


async def test_a_worn_part_makes_one_chore(scenario: Scenario, robot: FakeRoborock) -> None:
    tired(scenario)
    robot.set_parts(ROBOT, filter_work_time=530_000)
    for _ in range(3):
        clock.advance(timedelta(hours=6))
        await scenario.run_periodic("devices.vacuum")
    await scenario.app.outbox.flush()
    assert [t[0] for t in tasks(scenario)] == ["Replace the vacuum's filter"]
    assert "The vacuum's filter is nearly worn out. Replace it when you can?" in (
        scenario.inbox("Husband")
    )


async def test_a_sign_in_that_stops_working_tells_the_admin_once(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    robot.expire()
    await seen(scenario, robot, "trapped")
    await seen(scenario, robot, "trapped")
    assert scenario.inbox("Erin") == [EXPIRED_TEXT]  # the admin, once
    assert scenario.inbox("Husband") == []
    assert tasks(scenario) == []


async def test_asked_how_the_vacuum_is_doing_it_looks(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    robot.set_status(ROBOT, "main_brush_jammed")
    said = await ask(scenario, "How's the robot vacuum doing?", "vacuum")
    assert "appliance_status" in tool_names(scenario)  # the words chose the devices group
    assert "Robbie (vacuum), read just now: stopped with a problem, battery 55%" in said
    assert "it needs a hand: the main brush is jammed" in said


WATER = "The vacuum's dock is out of clean water. Refill the tank?"


async def test_out_of_water_overnight_its_for_either_of_you(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    """F23d: at 4:47 am it went to Erin, asked at 8; Michael saw nothing of it."""
    clock.advance(timedelta(hours=19, minutes=40))  # Thu 4:40 am: both asleep
    await seen(scenario, robot, "clean_water_empty")
    (row,) = scenario.app.db.query("SELECT * FROM tasks")
    assert row["either"] and row["shared"]
    assert await scenario.advance(hours=2, minutes=10) == []  # 6:55: still his quiet hours
    assert await scenario.advance(minutes=10) == [WATER]  # 7:05: they ended at 7
    assert scenario.inbox("Husband") == [WATER] and scenario.inbox("Erin") == []
    await scenario.tap("Husband", "Done")
    assert tasks(scenario)[0][1] == "done"
    await scenario.advance(hours=1, minutes=30)  # past 8 am
    assert WATER not in scenario.inbox("Erin")


async def test_out_of_water_overnight_both_are_asked(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    clock.advance(timedelta(hours=19, minutes=40))
    await seen(scenario, robot, "clean_water_empty")
    await scenario.advance(hours=3, minutes=30)  # 8:15 am, nobody has answered
    assert scenario.inbox("Husband") == [WATER]
    assert scenario.inbox("Erin") == [WATER]


async def test_asked_how_the_vacuum_is_the_chore_and_whose_it_is(
    scenario: Scenario, robot: FakeRoborock
) -> None:
    tired(scenario)  # Michael has more room: it's his
    await seen(scenario, robot, "clean_water_empty")
    said = await ask(scenario, "What's the state of the vacuum?", "vacuum")
    assert "Open chore: Refill the vacuum's clean water, Husband's, not asked yet" in said
    await scenario.advance(minutes=5)
    said = await ask(scenario, "And now?", "vacuum")
    assert "Open chore: Refill the vacuum's clean water, Husband's, asked at 9:10 am" in said
