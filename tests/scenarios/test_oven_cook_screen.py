"""OV4 to OV7: the oven on the cook screen, always by a tap. Alfredo Sauce baked over pasta
(step 4: "Preheat the oven to 400°F"). The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.fakes.smarthq import FakeSmartHQ
from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi_home.connectors.smarthq import LOWER, UPPER
from themi_home.connectors.smarthq import events as ov


class Screen:
    def __init__(self, scenario: Scenario, site: httpx.AsyncClient, csrf: str) -> None:
        self.scenario, self.site, self.csrf = scenario, site, csrf

    async def state(self) -> dict[str, Any]:
        return (await self.site.get("/session/state")).json()

    async def act(self, action: str, **form: Any) -> dict[str, Any]:
        state = await self.state()
        response = await self.site.post(
            f"/session/cook/{state['id']}/act",
            headers={"X-Requested-With": "fetch"},
            data={"csrf": self.csrf, "action": action, "seq": str(state["seq"]),
                  **{k: str(v) for k, v in form.items()}},
        )  # fmt: skip
        return response.json()


@pytest.fixture
async def alfredo(scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ) -> Screen:
    from tests.unit.test_cooking_look_ahead import BAKED, items

    load(scenario.app.services, BAKED)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(items())
    await scenario.say("Erin", "Let's make the alfredo sauce")
    await scenario.tap("Erin", "Skip")
    return Screen(scenario, site, csrf)


async def test_preheat_from_the_look_ahead(alfredo: Screen, kitchen: FakeSmartHQ) -> None:
    state = await alfredo.state()
    assert state["strip"]["text"] == "Step 4 wants the oven at 400°F. Start it now?"
    labels = [b["label"] for b in state["strip"]["oven"]]
    assert labels == ["Preheat lower oven", "Preheat upper oven"]  # a plain Bake: either
    page = (await alfredo.site.get("/session/cook/view")).text
    assert 'value="oven_heat"' in page and "Preheat lower oven" in page

    kitchen.remote_enable()
    button = state["strip"]["oven"][0]
    shown = await alfredo.act(
        "oven_heat", oven=button["oven"], mode=button["mode"], temp=button["temp"],
        key=button["key"], at=state["strip"]["at"],
    )  # fmt: skip
    assert shown["said"] == "The lower oven is preheating to 400°F."
    assert shown["strip"] is None  # the offer's done
    assert shown["oven_line"] == "Lower oven heating to 400°F"
    clock.advance(timedelta(minutes=8))
    await alfredo.scenario.run_periodic("devices.oven")
    assert (await alfredo.state())["oven_line"] == "Lower oven 270°F of 400°F"
    clock.advance(timedelta(minutes=8))
    await alfredo.scenario.run_periodic("devices.oven")
    assert (await alfredo.state())["oven_line"] == "Lower oven preheated to 400°F"
    trail = alfredo.scenario.app.services.autonomy.audit_trail(category="oven_heat")
    assert [t["event"] for t in trail] == ["staged", "approved", "executed"]  # the tap's yes
    assert alfredo.scenario.inbox("Erin")[-1] != "Waiting on your yes"  # no second card


async def test_remote_enable_off_says_what_to_press(alfredo: Screen, kitchen: FakeSmartHQ) -> None:
    state = await alfredo.state()
    button = state["strip"]["oven"][0]
    shown = await alfredo.act(
        "oven_heat", oven=LOWER, mode=button["mode"], temp=button["temp"], key=button["key"],
        at=state["strip"]["at"],
    )  # fmt: skip
    assert "Remote Enable is off" in shown["said"] and "Press and hold" in shown["said"]
    assert shown["strip"]["key"] == "preheat:3"  # still offered
    assert kitchen.state(LOWER) == ov.STATE_OFF


async def test_a_screen_left_open_too_long_doesnt_heat(
    alfredo: Screen, kitchen: FakeSmartHQ
) -> None:
    kitchen.remote_enable()
    state = await alfredo.state()
    button = state["strip"]["oven"][0]
    clock.advance(timedelta(minutes=11))
    shown = await alfredo.act(
        "oven_heat", oven=LOWER, mode=button["mode"], temp=button["temp"], key=button["key"],
        at=state["strip"]["at"],
    )  # fmt: skip
    assert shown["said"] == "That was a while ago, so I've left it. The lower oven is off."
    assert kitchen.state(LOWER) == ov.STATE_OFF
    assert kitchen.state(UPPER) == ov.STATE_OFF


async def test_no_oven_linked_no_preheat_button(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    from tests.unit.test_cooking_look_ahead import BAKED, items

    load(scenario.app.services, BAKED)
    await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(items())
    await scenario.say("Erin", "Let's make the alfredo sauce")
    await scenario.tap("Erin", "Skip")
    state = (await site.get("/session/state")).json()
    assert "oven" not in state["strip"] and state["oven_line"] == ""
