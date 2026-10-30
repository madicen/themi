"""H1: the dishwasher, read from Home Connect. Linked from the Family page; a cycle starting
checks off the dishwasher on the wall's routines and Themi's tasks; fewer runs than usual is
a "running behind" sign. The clock starts on Wednesday 21 October 2026, 09:00 (Los Angeles)."""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.home_connect import FakeHomeConnect
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core.dishwasher import CATEGORY
from themi.core.tasks import TaskBoard

WED = date(2026, 10, 21)
DISHWASHER = "BOSCH-SMV-1"


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


async def link(scenario: Scenario, site: httpx.AsyncClient, fake: FakeHomeConnect) -> str:
    """Erin (an admin) links Home Connect from the Family page; returns the page's message."""
    await sign_in(scenario, site, "Erin")
    family_page = await site.get("/family")
    started = await site.post("/family/home-connect/link", data={"csrf": csrf_of(family_page.text)})
    assert started.status_code == 303
    state, code = fake.approve(started.headers["location"])
    back = await site.get(f"/auth/home-connect/callback?state={state}&code={code}")
    assert back.status_code == 303 and back.headers["location"] == "/family"
    return await flash(site, "/family")


async def at(scenario: Scenario, day: date, hour: int, minute: int = 0) -> None:
    target = clock.now().replace(
        year=day.year, month=day.month, day=day.day, hour=hour, minute=minute
    )
    clock.advance(target - clock.now())


async def read(scenario: Scenario) -> object:
    started = await scenario.run_periodic("devices.dishwasher")
    await scenario.app.outbox.flush()
    return started


async def run_once(scenario: Scenario, fake: FakeHomeConnect) -> None:
    """A whole cycle: running at one read, done by the next."""
    fake.set_state(DISHWASHER, "Run")
    await read(scenario)
    clock.advance(timedelta(hours=2))
    fake.set_state(DISHWASHER, "Finished")
    await read(scenario)


def signals(scenario: Scenario, name: str) -> list[tuple[float, str]]:
    rows = scenario.app.db.query(
        "SELECT value, note FROM energy_signals WHERE member_id = ? AND source = 'device_activity'",
        (scenario.member(name).id,),
    )
    return [(r["value"], r["note"]) for r in rows]


