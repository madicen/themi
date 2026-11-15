"""OV2: "is the oven still on?" reads the range's two ovens through SmartHQ (fake_smarthq),
never from memory; an oven that can't be read is told as last seen."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fakes.smarthq import CODE, EMAIL, PASSWORD, FakeSmartHQ
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_appliance_status import ask, tool_names
from themi import clock
from themi_home.connectors.smarthq import LOWER, UPPER
from themi_home.connectors.smarthq import events as ov


async def test_is_the_oven_still_on(scenario: Scenario, kitchen: FakeSmartHQ) -> None:
    kitchen.start_by_hand(LOWER, ov.BAKE, 400)
    clock.advance(timedelta(minutes=8))  # 70°F, and 25°F a minute for 8
    said = await ask(scenario, "is the oven still on?", "oven")
    assert "appliance_status" in tool_names(scenario)  # "oven" chose the devices group
    assert "Upper oven (oven), read just now: off." in said
    assert "Lower oven (oven), read just now: preheating to 400°F for Bake (270°F now)." in said

    clock.advance(timedelta(minutes=10))
    kitchen.set_probe(141)
    said = await ask(scenario, "is it preheated yet?", "oven")
    assert "Lower oven (oven), read just now: on Bake at 400°F, preheated; the probe" in said


async def test_the_timer_and_an_oven_that_cant_be_read(
    scenario: Scenario, kitchen: FakeSmartHQ
) -> None:
    kitchen.start_by_hand(UPPER, ov.PROOF, 85)
    kitchen.receive(ov.code(UPPER, ov.KITCHEN_TIMER), ov.timer_value(45))
    await scenario.run_periodic("devices.oven")
    said = await ask(scenario, "how's the dough doing in the oven?", "oven")
    assert "Upper oven (oven), read just now: proofing (85°F); its kitchen timer has about" in said
    assert "45 minutes left" in said

    kitchen.offline = True
    said = await ask(scenario, "is the oven on?", "oven")
    assert "Upper oven (oven): couldn't be read just now. As of 9 am it was proofing" in said


async def test_the_website_signs_in_with_the_emailed_code(
    scenario: Scenario, site: httpx.AsyncClient, fake_smarthq: FakeSmartHQ
) -> None:
    await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "Oven" in page.text and "/family/smarthq/sign-in" in page.text
    asked = await site.post(
        "/family/smarthq/sign-in",
        data={"csrf": csrf_of(page.text), "email": EMAIL, "password": PASSWORD, "region": "US"},
    )
    assert asked.status_code == 200
    assert f"The code SmartHQ emailed to {EMAIL}" in asked.text
    assert PASSWORD not in asked.text
    done = await site.post(
        "/family/smarthq/code", data={"csrf": csrf_of(asked.text), "email": EMAIL, "code": CODE}
    )
    assert done.status_code == 303
    assert done.headers["location"] == "/accounts?open=smarthq#smarthq"
    page_text = await flash(site, "/accounts")
    assert "Linked SmartHQ. Found the upper and lower ovens." in page_text
    assert "Upper oven" in page_text and f"Signed in as {EMAIL}" in page_text


async def test_only_an_admin_signs_in(
    scenario: Scenario, site: httpx.AsyncClient, fake_smarthq: FakeSmartHQ
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    response = await site.post(
        "/family/smarthq/sign-in", data={"csrf": csrf, "email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 403
    assert fake_smarthq.codes_sent == []
