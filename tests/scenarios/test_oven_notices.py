"""OV3: what Themi says about the oven, once per heat-up: preheated and the oven's timer
to whoever asked Themi for them; the probe to whoever's cooking; an oven left on at the
first bedtime, or after cooking ended, to everyone, with [Turn it off] [It's fine]. The
clock starts Wednesday 21 October 2026, 9 am; Erin's quiet hours start at 9:30 pm."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fakes.smarthq import FakeSmartHQ
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi_home.connectors.smarthq import LOWER, UPPER
from themi_home.connectors.smarthq import events as ov
from themi_home.oven import OvenControl


def control(scenario: Scenario) -> OvenControl:
    found = scenario.app.services.maybe(keys.oven)
    assert found is not None
    return found


async def poll(scenario: Scenario) -> list[str]:
    before = {n: len(scenario.inbox(n)) for n in ("Erin", "Husband")}
    await scenario.run_periodic("devices.oven")
    await scenario.app.outbox.flush()
    return [t for n in ("Erin", "Husband") for t in scenario.inbox(n)[before[n] :]]


async def test_preheated_once_to_whoever_started_it(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    kitchen.remote_enable()
    erin = scenario.member("Erin")
    lower = control(scenario).oven(LOWER)
    assert lower is not None
    said = await control(scenario).heat(erin, lower, ov.BAKE, 400)
    assert said.ok and said.words == "The lower oven is preheating to 400°F."
    clock.advance(timedelta(minutes=5))
    assert await poll(scenario) == []  # still on its way
    clock.advance(timedelta(minutes=10))
    assert await poll(scenario) == ["The lower oven's preheated to 400°F."]
    assert scenario.inbox("Husband") == []
    clock.advance(timedelta(minutes=1))
    assert await poll(scenario) == []  # once


async def test_an_oven_started_at_the_range_isnt_announced(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    kitchen.start_by_hand(LOWER, ov.BAKE, 350)
    await poll(scenario)
    clock.advance(timedelta(minutes=15))
    assert await poll(scenario) == []  # whoever started it is standing at it


async def test_the_ovens_timer_to_whoever_set_it(scenario: Scenario, kitchen: FakeSmartHQ) -> None:
    said = await control(scenario).set_timer(scenario.member("Erin"), 5)
    assert said.ok and said.words == "The oven's timer is set for 5 minutes."
    clock.advance(timedelta(minutes=5))
    assert await poll(scenario) == ["The oven timer's done."]
    # One set at the range beeps there.
    kitchen.receive(ov.code(UPPER, ov.KITCHEN_TIMER), ov.timer_value(3))
    await poll(scenario)
    clock.advance(timedelta(minutes=3))
    assert await poll(scenario) == []


async def test_the_probe_near_and_reached(scenario: Scenario, kitchen: FakeSmartHQ) -> None:
    kitchen.start_by_hand(LOWER, ov.CONV_ROAST, 375, probe_target_f=165)
    kitchen.set_probe(120)
    await poll(scenario)
    kitchen.set_probe(161)
    near = "The probe's at 161°F; the target is 165°F."
    assert await poll(scenario) == [near, near]  # started at the range: both hear it
    kitchen.set_probe(163)
    assert await poll(scenario) == []
    kitchen.set_probe(166)
    assert await poll(scenario) == ["The probe's reached 165°F."] * 2


async def test_left_on_at_bedtime_and_turned_off_from_the_card(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    clock.advance(timedelta(hours=11))  # 8 pm
    kitchen.start_by_hand(LOWER, ov.BAKE, 400)
    await poll(scenario)
    assert await scenario.run_periodic("oven.left_on") == 0
    clock.advance(timedelta(hours=1, minutes=35))  # 9:35 pm: Erin's quiet hours began
    await poll(scenario)
    assert await scenario.run_periodic("oven.left_on") == 1
    await scenario.app.outbox.flush()
    warning = "The lower oven is still on (on Bake at 400°F, preheated)."
    assert scenario.inbox("Erin")[-1] == warning and scenario.inbox("Husband")[-1] == warning
    assert scenario.last_buttons("Husband") == ["Turn it off", "It's fine"]
    await scenario.tap("Husband", "Turn it off")
    assert scenario.edits("Husband")[-1]["text"] == "The lower oven is off."
    assert kitchen.state(LOWER) == ov.STATE_OFF
    assert await scenario.run_periodic("oven.left_on") == 0
    [action] = scenario.app.services.autonomy.audit_trail(category="oven_off")[-1:]
    assert action["event"] == "executed"


@pytest.mark.parametrize("answer", ["It's fine", "nothing"])
async def test_its_fine_holds_it_until_the_next_heat_up(
    scenario: Scenario, kitchen: FakeSmartHQ, answer: str
) -> None:
    clock.advance(timedelta(hours=12, minutes=40))  # 9:40 pm
    kitchen.start_by_hand(UPPER, ov.PROOF, 85)
    await poll(scenario)
    clock.advance(timedelta(hours=1, minutes=30))  # 11:10 pm: Husband's quiet hours began
    await poll(scenario)
    assert await scenario.run_periodic("oven.left_on") == 1
    await scenario.app.outbox.flush()
    if answer == "It's fine":
        await scenario.tap("Erin", "It's fine")
        assert scenario.edits("Erin")[-1]["text"] == "Okay, leaving the upper oven on."
    clock.advance(timedelta(minutes=30))
    await poll(scenario)
    assert await scenario.run_periodic("oven.left_on") == 0  # told once a heat-up either way
    assert kitchen.state(UPPER) == ov.STATE_PROOF


async def test_left_on_half_an_hour_after_cooking_ended(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    from tests.fixtures.cookbook import load
    from tests.unit.test_cooking_look_ahead import BAKED, items

    load(scenario.app.services, BAKED)
    kitchen.start_by_hand(LOWER, ov.BAKE, 400)
    await poll(scenario)
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(items())
    await scenario.say("Erin", "Let's make the alfredo sauce")
    await scenario.say("Erin", "stop cooking")
    clock.advance(timedelta(minutes=20))
    await poll(scenario)
    assert await scenario.run_periodic("oven.left_on") == 0
    clock.advance(timedelta(minutes=10))
    await poll(scenario)
    assert await scenario.run_periodic("oven.left_on") == 1


async def test_a_lost_sign_in_tells_the_admin_once(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    kitchen.expire()
    await poll(scenario)
    await poll(scenario)
    lost = [t for t in scenario.inbox("Erin") if t.startswith("SmartHQ stopped accepting")]
    assert len(lost) == 1
