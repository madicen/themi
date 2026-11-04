"""CG1a: the CatGenie litter box, linked from the Accounts page by a texted code, and read when
someone asks how it's doing. The clock starts on Wednesday 21 October 2026, 09:00 (Los
Angeles)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from tests.fakes.catgenie import CODE, PHONE, FakeCatGenie
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_appliance_status import ask, tool_names
from themi import clock

BOX = "CGR0000001"


@pytest.fixture
async def litter_box(scenario: Scenario, fake_catgenie: FakeCatGenie) -> FakeCatGenie:
    """The litter box, linked and read once (the starting point: ready, no errors)."""
    fake_catgenie.add_box(BOX, "CatGenie")
    watcher = scenario.app.services.catgenie
    assert watcher is not None
    await watcher.send_code(PHONE)
    await watcher.link(scenario.member("Erin"), PHONE, CODE)
    await scenario.run_periodic("devices.litter_box")
    return fake_catgenie


async def seen(scenario: Scenario, fake: FakeCatGenie, **changes: object) -> None:
    """The box reports `changes`, and a read comes round (10 minutes on)."""
    if changes:
        fake.set(BOX, **changes)  # type: ignore[arg-type]
    clock.advance(timedelta(minutes=10))
    await scenario.run_periodic("devices.litter_box")
    await scenario.app.outbox.flush()


async def test_linking_by_a_texted_code_from_the_accounts_page(
    scenario: Scenario, site: httpx.AsyncClient, fake_catgenie: FakeCatGenie
) -> None:
    fake_catgenie.add_box(BOX, "CatGenie")
    await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "Litter box" in page.text and "Send code" in page.text
    sent = await site.post(
        "/family/catgenie/code", data={"csrf": csrf_of(page.text), "phone": "(555) 010-0123"}
    )
    assert sent.status_code == 200  # the code form, with the number kept out of the URL
    assert f"The code texted to {PHONE}" in sent.text
    assert fake_catgenie.codes_sent == [PHONE]
    done = await site.post(
        "/family/catgenie/link",
        data={"csrf": csrf_of(sent.text), "phone": PHONE, "code": CODE},
    )
    assert done.status_code == 303
    assert done.headers["location"] == "/accounts?open=catgenie#catgenie"
    assert "Linked CatGenie. Found CatGenie." in await flash(site, "/accounts")

    await scenario.run_periodic("devices.litter_box")
    page = await site.get("/accounts")
    assert "CatGenie · ready, 39% sani-solution left" in page.text
    assert "<code>remainingSaniSolution</code>: 39" in page.text  # what it reports
    assert BOX not in page.text  # its id stays out
    assert "Unlink CatGenie" in page.text and "Send code" not in page.text


async def test_a_wrong_code_says_so(
    scenario: Scenario, site: httpx.AsyncClient, fake_catgenie: FakeCatGenie
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    sent = await site.post("/family/catgenie/code", data={"csrf": csrf, "phone": PHONE})
    await site.post(
        "/family/catgenie/link", data={"csrf": csrf_of(sent.text), "phone": PHONE, "code": "1"}
    )
    text = await flash(site, "/accounts")
    assert "linked: PetNovations didn" in text and "take that code" in text
    assert scenario.app.services.catgenie is not None
    assert not scenario.app.services.catgenie.account.linked()


async def test_only_an_admin_links_it(
    scenario: Scenario, site: httpx.AsyncClient, fake_catgenie: FakeCatGenie
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    response = await site.post("/family/catgenie/code", data={"csrf": csrf, "phone": PHONE})
    assert response.status_code == 403
    assert fake_catgenie.calls == []


async def test_unlinking_forgets_the_sign_in_and_the_box(
    scenario: Scenario, site: httpx.AsyncClient, litter_box: FakeCatGenie
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/family/catgenie/unlink", data={"csrf": csrf})
    assert "Unlinked CatGenie." in await flash(site, "/accounts")
    assert scenario.app.db.query("SELECT 1 FROM catgenie_account") == []
    assert [d for d in scenario.app.store.list_devices() if d.provider == "catgenie"] == []


async def test_asked_how_the_litter_box_is_themi_reads_it(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    litter_box.clean(BOX, clock.now() - timedelta(hours=1))
    litter_box.set(BOX, sani=15, cleaning=60)
    said = await ask(scenario, "Is the litter box ok?", "litter_box")
    assert "appliance_status" in tool_names(scenario)  # the words chose the devices group
    assert said.startswith(
        "CatGenie (litter_box), read just now: cleaning (60% done), 15% sani-solution left; "
        "last cleaned 8 am today."
    )


async def test_when_it_cant_be_read_it_says_when_it_was_last_seen(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    litter_box.fail(times=1)
    said = await ask(scenario, "How much sani-solution is left in the CatGenie?", "litter_box")
    assert said.startswith(
        "CatGenie (litter_box): couldn't be read just now. As of 9 am it was ready, 39% "
        "sani-solution left."
    )
