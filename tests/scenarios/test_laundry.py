"""31: the laundry. The washer finishing nudges whoever has more room to move the load; the
dryer starting settles it; a load left past the fresh hours is offered a rinse timed to
finish as that person's next good window begins. The clock starts on Wednesday
21 October 2026, 09:00 (Los Angeles); the washer and dryer are LG's, read through pushes."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from tests.fakes.thinq import TOKEN, FakeThinq
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import START, Scenario
from themi import clock
from themi.core.laundry import RESCUE_TEXT, SUPERSEDED_TEXT, WASHED_TEXT, Laundry
from themi.core.tasks import clock_words
from themi.energy.windows import next_window

WASHER, DRYER = "lg-washer-1", "lg-dryer-1"
TZ = START.tzinfo


@pytest.fixture
async def laundry_room(scenario: Scenario, fake_thinq: FakeThinq) -> FakeThinq:
    """The washer and dryer, linked and read once (the starting point), pushes connected."""
    fake_thinq.add_device(WASHER, "DEVICE_WASHER", "Washer")
    fake_thinq.add_device(DRYER, "DEVICE_DRYER", "Dryer", "DLEX4000W")
    watcher = scenario.app.services.thinq
    assert watcher is not None
    await watcher.link(scenario.member("Erin"), TOKEN, "US")
    await scenario.run_periodic("devices.thinq")
    await scenario.run_periodic("devices.thinq_push")
    assert watcher.push.connected()
    return fake_thinq


def laundry(scenario: Scenario) -> Laundry:
    assert scenario.app.services.laundry is not None
    return scenario.app.services.laundry


async def pushed(scenario: Scenario, fake: FakeThinq, device: str, word: str) -> None:
    fake.push_state(device, word)
    await scenario.run_periodic("devices.thinq_push")
    await scenario.app.outbox.flush()


async def wash(scenario: Scenario, fake: FakeThinq) -> str:
    """A whole wash: running now, finished an hour on. Returns when it finished, in words."""
    await pushed(scenario, fake, WASHER, "RUNNING")
    clock.advance(timedelta(hours=1))
    await pushed(scenario, fake, WASHER, "END")
    return clock_words(clock.now().astimezone(TZ))


def loads(scenario: Scenario) -> list[str]:
    return [r["status"] for r in scenario.app.db.query("SELECT status FROM laundry_loads")]


def tasks(scenario: Scenario) -> list[tuple[str, str, int]]:
    return [
        (r["title"], r["status"], r["assignee"])
        for r in scenario.app.db.query("SELECT * FROM tasks ORDER BY id")
    ]


async def test_the_washer_finishing_goes_to_whoever_has_more_room(
    scenario: Scenario, laundry_room: FakeThinq
) -> None:
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    scenario.app.services.energy.record(erin, "text_note", -3, "a draining morning")
    at = await wash(scenario, laundry_room)
    assert scenario.inbox("Husband")[-1] == WASHED_TEXT.format(at=at)
    assert scenario.last_buttons("Husband") == ["Moved it", "Later"]
    assert not any("washer" in text for text in scenario.inbox("Erin"))
    ((title, status, assignee),) = tasks(scenario)
    assert (title, status, assignee) == ("Move the wet load to the dryer", "open", husband.id)
    reason = scenario.app.db.scalar("SELECT assign_reason FROM tasks")
    assert reason == "Husband seems to have the most room right now."
    assert not any(ch.isdigit() for ch in reason)


async def test_the_dryer_starting_settles_the_load(
    scenario: Scenario, laundry_room: FakeThinq
) -> None:
    await wash(scenario, laundry_room)
    clock.advance(timedelta(minutes=40))
    await pushed(scenario, laundry_room, DRYER, "DRYING")
    assert loads(scenario) == ["dried"]
    assert tasks(scenario)[0][1] == "done"
    who = "Erin" if scenario.edits("Erin") else "Husband"
    assert (
        scenario.edits(who)[-1]["text"] == "Marked done: Move the wet load to the dryer. Thank you."
    )
    clock.advance(timedelta(hours=9))
    assert await scenario.run_periodic("laundry.fresh") == 0  # nothing left to rescue


async def test_tapping_moved_it_settles_it_too(scenario: Scenario, laundry_room: FakeThinq) -> None:
    scenario.app.services.energy.record(scenario.member("Erin"), "text_note", -3, "tired")
    await wash(scenario, laundry_room)
    await scenario.tap("Husband", "Moved it")
    assert loads(scenario) == ["done"]
    clock.advance(timedelta(hours=9))
    assert await scenario.run_periodic("laundry.fresh") == 0


async def test_a_new_wash_supersedes_the_wet_load(
    scenario: Scenario, laundry_room: FakeThinq
) -> None:
    scenario.app.services.energy.record(scenario.member("Erin"), "text_note", -3, "tired")
    await wash(scenario, laundry_room)
    clock.advance(timedelta(hours=2))
    await pushed(scenario, laundry_room, WASHER, "RUNNING")  # washed again, before moving it
    assert loads(scenario) == ["superseded"]
    assert tasks(scenario)[0][1] == "cancelled"
    assert scenario.edits("Husband")[-1]["text"] == SUPERSEDED_TEXT
    clock.advance(timedelta(hours=1))
    await pushed(scenario, laundry_room, WASHER, "END")
    assert loads(scenario) == ["superseded", "wet"]
    assert [t[1] for t in tasks(scenario)] == ["cancelled", "open"]


async def test_a_load_left_past_eight_hours_is_offered_a_timed_rinse(
    scenario: Scenario, laundry_room: FakeThinq
) -> None:
    erin = scenario.member("Erin")
    scenario.app.services.energy.record(scenario.member("Husband"), "text_note", -3, "tired")
    finished = await wash(scenario, laundry_room)  # 10 am
    assert scenario.inbox("Erin")[-1] == WASHED_TEXT.format(at=finished)
    await scenario.tap("Erin", "Later")
    clock.advance(timedelta(hours=7, minutes=45))
    assert await scenario.run_periodic("laundry.fresh") == 0  # still fresh
    clock.advance(timedelta(minutes=15))
    assert await scenario.run_periodic("laundry.fresh") == 1
    # She put it off, so the rinse is what comes back when that runs out.
    sent = len(scenario.inbox("Erin"))
    await scenario.run_periodic("tasks.resurface")
    await scenario.app.outbox.flush()
    now = clock.now()
    start, ready = laundry(scenario).rinse_times(erin, now)
    assert ready - start == timedelta(minutes=30)
    tz = TZ
    assert tz is not None
    expected = RESCUE_TEXT.format(
        at=finished,
        start=clock_words(start.astimezone(tz)),
        ready=clock_words(ready.astimezone(tz)),
    )
    outbox = scenario.app.db.one(
        "SELECT status, text, send_after, deadline FROM outbox WHERE member_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (erin.id,),
    )
    assert outbox is not None and outbox["text"] == expected
    assert datetime.fromisoformat(outbox["deadline"]) == start
    if outbox["status"] == "queued":  # held for a better moment, but never past the start
        assert datetime.fromisoformat(outbox["send_after"]) <= start
        await scenario.advance(minutes=(start - now).total_seconds() / 60)
    assert scenario.inbox("Erin")[sent:] == [expected]
    assert scenario.last_buttons("Erin") == ["Rinse started", "Later"]
    ((title, status, _),) = tasks(scenario)
    assert (title, status) == ("Rinse the washer load", "open")


async def test_a_rinse_for_the_morning_is_suggested_in_the_morning(
    scenario: Scenario, laundry_room: FakeThinq
) -> None:
    """Past the fresh hours at 10 pm, Erin's quiet hours have begun: the next good window is
    the morning, so the rinse is suggested then, not at night."""
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    scenario.app.store.update_family(erin, laundry_fresh_hours=12)
    scenario.app.services.energy.record(husband, "text_note", -3, "tired")
    finished = await wash(scenario, laundry_room)  # 10 am
    clock.advance(timedelta(hours=12))  # 10 pm
    assert await scenario.run_periodic("laundry.fresh") == 1
    model = scenario.app.services.taskboard.matcher.model  # type: ignore[union-attr]
    row = scenario.app.db.one("SELECT rinse_from, ready_at FROM laundry_loads")
    assert row is not None
    start, ready = (datetime.fromisoformat(row[k]).astimezone(TZ) for k in row)
    window = next_window(model, erin, clock.now() + timedelta(minutes=30))
    # The window opens as her quiet hours end, so the rinse starts then rather than before,
    # when nothing could reach her, and finishes just into it.
    assert start == window and ready == window + timedelta(minutes=30)
    assert (start.date() - clock.now().astimezone(TZ).date()).days == 1  # tomorrow morning
    texts = await scenario.advance(hours=1)
    assert not any("rinse" in text for text in texts)  # not at night
    texts = await scenario.advance(minutes=(start - clock.now()).total_seconds() / 60)
    assert texts == [
        RESCUE_TEXT.format(
            at=f"yesterday at {finished}", start=clock_words(start), ready=clock_words(ready)
        )
    ]


async def test_the_fresh_hours_are_the_familys(
    scenario: Scenario, site: httpx.AsyncClient, laundry_room: FakeThinq
) -> None:
    await sign_in(scenario, site, "Erin")
    page = await site.get("/family")
    assert "Fresh for (hours)" in page.text
    response = await site.post(
        "/family/laundry",
        data={"csrf": csrf_of(page.text), "fresh_hours": "4", "rinse_minutes": "20"},
    )
    assert response.status_code == 303
    assert "Laundry settings saved." in await flash(site, "/family")
    family = scenario.app.store.get_family()
    assert family is not None
    assert (family.laundry_fresh_hours, family.laundry_rinse_minutes) == (4.0, 20)
    await site.post(
        "/family/laundry",
        data={"csrf": csrf_of(page.text), "fresh_hours": "0", "rinse_minutes": "20"},
    )
    assert "Not saved: a wet load stays fresh for 1 to 48 hours." in await flash(site, "/family")

    await wash(scenario, laundry_room)
    clock.advance(timedelta(hours=4))
    assert await scenario.run_periodic("laundry.fresh") == 1


async def test_laundry_nudges_can_be_paused(scenario: Scenario, laundry_room: FakeThinq) -> None:
    for name in ("Erin", "Husband"):
        await scenario.say(name, "/pause laundry 3 hours")
    before = {name: len(scenario.inbox(name)) for name in ("Erin", "Husband")}
    await wash(scenario, laundry_room)
    assert not any(
        "washer" in text for name in before for text in scenario.inbox(name)[before[name] :]
    )
    held = scenario.app.db.query("SELECT status FROM outbox WHERE kind = 'laundry'")
    assert [r["status"] for r in held] == ["queued"]  # held, not lost
    texts = await scenario.advance(hours=3)
    assert any(text.startswith("The washer finished at") for text in texts)
