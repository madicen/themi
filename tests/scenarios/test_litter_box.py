"""CG1a, CG1b: the CatGenie litter box, linked from the Accounts page by a texted code, read
when someone asks how it's doing, and its chores: an error, an alert, the sani-solution low
or out, and the granules every so many cleans go to whoever has more room, 10 minutes on;
the box sorting itself takes the nudge back. The clock starts on Wednesday 21 October 2026,
09:00 (Los Angeles)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from tests.fakes.catgenie import CODE, PHONE, FakeCatGenie
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_appliance_status import ask, tool_names
from themi import clock
from themi.accounts import SYSTEM
from themi.core import keys

BOX = "CGR0000001"


@pytest.fixture
async def litter_box(scenario: Scenario, fake_catgenie: FakeCatGenie) -> FakeCatGenie:
    """The litter box, linked and read once (the starting point: ready, no errors)."""
    fake_catgenie.add_box(BOX, "CatGenie")
    watcher = scenario.app.services.maybe(keys.catgenie)
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
    assert scenario.app.services.maybe(keys.catgenie) is not None
    assert not scenario.app.services.get(keys.catgenie).account.linked()


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


# ----- CG1b: its chores --------------------------------------------------------------------

ERROR = "The CatGenie needs a look: it shows an error (heater fault). Check it when you can?"
LOW = (
    "The CatGenie is running low on sani-solution (about 15% left). Swap in a new cartridge "
    "when you can?"
)
OUT = "The CatGenie is out of sani-solution, so it can't wash. Swap in a new cartridge?"
ALERT = "The CatGenie sent an alert: it shows an error (dome open). Check it when you can?"
GRANULES = (
    "The CatGenie has cleaned 3 times since its granules were last topped up. Top them up when "
    "you can?"
)


def tasks(scenario: Scenario) -> list[tuple[str, str, int]]:
    return [
        (r["title"], r["status"], r["assignee"])
        for r in scenario.app.db.query("SELECT * FROM tasks ORDER BY id")
    ]


def tired(scenario: Scenario) -> None:
    scenario.app.services.energy.record(scenario.member("Erin"), "text_note", -3, "worn out")


async def test_an_error_goes_to_whoever_has_more_room_and_cant_wait(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    tired(scenario)
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(SYSTEM, husband.id, daily_limit=0)  # due at once anyway
    await seen(scenario, litter_box, error="HEATER_FAULT")
    assert tasks(scenario) == [("Check the CatGenie", "open", husband.id)]
    assert await scenario.advance(minutes=9) == []  # a bounce in the reading waits
    assert await scenario.advance(minutes=1) == [ERROR]
    assert scenario.last_buttons("Husband") == ["Done", "Later"]
    assert scenario.inbox("Erin") == []
    await seen(scenario, litter_box)  # still showing: no second task
    assert len(tasks(scenario)) == 1
    await seen(scenario, litter_box, error="")  # cleared on the box: asked, so someone did it
    assert tasks(scenario)[0][1] == "done"
    signals = scenario.app.db.query("SELECT * FROM energy_signals WHERE source = 'device_activity'")
    assert signals == []  # the box can't say who sorted it


async def test_sorted_within_ten_minutes_sends_nothing(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    await seen(scenario, litter_box, error="HEATER_FAULT")
    litter_box.set(BOX, error="")
    clock.advance(timedelta(minutes=5))
    await scenario.run_periodic("devices.litter_box")
    assert tasks(scenario)[0][1] == "cancelled"
    assert await scenario.advance(hours=1) == []
    assert scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'litter_box'") == []


async def test_running_low_then_out_asks_again_then_a_new_cartridge_closes_it(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    tired(scenario)
    await seen(scenario, litter_box, sani=15)
    assert tasks(scenario)[0][0] == "Change the CatGenie's sani-solution cartridge"
    assert await scenario.advance(minutes=10) == [LOW]
    await seen(scenario, litter_box, sani=0)
    assert scenario.inbox("Husband") == [LOW, OUT]  # the same chore, asked again
    assert len(tasks(scenario)) == 1
    await seen(scenario, litter_box, sani=100)
    assert tasks(scenario)[0][1] == "done"


async def test_done_is_a_small_effort_for_whoever_did_it(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    tired(scenario)
    await seen(scenario, litter_box, sani=15)
    await scenario.advance(minutes=10)
    await scenario.tap("Husband", "Done")
    assert tasks(scenario)[0][1] == "done"
    signals = scenario.app.db.query("SELECT * FROM energy_signals WHERE source = 'device_activity'")
    assert [(s["member_id"], s["value"]) for s in signals] == [
        (scenario.member("Husband").id, -0.5)
    ]
    await seen(scenario, litter_box, sani=14)  # not changed after all
    assert len(tasks(scenario)) == 1  # said done: not raised again until it's sorted


async def test_an_alert_lasts_until_the_box_cleans_again(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    tired(scenario)
    litter_box.alert(BOX, "DOME_OPEN", clock.now())
    await seen(scenario, litter_box)
    assert tasks(scenario)[0][0] == "Check the CatGenie"
    assert await scenario.advance(minutes=10) == [ALERT]
    litter_box.clean(BOX, clock.now())
    await seen(scenario, litter_box)
    assert tasks(scenario)[0][1] == "done"


async def test_the_granules_every_so_many_cleans_set_on_the_accounts_page(
    scenario: Scenario, site: httpx.AsyncClient, litter_box: FakeCatGenie
) -> None:
    tired(scenario)
    csrf = await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "Top up the granules every" in page.text
    device = scenario.app.services.maybe(keys.catgenie).devices()[0]  # type: ignore[union-attr]
    saved = await site.post(
        f"/family/catgenie/granules/{device.id}", data={"csrf": csrf, "every": "3"}
    )
    assert saved.status_code == 303
    assert "a granule top-up every 3 cleans, counted from now" in await flash(site, "/accounts")
    for _ in range(2):
        litter_box.clean(BOX, clock.now())
        await seen(scenario, litter_box)
    assert tasks(scenario) == []
    litter_box.clean(BOX, clock.now())
    await seen(scenario, litter_box)
    assert tasks(scenario)[0][0] == "Top up the CatGenie's granules"
    assert await scenario.advance(minutes=10) == [GRANULES]
    said = await ask(scenario, "Do the granules need topping up?", "litter_box")
    assert "Granules: 3 cleans since they were last topped up (a top-up every 3)." in said
    await scenario.tap("Husband", "Done")
    page = await site.get("/accounts")
    assert "0 since the last top-up" in page.text  # the count starts again
    for _ in range(3):
        litter_box.clean(BOX, clock.now())
        await seen(scenario, litter_box)
    assert [t[1] for t in tasks(scenario)] == ["done", "open"]  # and comes round again
    blank = await site.post(f"/family/catgenie/granules/{device.id}", data={"csrf": csrf})
    assert blank.status_code == 303
    assert "no granule reminders" in await flash(site, "/accounts")


async def test_an_error_at_night_is_for_either_of_you(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    clock.advance(timedelta(hours=14, minutes=20))  # 23:20: both in quiet hours
    await seen(scenario, litter_box, error="HEATER_FAULT")
    assert scenario.app.db.scalar("SELECT either FROM tasks") == 1
    assert await scenario.advance(hours=7) == []  # 06:30: nobody's up
    assert await scenario.advance(minutes=30) == [ERROR]  # 07:00, his quiet hours end


async def test_paused_litter_box_nudges_wait(scenario: Scenario, litter_box: FakeCatGenie) -> None:
    tired(scenario)
    await scenario.say("Husband", "/pause litter 2 hours")
    await seen(scenario, litter_box, sani=15)
    assert LOW not in await scenario.advance(minutes=30)
    assert LOW in await scenario.advance(hours=2)


async def test_asked_about_it_with_a_chore_open(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    tired(scenario)
    await seen(scenario, litter_box, sani=15)
    await scenario.advance(minutes=10)
    said = await ask(scenario, "Is the litter box ok?", "litter_box")
    assert "15% sani-solution left" in said
    assert "Open chore: Change the CatGenie's sani-solution cartridge, Husband's, asked at" in said


async def test_a_refused_sign_in_tells_the_admins_once(
    scenario: Scenario, litter_box: FakeCatGenie
) -> None:
    litter_box.revoke()
    for _ in range(3):
        clock.advance(timedelta(minutes=10))
        await scenario.run_periodic("devices.litter_box")
    await scenario.app.outbox.flush()
    told = [t for t in scenario.inbox("Erin") if t.startswith("CatGenie stopped answering")]
    assert len(told) == 1 and "Link the litter box again" in told[0]
    assert scenario.inbox("Husband") == []  # not an admin


# ----- F41a, bug #197: the Whoosh counts cleans, not a percent -----------------------------

WHOOSH = "SFU0000001"


async def test_the_whoosh_says_cleans_left_and_runs_low_at_thirty(
    scenario: Scenario, fake_catgenie: FakeCatGenie, site: httpx.AsyncClient
) -> None:
    fake_catgenie.add_box(WHOOSH, "Whoosh", "device_whoosh")
    watcher = scenario.app.services.get(keys.catgenie)
    await watcher.send_code(PHONE)
    await watcher.link(scenario.member("Erin"), PHONE, CODE)
    fake_catgenie.set(WHOOSH, sani=31)
    await scenario.run_periodic("devices.litter_box")
    await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "Whoosh · ready, 31 cleans of sani-solution left" in page.text
    assert "31%" not in page.text
    tired(scenario)
    fake_catgenie.set(WHOOSH, sani=30)
    clock.advance(timedelta(minutes=10))
    await scenario.run_periodic("devices.litter_box")
    assert tasks(scenario)[0][0] == "Change the Whoosh's sani-solution cartridge"
    assert await scenario.advance(minutes=10) == [
        "The Whoosh is running low on sani-solution (about 30 cleans left). Swap in a new "
        "cartridge when you can?"
    ]
    home = await site.get("/")
    assert "30 cleans of sani-solution left" in home.text
    assert "30%" not in home.text