async def test_linking_finds_the_dishwasher(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher", "Dishwasher")
    page = await link(scenario, site, fake_home_connect)
    assert "Linked Home Connect. Found Dishwasher." in page
    assert "Dishwasher · dishwasher" in page
    (device,) = scenario.app.store.list_devices()
    assert (device.provider, device.external_id, device.appliance) == (
        "home_connect",
        DISHWASHER,
        "dishwasher",
    )


async def test_linking_redirects_are_allowed_by_the_csp(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    # Home Connect passes the sign-in on to SingleKey ID; browsers check every hop of a
    # form's redirects, so the Link button did nothing while SingleKey ID was left out.
    response = await site.get("/signed-out")
    form_action = response.headers["Content-Security-Policy"].split("form-action ")[1]
    assert "https://singlekey-id.com" in form_action.split(";")[0].split()


async def test_only_admins_link_it(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    response = await site.post("/family/home-connect/link", data={"csrf": csrf})
    assert response.status_code == 403
    assert not fake_home_connect.calls


async def test_a_cycle_starting_asks_to_check_off_the_wall_routine(
    scenario: Scenario,
    site: httpx.AsyncClient,
    fake_home_connect: FakeHomeConnect,
    fake_cozyla: FakeCozyla,
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    routine = fake_cozyla.add_routine("m-husband", "Cycle dishwasher", "Evening")
    fake_cozyla.add_routine("m-husband", "Take meds", "Evening")
    await link(scenario, site, fake_home_connect)

    await at(scenario, WED, 20, 14)
    assert await read(scenario) == 0  # Ready
    fake_home_connect.set_state(DISHWASHER, "Run")
    assert await read(scenario) == 1
    assert scenario.inbox("Husband")[-1] == (
        "The dishwasher started at 8:14 pm: check off Cycle dishwasher on the wall\n"
        "Go ahead, or not now?"
    )
    assert scenario.inbox("Erin") == []
    await scenario.tap("Husband", "Go ahead")
    assert (routine, WED.isoformat()) in fake_cozyla.routine_ticks

    clock.advance(timedelta(minutes=5))
    assert await read(scenario) == 0  # still the same cycle
    assert len(scenario.inbox("Husband")) == 1


async def test_once_its_automatic_the_routine_is_ticked_without_asking(
    scenario: Scenario,
    site: httpx.AsyncClient,
    fake_home_connect: FakeHomeConnect,
    fake_cozyla: FakeCozyla,
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    routine = fake_cozyla.add_routine("m-husband", "Cycle dishwasher", "Evening")
    await link(scenario, site, fake_home_connect)
    scenario.app.services.autonomy.grant_tier2(CATEGORY, via_rule_id=1, by=scenario.member("Erin"))
    await at(scenario, WED, 19)
    fake_home_connect.set_state(DISHWASHER, "Run")
    await read(scenario)
    assert (routine, WED.isoformat()) in fake_cozyla.routine_ticks
    assert scenario.inbox("Husband") == []

    # The evening check doesn't list it: it's done.
    await at(scenario, WED, 22, 1)
    await scenario.run_periodic("cozyla.routines")
    await scenario.app.outbox.flush()
    assert scenario.inbox("Husband") == []


async def test_a_cycle_closes_an_open_task_about_the_dishwasher(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Run the dishwasher", "physical", 1, WED, assignee=erin, nudge=False
    )
    later = await board(scenario).create(
        erin, "Descale the dishwasher", "physical", 2, WED + timedelta(days=3), nudge=False
    )
    await link(scenario, site, fake_home_connect)
    await at(scenario, WED, 13)
    fake_home_connect.set_state(DISHWASHER, "Run")
    await read(scenario)
    assert scenario.inbox("Erin")[-1].startswith(
        "The dishwasher started at 1 pm: check off Run the dishwasher\n"
    )
    await scenario.tap("Erin", "Go ahead")
    assert board(scenario).get(task.id).status == "done"
    assert board(scenario).get(later.id).status == "open"  # not due yet


async def test_a_new_cycle_needs_the_last_one_to_end_and_offline_ends_nothing(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    await link(scenario, site, fake_home_connect)
    fake_home_connect.set_state(DISHWASHER, "Run")
    assert await read(scenario) == 1
    fake_home_connect.offline(DISHWASHER)
    assert await read(scenario) == 0
    fake_home_connect.set_state(DISHWASHER, "Run")  # back online, same cycle
    assert await read(scenario) == 0
    fake_home_connect.set_state(DISHWASHER, "Finished")
    assert await read(scenario) == 0
    fake_home_connect.set_state(DISHWASHER, "Run")
    assert await read(scenario) == 1
    cycles = scenario.app.db.query("SELECT ended_at FROM appliance_cycles ORDER BY id")
    assert [c["ended_at"] is not None for c in cycles] == [True, False]


async def test_a_rate_limit_waits_quietly(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    await link(scenario, site, fake_home_connect)
    fake_home_connect.set_state(DISHWASHER, "Run")
    fake_home_connect.limit()
    assert await read(scenario) == 0
    clock.advance(timedelta(minutes=5))
    assert await read(scenario) == 0  # still inside the 10 minutes asked for
    clock.advance(timedelta(minutes=5))
    assert await read(scenario) == 1


async def test_fewer_runs_than_usual_is_a_gentle_sign(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    await link(scenario, site, fake_home_connect)

    async def pace() -> object:
        return await scenario.run_periodic("devices.dishwasher_pace")

    for day in range(14):  # two weeks of a run every day
        await at(scenario, WED + timedelta(days=day), 10)
        await run_once(scenario, fake_home_connect)
    await at(scenario, WED + timedelta(days=13), 19)
    assert await pace() is False  # not a week of history before this one yet
    assert signals(scenario, "Erin") == []

    await at(scenario, WED + timedelta(days=16), 10)  # then only once in a week
    await run_once(scenario, fake_home_connect)
    await at(scenario, WED + timedelta(days=21), 17)
    assert await pace() is False  # from the evening
    await at(scenario, WED + timedelta(days=21), 18)
    assert await pace() is True
    note = "the dishwasher ran once this week, fewer than usual (about 7 times)"
    assert signals(scenario, "Erin") == [(-0.5, note)]
    assert signals(scenario, "Husband") == [(-0.5, note)]
    assert await pace() is False  # once a day
    assert scenario.inbox("Erin") == []  # a signal, never a message


async def test_a_usual_week_says_nothing(
    scenario: Scenario, site: httpx.AsyncClient, fake_home_connect: FakeHomeConnect
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher")
    await link(scenario, site, fake_home_connect)
    for day in range(0, 21, 2):  # every other day, all along
        await at(scenario, WED + timedelta(days=day), 10)
        await run_once(scenario, fake_home_connect)
    await at(scenario, WED + timedelta(days=21), 18)
    assert await scenario.run_periodic("devices.dishwasher_pace") is False
    assert signals(scenario, "Erin") == []
