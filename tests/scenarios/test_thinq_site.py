"""30: LG ThinQ on the Family page. An admin pastes the token, Themi finds the appliances,
and each one is mapped to the washer, the dryer or nothing."""

from __future__ import annotations

import httpx

from tests.fakes.thinq import TOKEN, FakeThinq
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario


async def link(scenario: Scenario, site: httpx.AsyncClient, token: str = TOKEN) -> str:
    """Erin (an admin) links LG ThinQ from the Family page; returns the page after."""
    await sign_in(scenario, site, "Erin")
    page = await site.get("/family")
    response = await site.post(
        "/family/thinq/link",
        data={"csrf": csrf_of(page.text), "token": token, "country": "US"},
    )
    assert response.status_code == 303 and response.headers["location"] == "/family"
    return await flash(site, "/family")


async def test_linking_finds_the_washer_and_dryer(
    scenario: Scenario, site: httpx.AsyncClient, fake_thinq: FakeThinq
) -> None:
    fake_thinq.add_device("lg-washer-1", "DEVICE_WASHER", "Washer")
    fake_thinq.add_device("lg-dryer-1", "DEVICE_DRYER", "Dryer")
    page = await link(scenario, site)
    assert "Linked LG ThinQ. Found Washer, Dryer." in page
    assert "Unlink LG ThinQ" in page
    assert TOKEN not in page
    assert [(d.external_id, d.appliance) for d in scenario.app.store.list_devices()] == [
        ("lg-washer-1", "washer"),
        ("lg-dryer-1", "dryer"),
    ]


async def test_a_wrong_token_says_so(
    scenario: Scenario, site: httpx.AsyncClient, fake_thinq: FakeThinq
) -> None:
    page = await link(scenario, site, token="typo")
    assert "LG ThinQ wasn&#39;t linked: LG ThinQ no longer accepts this token" in page
    assert "Link LG ThinQ" in page


async def test_an_appliance_is_mapped_on_the_page(
    scenario: Scenario, site: httpx.AsyncClient, fake_thinq: FakeThinq
) -> None:
    fake_thinq.add_device("lg-combo-1", "DEVICE_WASHCOMBO_MAIN", "Combo")
    await link(scenario, site)
    (device,) = scenario.app.store.list_devices()
    assert device.appliance is None
    page = await site.get("/family")
    response = await site.post(
        f"/family/thinq/devices/{device.id}",
        data={"csrf": csrf_of(page.text), "appliance": "washer"},
    )
    assert response.status_code == 303
    assert "Combo: washer." in await flash(site, "/family")
    assert scenario.app.store.get_device(device.id).appliance == "washer"
    response = await site.post(
        f"/family/thinq/devices/{device.id}",
        data={"csrf": csrf_of(page.text), "appliance": "feeder"},
    )
    assert "the washer, the dryer, or neither" in await flash(site, "/family")
    assert scenario.app.store.get_device(device.id).appliance == "washer"


async def test_only_admins_link_it(
    scenario: Scenario, site: httpx.AsyncClient, fake_thinq: FakeThinq
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    response = await site.post(
        "/family/thinq/link", data={"csrf": csrf, "token": TOKEN, "country": "US"}
    )
    assert response.status_code == 403
    assert not fake_thinq.calls


async def test_unlinking(
    scenario: Scenario, site: httpx.AsyncClient, fake_thinq: FakeThinq
) -> None:
    fake_thinq.add_device("lg-washer-1", "DEVICE_WASHER", "Washer")
    page = await link(scenario, site)
    response = await site.post("/family/thinq/unlink", data={"csrf": csrf_of(page)})
    assert response.status_code == 303
    page = await flash(site, "/family")
    assert "Unlinked LG ThinQ." in page and "Link LG ThinQ" in page
    assert scenario.app.store.list_devices() == []
