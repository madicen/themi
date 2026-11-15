"""OV5: a step's timer can be the oven's too. Themi's timer and the upper oven's kitchen
timer start together; cancelling or moving either follows on the other at the next read;
the end is said once, by Themi's own timer. Pancakes, step 5 ("2 to 3 minutes", "1 to 2")."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fakes.smarthq import FakeSmartHQ
from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cook_screen import PANCAKES
from tests.scenarios.test_oven_cook_screen import Screen
from tests.unit.test_cook_screen import lines
from themi import clock
from themi_home.connectors.smarthq import UPPER
from themi_home.connectors.smarthq import events as ov


async def at_step_5(scenario: Scenario, site: httpx.AsyncClient) -> Screen:
    load(scenario.app.services)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "pancakes", "scale": ""})
    scenario.primary.queue_structured(lines(PANCAKES))
    await scenario.say("Erin", "Let's make pancakes")
    scenario.primary.queue_structured({"jobs": []})
    for said in ("skip", "all here", "skip prep", "go to step 5"):
        await scenario.say("Erin", said)
    return Screen(scenario, site, csrf)


def oven_timer(kitchen: FakeSmartHQ) -> int | None:
    return ov.read(UPPER, kitchen.erds()).timer_minutes


async def poll(scenario: Scenario) -> None:
    await scenario.run_periodic("devices.oven")
    await scenario.app.outbox.flush()


async def test_both_timers_and_the_end_said_once(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    state = await screen.state()
    assert [o["oven"] for o in state["offers"]] == [True, True]
    page = (await site.get("/session/cook/view")).text
    assert 'value="oven_timer"' in page and "Oven timer" in page
    offer = state["offers"][0]  # 2 minutes
    shown = await screen.act("oven_timer", minutes=offer["minutes"], step=offer["step"])
    assert shown["said"] == "Timer set, and the oven's timer too."
    assert [t["label"] for t in shown["timers"]] == ["Step 5"]
    assert oven_timer(kitchen) == 2
    await scenario.advance(minutes=2)
    await scenario.run_jobs()
    await poll(scenario)
    ends = [t for t in scenario.inbox("Erin") if "Time's up" in t or "oven timer" in t]
    assert ends == ["Time's up: 2 min for step 5 of Pancakes."]  # once, by Themi's timer


async def test_cancelling_themis_clears_the_ovens(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    offer = (await screen.state())["offers"][0]
    shown = await screen.act("oven_timer", minutes=offer["minutes"], step=offer["step"])
    await screen.act("timer_cancel", timer=shown["timers"][0]["id"])
    await poll(scenario)
    assert oven_timer(kitchen) == 0


async def test_more_time_moves_both(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    offer = (await screen.state())["offers"][0]
    shown = await screen.act("oven_timer", minutes=offer["minutes"], step=offer["step"])
    await screen.act("timer_add", timer=shown["timers"][0]["id"], minutes=5)
    await poll(scenario)
    assert oven_timer(kitchen) == 7


async def test_cleared_at_the_range_cancels_themis(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    offer = (await screen.state())["offers"][0]
    await screen.act("oven_timer", minutes=offer["minutes"], step=offer["step"])
    await poll(scenario)
    kitchen.receive(ov.code(UPPER, ov.KITCHEN_TIMER), ov.timer_value(0))  # at the range
    await poll(scenario)
    assert (await screen.state())["timers"] == []
    clock.advance(timedelta(minutes=3))
    await scenario.run_jobs()
    await scenario.app.outbox.flush()
    assert not [t for t in scenario.inbox("Erin") if "Time's up" in t]
