"""F20b, Michael's bug #109 (2026-10-31): "How much longer on the current wash cycle?" got "25
minutes left" and "And the dryer?" got "The dryer isn't running", both made up, while both
were running. Now `appliance_status` reads them. The washer and dryer are LG's (fake_thinq),
the dishwasher Bosch's (fake_home_connect)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from tests.fakes.home_connect import FakeHomeConnect
from tests.fakes.thinq import TOKEN, FakeThinq
from tests.scenarios.harness import Scenario
from tests.scenarios.test_dishwasher import DISHWASHER, link
from themi import clock
from themi.ai.types import ToolResult
from themi.core.appliances import NONE_LINKED

WASHER, DRYER = "lg-washer-1", "lg-dryer-1"


@pytest.fixture
async def laundry_room(scenario: Scenario, fake_thinq: FakeThinq) -> FakeThinq:
    fake_thinq.add_device(WASHER, "DEVICE_WASHER", "Washer")
    fake_thinq.add_device(DRYER, "DEVICE_DRYER", "Dryer", "DLEX4000W")
    watcher = scenario.app.services.thinq
    assert watcher is not None
    await watcher.link(scenario.member("Erin"), TOKEN, "US")
    await scenario.run_periodic("devices.thinq")  # the starting point: both off
    return fake_thinq


def tool_result(scenario: Scenario) -> str:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ][-1]


def tool_names(scenario: Scenario) -> set[str]:
    return {spec.name for spec in scenario.primary.last_request.tools}


async def ask(scenario: Scenario, text: str, appliance: str, reply: str = "Here.") -> str:
    scenario.primary.queue_tool_call("appliance_status", {"appliance": appliance})
    scenario.primary.queue_text(reply)
    await scenario.say("Husband", text)
    return tool_result(scenario)


async def test_michaels_two_questions(scenario: Scenario, laundry_room: FakeThinq) -> None:
    laundry_room.set_state(WASHER, "washer_running")  # 24 minutes left
    laundry_room.set_state(DRYER, "dryer_running")  # 48 minutes left
    said = await ask(scenario, "How much longer on the current wash cycle?", "washer")
    assert "Washer (washer), read just now: running" in said and "24 minutes left" in said
    assert "appliance_status" in tool_names(scenario)  # the words chose the devices group

    said = await ask(scenario, "And the dryer?", "dryer")
    assert "Dryer (dryer), read just now: running" in said and "48 minutes left" in said
    assert "appliance_status" in tool_names(scenario)  # from the question before it


async def test_since_when_and_finished(scenario: Scenario, laundry_room: FakeThinq) -> None:
    laundry_room.set_run_state(WASHER, "RUNNING")  # no timer in this report
    await scenario.run_periodic("devices.thinq")
    clock.advance(timedelta(minutes=20))
    said = await ask(scenario, "is the washer still running?", "washer")
    assert "running since 9 am; it doesn't say how long is left" in said
    clock.advance(timedelta(minutes=40))
    laundry_room.set_state(WASHER, "washer_end")
    said = await ask(scenario, "is the washer done?", "washer")
    assert "read just now: finished at 10 am, not running now." in said


async def test_an_appliance_that_cant_be_read_is_told_as_last_seen(
    scenario: Scenario, laundry_room: FakeThinq
) -> None:
    laundry_room.set_state(DRYER, "dryer_running")
    await scenario.run_periodic("devices.thinq")
    clock.advance(timedelta(minutes=10))
    laundry_room.offline(DRYER)
    said = await ask(scenario, "is the dryer done?", "dryer")
    assert "Dryer (dryer): couldn't be read just now. As of 9 am it was running." in said
    assert "never add a time or a state" in said


async def test_nothing_linked_says_so(scenario: Scenario) -> None:
    said = await ask(scenario, "How much longer on the wash?", "all")
    assert said == NONE_LINKED


async def test_the_dishwasher_and_its_time_left(
    scenario: Scenario,
    site: httpx.AsyncClient,
    fake_home_connect: FakeHomeConnect,
) -> None:
    fake_home_connect.add_appliance(DISHWASHER, "Dishwasher", "Dishwasher")
    await link(scenario, site, fake_home_connect)
    fake_home_connect.set_state(DISHWASHER, "Run", seconds_left=2700)
    said = await ask(scenario, "Is the dishwasher still running?", "dishwasher")
    assert "Dishwasher (dishwasher), read just now: running since 9 am, 45 minutes left" in said
    fake_home_connect.set_state(DISHWASHER, "Ready")
    said = await ask(scenario, "Is the dishwasher still running?", "dishwasher")
    assert "not running" in said
