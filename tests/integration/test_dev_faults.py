"""D5c: the control panel's faults, the Safeway helper, travel and scenes, through the
simulator, against `make dev`'s wiring. Each fault leads to what its connector's own tests
expect."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from tests.fakes.roborock import CODE, EMAIL
from tests.fixtures.dev import Panel
from themi import clock
from themi.connectors.travel import TravelError
from tools.dev import controls
from tools.dev.controls import SECTIONS, Values
from tools.dev.scenes import SCENES, At, Do, Scene, Wait


def account(panel: Panel, address: str) -> dict:
    (row,) = panel.rows("SELECT * FROM linked_accounts WHERE address = ?", address)
    return row


# ----- faults -------------------------------------------------------------------------------


async def test_access_revoked_at_google_needs_relinking(panel: Panel) -> None:
    await panel.ok("email", "fault", fault="Access revoked at Google", person="Erin")
    assert not account(panel, "erin@gmail.com")["enabled"]  # the "Needs relinking" chip
    assert account(panel, "husband@gmail.com")["enabled"]


async def test_gmail_busy_backs_off_and_loses_nothing(panel: Panel) -> None:
    await panel.run.fakes.check_now("gmail.poll")  # the first sync, as when dev starts
    clock.advance(timedelta(minutes=5))
    await panel.ok("email", "fault", fault="Gmail is busy (429)", person="Erin", seconds="600")
    after = account(panel, "erin@gmail.com")["poll_after"]
    assert after >= (clock.now() + timedelta(seconds=600)).isoformat()[:19]  # it waits
    await panel.ok("email", "preset", person="Erin", preset="A school notice")
    await panel.ok("email", "preset", person="Husband", preset="A bill due Friday")
    subjects = [r["subject"] for r in panel.rows("SELECT subject FROM emails ORDER BY id")]
    assert subjects == [
        "Field trip permission slip due Thursday",
        "Your bill is ready: $84.20 due Friday",
    ]  # each once


async def test_lg_turning_the_token_down_and_working_again(panel: Panel) -> None:
    await panel.ok("laundry", "fault", fault="LG revokes the token")
    await panel.ok("laundry", "state", machine="Washer", state="Running")
    assert panel.device_state("Washer") != "running"  # Themi can't read it
    happened = await panel.ok("laundry", "fault", fault="LG works again")
    assert "thinqpat_family_token" in happened  # what to relink with
    await panel.ok("laundry", "state", machine="Washer", state="Running")
    assert panel.device_state("Washer") == "running"


async def test_roborock_signed_out_says_link_it_again_and_relinks(panel: Panel) -> None:
    await panel.ok("vacuum", "fault", fault="The sign-in expires")
    watcher = panel.run.runtime.app.services.roborock
    assert watcher is not None and watcher.account.problem()  # the "Link it again" chip
    admin = panel.run.runtime.app.store.member_by_name("Erin")
    assert admin is not None
    await watcher.send_code(EMAIL)  # as the Accounts page does
    await watcher.link(admin, EMAIL, CODE)
    assert watcher.account.problem() is None
    await panel.ok("vacuum", "status", status="Cleaning")
    assert panel.device_state("Robbie") == "cleaning"


async def test_home_connect_revoked_then_approved_again(panel: Panel) -> None:
    await panel.ok("dishwasher", "fault", fault="Access revoked")
    await panel.ok("dishwasher", "state", state="Running", minutes="60")
    assert panel.device_state("Dishwasher") != "Run"
    await panel.ok("dishwasher", "fault", fault="Approve it again")
    await panel.ok("dishwasher", "state", state="Running", minutes="60")
    assert panel.device_state("Dishwasher") == "Run"


async def test_the_wall_failing_once_is_retried_without_doubles(panel: Panel) -> None:
    await panel.ok("wall", "fault", fault="Reading the to-dos fails")
    await panel.ok("wall", "add", title="Fix the gate")
    await panel.ok("wall", "add", title="Sort photos")
    assert panel.rows("SELECT title FROM tasks") == []  # Themi waits before trying again
    clock.advance(timedelta(minutes=2))
    await panel.run.fakes.check_now("cozyla.sync")
    await panel.run.fakes.check_now("cozyla.sync")
    titles = [r["title"] for r in panel.rows("SELECT title FROM tasks ORDER BY title")]
    assert titles == ["Fix the gate", "Sort photos"]
    assert sorted(t["todoTitle"] for t in panel.run.fakes.cozyla.todos.values()) == titles


async def test_keep_losing_a_save_sends_it_again_once(panel: Panel) -> None:
    await panel.ok("home", "fault", fault="Keep loses the next save")
    await panel.ok("groceries", "add", item="Eggs")  # Themi's list, to both people's Keep
    await panel.run.fakes.check_now("groceries.keep")  # the lost save
    await panel.run.fakes.check_now("groceries.keep")
    keep = panel.run.fakes.keep
    for address in ("erin@gmail.com", "husband@gmail.com"):
        assert keep.unchecked_texts(address).count("eggs") == 1


# ----- the Safeway helper -------------------------------------------------------------------


async def test_a_cart_job_answered_from_the_panel_lands_in_its_results(panel: Panel) -> None:
    app = panel.run.runtime.app
    assert app.services.safeway is not None
    erin = app.store.member_by_name("Erin")
    assert erin is not None
    items = [{"name": "milk", "qty": 1}, {"name": "eggs", "qty": 2}]
    app.services.safeway.queue(erin, items, None)
    state = (await panel.client.get("/control/state")).json()["safeway"]
    assert state == ["Helper: connected", "Job 1 (queued): milk, eggs"]

    happened = await panel.ok("safeway", "answer", outcome="Added", **{"except": "Milk: not found"})
    assert happened == "Safeway helper: cart job 1 answered: 1 not found, 1 added"
    (job,) = panel.rows("SELECT status, results FROM safeway_jobs")
    assert job["status"] == "done"
    results = {line["name"]: line["status"] for line in json.loads(job["results"])["items"]}
    assert results == {"milk": "not_found", "eggs": "added"}

    nothing = await panel.act("safeway", "answer", outcome="Added")
    assert nothing.json()["error"] == "no cart job is waiting"


async def test_a_revoked_helper_is_told_to_pair_again(panel: Panel) -> None:
    safeway = panel.run.runtime.app.services.safeway
    assert safeway is not None
    for helper in safeway.helpers():
        safeway.revoke(helper.id)  # Disconnect, on the Safeway page
    refused = await panel.act("safeway", "answer", outcome="Added")
    assert refused.json()["error"] == "the helper isn't connected: pair it again"
    await panel.ok("safeway", "pair", person="Husband")
    assert (await panel.act("safeway", "answer", outcome="Added")).json()["error"] == (
        "no cart job is waiting"
    )


# ----- travel -------------------------------------------------------------------------------


async def test_travel_is_set_from_the_panel(panel: Panel) -> None:
    await panel.ok("travel", "minutes", minutes="45")
    await panel.ok("travel", "place", address="Smile Dental", lat="37.7", lon="-122.4")
    await panel.ok("travel", "fail", kind="Drive time (TomTom)", status="503")
    travel = panel.run.fakes.travel
    assert (travel.minutes, travel.places) == (45, {"smile dental": (37.7, -122.4)})
    client = travel.client()
    found = await client.geocode("Smile Dental")
    assert found is not None
    with pytest.raises(TravelError):
        await client.route(found, found, clock.now())


# ----- scenes -------------------------------------------------------------------------------


def test_every_scene_step_is_a_real_action() -> None:
    actions = {(s.id, a.id): a for s in SECTIONS for a in s.actions}
    for scene in SCENES:
        for step in scene.steps:
            if isinstance(step, Do):
                action = actions[(step.section, step.action)]
                Values(action.fields, step.values)  # its form is complete and its choices exist


def test_at_skips_to_the_next_such_time() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    wed_9 = datetime(2026, 10, 21, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert At("10:00").until(wed_9) == timedelta(hours=1)
    assert At("08:00").until(wed_9) == timedelta(hours=23)
    assert At("09:00").until(wed_9) == timedelta(0)
    assert At("08:00", "Tue").until(wed_9) == timedelta(days=5, hours=23)
    assert At("12:00", "Wed").until(wed_9) == timedelta(hours=3)


async def test_a_scene_that_fails_says_which_step(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = Scene("Broken", "", (Wait(5), Do("wall", "tick", {"title": "Nothing like it"})))
    monkeypatch.setattr(controls, "SCENES", (broken,))
    response = await panel.client.post("/control/scene", json={"name": "Broken"})
    assert response.json()["error"] == (
        "step 2 (wall · tick (Nothing like it)): the wall's list has no open 'Nothing like it'"
    )
    notices = [e.text for e in panel.sim.transcript(0)]
    assert notices[0] == "⚙ Scene: Broken"
    assert notices[1].startswith("Skipped ahead 5m")
    assert notices[-1].startswith("⚙ The scene stopped at step 2")
    unknown = await panel.client.post("/control/scene", json={"name": "Nope"})
    assert unknown.json()["error"] == "there's no scene called 'Nope'"
