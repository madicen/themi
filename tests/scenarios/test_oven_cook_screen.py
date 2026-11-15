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


# ----- OV6: Stop or Finish asks about the oven -------------------------------------------


async def preheated_here(alfredo: Screen, kitchen: FakeSmartHQ) -> None:
    kitchen.remote_enable()
    state = await alfredo.state()
    button = state["strip"]["oven"][0]
    await alfredo.act(
        "oven_heat", oven=button["oven"], mode=button["mode"], temp=button["temp"],
        key=button["key"], at=state["strip"]["at"],
    )  # fmt: skip


async def test_stop_on_the_screen_asks_and_turns_it_off(
    alfredo: Screen, kitchen: FakeSmartHQ
) -> None:
    await preheated_here(alfredo, kitchen)
    shown = await alfredo.act("stop")
    assert shown["oven_off"] == "The lower oven is still on. Turn it off too?"
    page = (await alfredo.site.get("/session/cook/view")).text
    assert 'value="oven_off"' in page and "Leave it on" in page
    assert not [t for t in alfredo.scenario.inbox("Erin") if "Turn it off too" in t]  # one ask
    shown = await alfredo.act("oven_off")
    assert shown["said"] == "The lower oven is off." and not shown.get("oven_off")
    assert kitchen.state(LOWER) == ov.STATE_OFF
    trail = alfredo.scenario.app.services.autonomy.audit_trail(category="oven_off")
    assert trail[-1]["event"] == "executed"


async def test_stop_in_chat_asks_there_and_leave_it_on_keeps_the_warning(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    from tests.unit.test_cooking_look_ahead import BAKED, items
    from themi.core import keys

    load(scenario.app.services, BAKED)
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(items())
    await scenario.say("Erin", "Let's make the alfredo sauce")
    oven = scenario.app.services.get(keys.oven)
    session = scenario.app.services.get(keys.cooking).current(scenario.member("Erin"))
    assert session is not None
    kitchen.remote_enable()
    lower = oven.oven(LOWER)
    assert lower is not None
    said = await oven.heat(scenario.member("Erin"), lower, ov.BAKE, 400, session_id=session.id)
    assert said.ok
    await scenario.say("Erin", "stop cooking")
    await scenario.app.outbox.flush()
    assert "The lower oven is still on. Turn it off too?" in scenario.inbox("Erin")
    await scenario.tap("Erin", "Leave it on")
    assert scenario.edits("Erin")[-1]["text"] == "Okay, leaving the lower oven on."
    assert kitchen.state(LOWER) != ov.STATE_OFF
    clock.advance(timedelta(minutes=31))
    await scenario.run_periodic("devices.oven")
    assert await scenario.run_periodic("oven.left_on") == 1  # the warning still comes


async def test_an_oven_this_session_didnt_start_isnt_offered(
    alfredo: Screen, kitchen: FakeSmartHQ
) -> None:
    kitchen.start_by_hand(LOWER, ov.BAKE, 400)
    await alfredo.scenario.run_periodic("devices.oven")
    shown = await alfredo.act("stop")
    assert not shown.get("oven_off")


# ----- OV7: proofing dough ----------------------------------------------------------------


async def at_the_rise(scenario: Scenario, site: httpx.AsyncClient) -> Screen:
    from tests.unit.test_cooking_look_ahead import LINES, items
    from tests.unit.test_cooking_look_ahead import recipe as a_recipe

    rolls = a_recipe(
        "Alfredo Sauce",
        LINES,
        [
            "Mix the dough and knead for 8 minutes.",
            "Cover and let rise in a warm place for 1 hour, until doubled.",
            "Shape and bake.",
        ],
    )
    load(scenario.app.services, rolls)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(items())
    await scenario.say("Erin", "Let's make the alfredo sauce")
    scenario.primary.queue_structured({"jobs": []})
    for said in ("skip", "all here", "skip prep", "go to step 2"):
        await scenario.say("Erin", said)
    return Screen(scenario, site, csrf)


async def test_proof_in_the_upper_oven_with_a_timer(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_the_rise(scenario, site)
    state = await screen.state()
    assert state["proof"]["label"] == "Proof in the oven" and state["proof"]["minutes"] == 60
    page = (await site.get("/session/cook/view")).text
    assert 'value="oven_proof"' in page
    kitchen.remote_enable()
    shown = await screen.act("oven_proof", minutes=60, at=state["proof"]["at"])
    assert shown["said"] == "The upper oven is on Proof (85°F). And a 1 hr timer for the rise."
    assert kitchen.state(UPPER) == ov.STATE_PROOF
    assert [t["label"] for t in shown["timers"]] == ["Step 2"]
    assert shown["proof"] is None  # the oven's on now
    assert shown["oven_line"] == "Upper oven proofing at 85°F"


async def test_no_proof_while_the_upper_oven_is_hot(
    scenario: Scenario, site: httpx.AsyncClient, kitchen: FakeSmartHQ
) -> None:
    screen = await at_the_rise(scenario, site)
    kitchen.start_by_hand(UPPER, ov.BAKE, 350)
    shown = await screen.act("oven_proof", minutes=60, at=(await screen.state())["proof"]["at"])
    assert shown["said"].startswith("The upper oven is on (preheating to 350°F")
    assert shown["said"].endswith("so it can't proof now.")
    await scenario.run_periodic("devices.oven")
    assert (await screen.state())["proof"] is None  # not offered with it on
