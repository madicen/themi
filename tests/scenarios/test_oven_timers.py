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
from tests.scenarios.test_cook_screen import PANCAKE_LINKS, PANCAKES
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
    scenario.primary.queue_structured(PANCAKE_LINKS)  # CF1: step 3 is asked about once
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


async def test_bug_215_a_cancel_clears_the_ovens_at_once(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    """F45f (bug #215): the oven heard the cancel 25 s later, at its next reading, and each
    clear was kept as a 0-minute oven timer never done."""
    screen = await at_step_5(scenario, site)
    offer = (await screen.state())["offers"][0]
    shown = await screen.act("oven_timer", minutes=offer["minutes"], step=offer["step"])
    assert oven_timer(kitchen) == 2
    cancelled = await screen.act("timer_cancel", timer=shown["timers"][0]["id"])
    assert oven_timer(kitchen) == 0  # no reading needed
    assert cancelled["said"] == "Timer cancelled, and the oven's too."
    assert not scenario.app.db.scalar(
        "SELECT COUNT(*) FROM oven_timers WHERE done_at IS NULL"
    )  # the cleared one is done, and the clear isn't a timer of its own
    await poll(scenario)
    assert oven_timer(kitchen) == 0


async def test_cancel_the_timer_in_chat_clears_the_ovens_too(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    offer = (await screen.state())["offers"][0]
    await screen.act("oven_timer", minutes=offer["minutes"], step=offer["step"])
    (reply,) = await scenario.say("Erin", "cancel the timer")
    assert reply == "Timer cancelled, and the oven's too."
    assert oven_timer(kitchen) == 0


# ----- F59h (idea #259): any timer can go to the oven, and the buttons sit by the time ----


async def test_a_timer_from_add_can_go_to_the_oven_with_its_time_left(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    shown = await screen.act("timer", minutes=15)  # [+ Add], 15 min
    (timer,) = shown["timers"]
    assert timer["oven"] is False
    page = (await site.get("/session/cook/view")).text
    assert "The oven&#39;s timer too, Step 5" in page or "The oven's timer too, Step 5" in page
    clock.advance(timedelta(seconds=14))  # 14:46 left
    sent = await screen.act("oven_timer", timer=timer["id"])
    assert sent["said"] == "The oven's timer is set too."
    assert oven_timer(kitchen) == 15  # 14:46, rounded up
    assert [t["oven"] for t in sent["timers"]] == [True]
    again = await screen.act("oven_timer", timer=timer["id"])  # already followed
    assert again["said"] == "The oven's timer follows this one already."
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM oven_timers WHERE done_at IS NULL") == 1
    await screen.act("timer_add", timer=timer["id"], minutes=5)
    await poll(scenario)
    assert oven_timer(kitchen) == 20  # +5 on Themi's moves the oven's


async def test_add_with_oven_timer_too_starts_both(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    page = (await site.get("/session/cook/view")).text
    assert 'name="oven" value="1"' in page and "Oven timer too" in page
    shown = await screen.act("timer", minutes=8, oven="1")
    assert shown["said"] == "Timer set, and the oven's timer too."
    assert oven_timer(kitchen) == 8


async def test_someone_elses_or_a_finished_timer_isnt_sent(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_step_5(scenario, site)
    shown = await screen.act("timer", minutes=1)
    timer_id = shown["timers"][0]["id"]
    await scenario.advance(minutes=1)
    await scenario.run_jobs()
    await screen.act("oven_timer", timer=timer_id)
    assert oven_timer(kitchen) in (0, None)
    await screen.act("oven_timer", timer=99999)
    assert oven_timer(kitchen) in (0, None)


async def test_the_time_and_its_buttons_share_a_row(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    import re

    screen = await at_step_5(scenario, site)
    await screen.act("timer", minutes=15)
    page = (await site.get("/session/cook/view")).text
    row = re.search(r'<div class="cook-timer-row">(.*?)</div>\s*</div>\s*<p class="cook-timer-of">',
                    page, re.S)  # fmt: skip
    assert row is not None
    assert 'class="cook-timer-left"' in row[1]
    assert row[1].count('value="timer_add"') == 2 and 'value="timer_cancel"' in row[1]
    assert 'value="oven_timer"' in row[1]


async def test_without_the_oven_theres_no_oven_button(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    screen = await at_step_5(scenario, site)
    await screen.act("timer", minutes=15)
    page = (await site.get("/session/cook/view")).text
    assert 'class="cook-timer-row"' in page  # the timer is there
    assert 'value="oven_timer"' not in page and "Oven timer too" not in page
