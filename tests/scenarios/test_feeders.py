"""32: the pet feeders' chores. When a feeder runs low, runs out or jams, whoever has more room
hears about it 10 minutes on; the feeder sorting itself takes the nudge back; asked "has the
cat been fed?", Themi reads it. The clock starts on Wednesday 21 October 2026, 09:00 (Los
Angeles). One feeder is Tuya's standard kind, with a food level; the other reports a fault
bitmap of its own."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from tests.fakes.tuya import ACCESS_ID, SECRET, FakeTuya
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_appliance_status import ask, tool_names, tool_result
from themi import clock
from themi.accounts import SYSTEM
from themi.core import keys

FEEDER, MOCHI = "ebfeeder1", "ebfeeder2"
LOW = "The cat feeder is running low on food (about 15% left). Top it up when you can?"
OUT = "The cat feeder is out of food. Fill it before the next meal?"
STUCK = (
    "Mochi's feeder needs a hand: the food's stuck (motor fault). Clear it so the next meal "
    "comes out?"
)


@pytest.fixture
async def feeders(scenario: Scenario, fake_tuya: FakeTuya) -> FakeTuya:
    """Both feeders, linked and read once (the starting point: fed and fine)."""
    fake_tuya.add_feeder(FEEDER, "Cat Feeder")
    fake_tuya.add_feeder(MOCHI, "Mochi's feeder", "fault")
    watcher = scenario.app.services.maybe(keys.tuya)
    assert watcher is not None
    await watcher.link(scenario.member("Erin"), ACCESS_ID, SECRET, "us")
    await scenario.run_periodic("devices.feeders")
    return fake_tuya


async def seen(scenario: Scenario, fake: FakeTuya, device: str, status: str) -> None:
    """The feeder reports `status`, and a read comes round (10 minutes on)."""
    fake.set_status(device, status)
    clock.advance(timedelta(minutes=10))
    await scenario.run_periodic("devices.feeders")
    await scenario.app.outbox.flush()


def tasks(scenario: Scenario) -> list[tuple[str, str, int]]:
    return [
        (r["title"], r["status"], r["assignee"])
        for r in scenario.app.db.query("SELECT * FROM tasks ORDER BY id")
    ]


def tired(scenario: Scenario) -> None:
    scenario.app.services.energy.record(scenario.member("Erin"), "text_note", -3, "worn out")


async def test_linking_from_the_accounts_page(
    scenario: Scenario, site: httpx.AsyncClient, fake_tuya: FakeTuya
) -> None:
    fake_tuya.add_feeder(FEEDER, "Cat Feeder")
    fake_tuya.add_device("ebfountain3", "Water fountain", "cwysj", "pqxfountain003")
    await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "Pet feeders" in page.text and "Link Tuya" in page.text
    done = await site.post(
        "/family/tuya/link",
        data={"csrf": csrf_of(page.text), "access_id": ACCESS_ID, "secret": SECRET, "region": "us"},
    )
    assert done.status_code == 303
    assert done.headers["location"] == "/accounts?open=tuya#tuya"
    text = await flash(site, "/accounts")
    assert "Linked Tuya. Found Cat Feeder, Water fountain." in text
    assert SECRET not in text

    await scenario.run_periodic("devices.feeders")
    page = await site.get("/accounts")
    assert "Cat Feeder · plenty of food (64% left)" in page.text
    assert "<code>surplus_grain</code>: 64" in page.text  # its data points, for a mapping
    watcher = scenario.app.services.maybe(keys.tuya)
    assert watcher is not None
    fountain = next(d for d in watcher.devices() if d.name == "Water fountain")
    mapped = await site.post(
        f"/family/tuya/devices/{fountain.id}",
        data={"csrf": csrf_of(page.text), "appliance": "feeder"},
    )
    assert mapped.status_code == 303
    assert scenario.app.store.get_device(fountain.id).appliance == "feeder"


async def test_no_devices_says_to_link_the_app_account(
    scenario: Scenario, site: httpx.AsyncClient, fake_tuya: FakeTuya
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post(
        "/family/tuya/link",
        data={"csrf": csrf, "access_id": ACCESS_ID, "secret": SECRET, "region": "us"},
    )
    assert "link the SmartLife app account to the cloud project" in await flash(site, "/accounts")


async def test_only_an_admin_links_it(
    scenario: Scenario, site: httpx.AsyncClient, fake_tuya: FakeTuya
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    response = await site.post(
        "/family/tuya/link",
        data={"csrf": csrf, "access_id": ACCESS_ID, "secret": SECRET, "region": "us"},
    )
    assert response.status_code == 403
    assert fake_tuya.calls == []


async def test_running_low_goes_to_whoever_has_more_room(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    tired(scenario)
    husband = scenario.member("Husband")
    await seen(scenario, feeders, FEEDER, "standard_low")
    assert tasks(scenario) == [("Refill the cat feeder", "open", husband.id)]
    assert await scenario.advance(minutes=9) == []  # a bounce in the reading waits
    assert await scenario.advance(minutes=1) == [LOW]
    assert scenario.inbox("Husband") == [LOW]
    assert scenario.last_buttons("Husband") == ["Done", "Later"]
    assert scenario.inbox("Erin") == []
    await seen(scenario, feeders, FEEDER, "standard_low")  # still low: no second task
    assert len(tasks(scenario)) == 1


async def test_refilled_within_ten_minutes_sends_nothing(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    await seen(scenario, feeders, FEEDER, "standard_low")
    feeders.set_status(FEEDER, "standard_plenty")
    clock.advance(timedelta(minutes=5))
    await scenario.run_periodic("devices.feeders")
    assert tasks(scenario)[0][1] == "cancelled"
    assert await scenario.advance(hours=1) == []
    assert scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'feeder'") == []


async def test_running_low_then_out_asks_again_then_the_refill_closes_it(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    tired(scenario)
    await seen(scenario, feeders, FEEDER, "standard_low")
    assert await scenario.advance(minutes=10) == [LOW]
    await seen(scenario, feeders, FEEDER, "standard_empty")
    assert scenario.inbox("Husband") == [LOW, OUT]  # the same chore, asked again
    assert len(tasks(scenario)) == 1
    await seen(scenario, feeders, FEEDER, "standard_plenty")
    assert tasks(scenario)[0][1] == "done"  # asked, and now it's full: someone saw to it
    signals = scenario.app.db.query("SELECT * FROM energy_signals WHERE source = 'device_activity'")
    assert signals == []  # the feeder can't say who filled it


async def test_done_is_a_small_effort_for_whoever_did_it(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    tired(scenario)
    await seen(scenario, feeders, FEEDER, "standard_low")
    await scenario.advance(minutes=10)
    await scenario.tap("Husband", "Done")
    assert tasks(scenario)[0][1] == "done"
    signals = scenario.app.db.query("SELECT * FROM energy_signals WHERE source = 'device_activity'")
    assert [(s["member_id"], s["value"]) for s in signals] == [
        (scenario.member("Husband").id, -0.5)
    ]
    await seen(scenario, feeders, FEEDER, "standard_low")  # not refilled after all
    assert len(tasks(scenario)) == 1  # said done: not raised again until it's sorted


async def test_with_device_activity_off_done_counts_for_nothing(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    tired(scenario)
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(SYSTEM, husband.id, tracking={"device_activity": False})
    await seen(scenario, feeders, FEEDER, "standard_low")
    await scenario.advance(minutes=10)
    await scenario.tap("Husband", "Done")
    assert (
        scenario.app.db.query("SELECT 1 FROM energy_signals WHERE member_id = ?", (husband.id,))
        == []
    )


async def test_a_jam_names_the_feeder_and_cant_wait_for_tomorrow(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    tired(scenario)
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(SYSTEM, husband.id, daily_limit=0)  # time-bound anyway
    await seen(scenario, feeders, MOCHI, "fault_motor")
    assert tasks(scenario) == [("Unjam Mochi's feeder", "open", husband.id)]
    assert await scenario.advance(minutes=10) == [STUCK]


async def test_out_of_food_at_night_is_for_either_of_you(
    scenario: Scenario, feeders: FakeTuya
) -> None:
    clock.advance(timedelta(hours=14, minutes=20))  # 23:20: both in quiet hours
    await seen(scenario, feeders, FEEDER, "standard_empty")
    assert scenario.app.db.scalar("SELECT either FROM tasks") == 1
    assert await scenario.advance(hours=7) == []  # 06:30: nobody's up
    assert await scenario.advance(minutes=30) == [OUT]  # 07:00, his quiet hours end
    assert scenario.inbox("Husband") == [OUT] and scenario.inbox("Erin") == []
    await scenario.advance(hours=1)  # 08:00, hers
    assert scenario.inbox("Erin") == [OUT]


async def test_paused_feeder_nudges_wait(scenario: Scenario, feeders: FakeTuya) -> None:
    tired(scenario)
    await scenario.say("Husband", "/pause feeders 2 hours")
    await seen(scenario, feeders, FEEDER, "standard_low")
    assert LOW not in await scenario.advance(minutes=30)
    assert LOW in await scenario.advance(hours=2)


async def test_asked_whether_the_cat_was_fed(scenario: Scenario, feeders: FakeTuya) -> None:
    clock.advance(timedelta(minutes=30))
    feeders.fed(FEEDER, 2, clock.now())  # 9:30
    clock.advance(timedelta(minutes=30))
    await scenario.run_periodic("devices.feeders")  # the log's read hourly
    said = await ask(scenario, "Has the cat been fed this morning?", "feeder")
    assert "appliance_status" in tool_names(scenario)  # the words chose the devices group
    assert (
        "Cat Feeder (feeder), read just now: plenty of food (64% left); last fed 9:30 am " in said
    )
    assert "today, 2 portions." in said
    assert "Mochi's feeder (feeder), read just now: fine." in said


async def test_asked_about_one_with_a_chore_open(scenario: Scenario, feeders: FakeTuya) -> None:
    tired(scenario)
    await seen(scenario, feeders, MOCHI, "fault_motor")
    await scenario.advance(minutes=10)
    said = await ask(scenario, "Is the feeder ok?", "feeder")
    assert "Mochi's feeder (feeder), read just now: the food's stuck (motor fault)." in said
    assert "Open chore: Unjam Mochi's feeder, Husband's, asked at" in said


async def test_a_lapsed_plan_tells_the_admins_once(scenario: Scenario, feeders: FakeTuya) -> None:
    feeders.lapse()
    for _ in range(3):
        clock.advance(timedelta(minutes=10))
        await scenario.run_periodic("devices.feeders")
    await scenario.app.outbox.flush()
    told = [t for t in scenario.inbox("Erin") if t.startswith("Tuya stopped answering")]
    assert len(told) == 1 and "extend it on Tuya's site" in told[0]
    assert scenario.inbox("Husband") == []  # not an admin


# ----- feeding now (F39a, bug #194: "Feed Juneau" went on Things to Buy) ------------------

JUNEAU = "ebjuneau3"


@pytest.fixture
async def juneau(scenario: Scenario, feeders: FakeTuya) -> FakeTuya:
    """Juneau's feeder too: the family's own model (from its capture), named for the cat."""
    feeders.add_feeder(JUNEAU, "Juneau", "family")
    watcher = scenario.app.services.maybe(keys.tuya)
    assert watcher is not None
    await watcher.link(scenario.member("Erin"), ACCESS_ID, SECRET, "us")
    return feeders


async def feed(
    scenario: Scenario, text: str, args: dict[str, object], *, done: bool = False
) -> str:
    """`done`: fed as asked, which is the whole answer (the turn ends there, P2b)."""
    scenario.primary.queue_tool_call("feed_pet", args)
    if not done:
        scenario.primary.queue_text("Here's how it went.")
    return " ".join(await scenario.say("Husband", text))


async def test_feed_juneau_dispenses_from_juneaus_feeder(
    scenario: Scenario, juneau: FakeTuya
) -> None:
    said = await feed(scenario, "Feed Juneau", {"feeder": "Juneau"}, done=True)
    assert "feed_pet" in tool_names(scenario)  # "feed" chose the devices group
    assert juneau.commands == {JUNEAU: [{"code": "manual_feed", "value": 1}]}
    assert "Fed Juneau: 1 portion." in said
    action = scenario.app.db.one("SELECT * FROM pending_actions WHERE category = 'pet_feed'")
    assert action is not None and action["status"] == "done"  # asked: their yes
    lists = scenario.app.db.scalar("SELECT COUNT(*) FROM list_items WHERE name LIKE '%Juneau%'")
    assert not lists


async def test_portions_and_every_feeder(scenario: Scenario, juneau: FakeTuya) -> None:
    args = {"feeder": "Juneau's feeder", "portions": 2}
    said = await feed(scenario, "Give Juneau's feeder 2 portions", args, done=True)
    assert juneau.commands[JUNEAU] == [{"code": "manual_feed", "value": 2}]
    assert "Fed Juneau: 2 portions." in said
    await feed(scenario, "Feed all the cats", {"feeder": "all"}, done=True)
    assert set(juneau.commands) == {FEEDER, MOCHI, JUNEAU}


async def test_the_cat_with_three_feeders_asks_which(scenario: Scenario, juneau: FakeTuya) -> None:
    await feed(scenario, "Feed the cat", {"feeder": "the cat"})
    assert "Which feeder? The linked ones: Cat Feeder, Mochi's feeder, Juneau." in tool_result(
        scenario
    )
    assert juneau.commands == {}


async def test_an_offline_feeder_says_nothing_can_come_out(
    scenario: Scenario, juneau: FakeTuya
) -> None:
    juneau.offline(JUNEAU)
    await scenario.run_periodic("devices.feeders")  # read as offline
    said = await feed(scenario, "Feed Juneau", {"feeder": "Juneau"})
    assert "Juneau's feeder is offline, so nothing can come out right now." in said
    assert juneau.commands == {}
    assert scenario.app.db.one("SELECT 1 FROM pending_actions") is None


async def test_one_that_drops_off_fails_and_can_be_tried_again(
    scenario: Scenario, juneau: FakeTuya
) -> None:
    juneau.offline(JUNEAU)  # since the last read
    await feed(scenario, "Feed Juneau", {"feeder": "Juneau"})
    assert "Tried but it failed" in tool_result(scenario)  # never "done" with nothing fed
    action = scenario.app.db.one("SELECT * FROM pending_actions WHERE category = 'pet_feed'")
    assert action is not None and action["status"] == "failed"
    assert juneau.commands == {}


async def test_the_model_feeding_on_its_own_waits_for_a_yes(
    scenario: Scenario, juneau: FakeTuya
) -> None:
    await feed(scenario, "Juneau's been meowing all evening", {"feeder": "Juneau"})
    assert "Staged for approval" in tool_result(scenario)  # their words didn't ask for it
    assert juneau.commands == {}
