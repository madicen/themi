"""33: seasonal and long-term maintenance. A due item is offered at most once a day, only
in a good window for whoever does it; done (a tap, chat, the website) is recorded with its
notes, and due dates go on the family calendar. The clock starts on Wednesday 21 October
2026, 09:00 (Los Angeles)."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.autonomy import Decision
from themi.core.maintenance import Item, Maintenance

FILTER_STEPS = ["Turn the furnace off", "Slide the old filter out", "Put the new one in, arrow up"]


def maintenance(scenario: Scenario) -> Maintenance:
    assert scenario.app.services.maintenance is not None
    return scenario.app.services.maintenance


async def add(
    scenario: Scenario,
    name: str = "Change the furnace filter",
    interval: int = 90,
    *,
    months: tuple[int, ...] = (),
    steps: list[str] | None = None,
    owner: str | None = None,
    last_done: date | None = None,
) -> Item:
    item, new = await maintenance(scenario).set(
        scenario.member("Erin"),
        name,
        interval_days=interval,
        months=months,
        guide=FILTER_STEPS if steps is None else steps,
        owner=scenario.member(owner) if owner else None,
        last_done=last_done,
    )
    assert new
    return item


async def offer(scenario: Scenario) -> list[str]:
    """The offer job, then whatever it sent."""
    before = len(scenario.telegram.calls("sendMessage"))
    await scenario.run_periodic("maintenance.offer")
    await scenario.app.outbox.flush()
    return [p["text"] for p in scenario.telegram.calls("sendMessage")[before:]]


def runs(scenario: Scenario) -> list[tuple[str, str, int | None, str | None]]:
    return [
        (r["name"], r["done_on"], r["done_by"], r["notes"])
        for r in scenario.app.db.query(
            "SELECT i.name, r.done_on, r.done_by, r.notes FROM maintenance_runs r "
            "JOIN maintenance_items i ON i.id = r.item_id ORDER BY r.id"
        )
    ]


def low(scenario: Scenario, name: str) -> None:
    scenario.app.services.energy.record(scenario.member(name), "text_note", -3, "wiped out")


# ----- the offer -----------------------------------------------------------------------


async def test_a_due_item_is_offered_with_its_guide_and_done_is_recorded(
    scenario: Scenario,
) -> None:
    await add(scenario, last_done=date(2026, 7, 20))  # 90 days on: due 18 October
    low(scenario, "Husband")  # Erin has the room
    (text,) = await offer(scenario)
    assert text == (
        "Maintenance: Change the furnace filter (every 90 days; last done Mon 20 Jul).\n\n"
        "> - Turn the furnace off\n> - Slide the old filter out\n"
        "> - Put the new one in, arrow up\n\nDone already, or later?"
    )
    assert scenario.inbox("Erin")[-1] == text
    assert scenario.last_buttons("Erin") == ["Done", "Later"]
    assert scenario.app.db.scalar("SELECT kind FROM outbox ORDER BY id DESC LIMIT 1") == (
        "maintenance"
    )
    task = scenario.app.db.one("SELECT * FROM tasks")
    assert task is not None
    assert (task["title"], task["kind"], task["effort"]) == (
        "Change the furnace filter",
        "physical",
        2,
    )
    assert "added this for you" not in text
    await scenario.tap("Erin", "Done")
    assert runs(scenario) == [
        ("Change the furnace filter", "2026-07-20", None, None),
        ("Change the furnace filter", "2026-10-21", scenario.member("Erin").id, None),
    ]
    item = maintenance(scenario).items()[0]
    assert item.task_id is None
    assert maintenance(scenario).next_due(item) == date(2027, 1, 19)
    assert await offer(scenario) == []


async def test_at_most_one_offer_a_day(scenario: Scenario) -> None:
    await add(scenario, "Change the furnace filter")
    await add(scenario, "Test the smoke alarms", 180, steps=[])
    assert len(maintenance(scenario).due()) == 2
    assert len(await offer(scenario)) == 1
    await scenario.tap(scenario.app.store.get_member(_assignee(scenario)).name, "Done")
    assert await offer(scenario) == []  # the first is done, but one a day
    await scenario.advance(hours=6)
    assert await offer(scenario) == []
    clock.advance(timedelta(hours=18))  # Thursday, 09:00
    (text,) = await offer(scenario)
    assert text.startswith("Maintenance: Test the smoke alarms (every 180 days;")


async def test_one_still_open_holds_the_rest_back_for_a_week(scenario: Scenario) -> None:
    await add(scenario, "Change the furnace filter")
    await add(scenario, "Test the smoke alarms", 180, steps=[])
    assert len(await offer(scenario)) == 1
    clock.advance(timedelta(days=1))
    assert await offer(scenario) == []  # the furnace filter is still open
    clock.advance(timedelta(days=6, minutes=15))
    (text,) = await offer(scenario)
    assert "smoke alarms" in text


async def test_offered_only_in_a_good_window(scenario: Scenario) -> None:
    await add(scenario, owner="Erin")
    erin = scenario.member("Erin")
    clock.advance(timedelta(hours=13))  # 22:00: Erin's quiet hours
    assert not maintenance(scenario).in_window(erin, clock.now())
    assert await offer(scenario) == []
    clock.advance(timedelta(hours=11))  # Thursday 09:00, but a hard morning
    low(scenario, "Erin")
    assert not maintenance(scenario).in_window(erin, clock.now())
    assert await offer(scenario) == []
    assert scenario.app.db.query("SELECT 1 FROM tasks") == []
    clock.advance(timedelta(days=1))  # Friday morning, recovered
    assert maintenance(scenario).in_window(erin, clock.now())
    (text,) = await offer(scenario)
    assert text.startswith("Maintenance: Change the furnace filter")
    assert scenario.inbox("Erin")[-1] == text


async def test_whoever_has_more_room_gets_it(scenario: Scenario) -> None:
    await add(scenario)
    low(scenario, "Erin")
    (text,) = await offer(scenario)
    assert scenario.inbox("Husband")[-1] == text
    assert _assignee(scenario) == scenario.member("Husband").id


async def test_out_of_season_its_not_offered(scenario: Scenario) -> None:
    await add(scenario, "Fertilize the fruit trees", 42, months=(3, 4, 5, 6, 7, 8, 9))
    item = maintenance(scenario).items()[0]
    assert maintenance(scenario).next_due(item) == date(2027, 3, 1)
    assert await offer(scenario) == []


async def test_later_asks_again_the_next_day(scenario: Scenario) -> None:
    await add(scenario, owner="Erin")
    await offer(scenario)
    await scenario.tap("Erin", "Later")
    asked = len(scenario.inbox("Erin"))
    await scenario.advance(hours=12)
    await scenario.run_periodic("tasks.resurface")
    assert len(scenario.inbox("Erin")) == asked
    await scenario.advance(hours=12)
    await scenario.run_periodic("tasks.resurface")
    (again,) = scenario.inbox("Erin")[asked:]
    assert again.startswith("Maintenance: Change the furnace filter")


async def test_taken_off_the_list_its_offered_again_in_a_week(scenario: Scenario) -> None:
    await add(scenario, owner="Erin")
    await offer(scenario)
    task_id = scenario.app.db.scalar("SELECT id FROM tasks")
    assert scenario.app.services.taskboard is not None
    await scenario.app.services.taskboard.cancel(task_id, scenario.member("Erin"))
    item = maintenance(scenario).items()[0]
    assert item.task_id is None and item.skip_until == date(2026, 10, 28)
    clock.advance(timedelta(days=6))
    assert await offer(scenario) == []
    clock.advance(timedelta(days=1))
    assert len(await offer(scenario)) == 1


async def test_paused_maintenance_reminders_wait(scenario: Scenario) -> None:
    await add(scenario, owner="Erin")
    await scenario.say("Erin", "/pause maintenance")
    assert await offer(scenario) == []
    assert scenario.app.db.scalar("SELECT status FROM outbox WHERE kind = 'maintenance'") == (
        "queued"
    )


# ----- chat ----------------------------------------------------------------------------


async def test_added_and_logged_in_chat_with_notes_kept_for_next_time(
    scenario: Scenario,
) -> None:
    scenario.primary.queue_tool_call(
        "set_maintenance",
        {
            "name": "Change the furnace filter",
            "interval_days": 90,
            "active_months": ["All year"],
            "steps": FILTER_STEPS,
            "last_done": "",
            "owner": "me",
            "new_name": "",
        },
    )
    scenario.primary.queue_text("Added it.")
    await scenario.say("Erin", "Put changing the furnace filter on the maintenance list")
    result = str(scenario.primary.last_request.messages[-1])
    assert "Added Change the furnace filter: every 90 days, all year; next due today" in result
    assert "set_maintenance" in {t.name for t in scenario.primary.requests[0].tools}

    scenario.primary.queue_tool_call(
        "log_maintenance",
        {"name": "furnace filter", "notes": "Used the 16x25 from the shed", "day": ""},
    )
    scenario.primary.queue_text("Noted.")
    await scenario.say("Erin", "Changed the furnace filter, used the 16x25 from the shed")
    assert "Next due Tue 19 Jan" in str(scenario.primary.last_request.messages[-1])
    erin = scenario.member("Erin").id
    assert runs(scenario) == [
        ("Change the furnace filter", "2026-10-21", erin, "Used the 16x25 from the shed")
    ]
    assert await offer(scenario) == []  # done today, so not due

    scenario.primary.queue_tool_call("get_maintenance_guide", {"name": "furnace filter"})
    scenario.primary.queue_text("Here it is.")
    await scenario.say("Erin", "How do I change the furnace filter?")
    guide = str(scenario.primary.last_request.messages[-1])
    assert "1. Turn the furnace off" in guide
    assert "21 Oct 2026: Used the 16x25 from the shed" in guide

    # Next time it comes round, the nudge carries the note.
    clock.advance(timedelta(days=90))
    (text,) = await offer(scenario)
    assert "Last time (21 Oct 2026): Used the 16x25 from the shed" in text


async def test_logging_an_offered_item_settles_its_nudge(scenario: Scenario) -> None:
    await add(scenario, owner="Erin")
    await offer(scenario)
    scenario.primary.queue_tool_call(
        "log_maintenance", {"name": "Change the furnace filter", "notes": "", "day": ""}
    )
    scenario.primary.queue_text("Noted.")
    await scenario.say("Erin", "Did the furnace filter")
    assert scenario.app.db.scalar("SELECT status FROM tasks") == "done"
    assert len(runs(scenario)) == 1  # one run, not one from the tool and one from the task
    assert maintenance(scenario).items()[0].task_id is None


async def test_the_same_day_again_adds_to_the_notes(scenario: Scenario) -> None:
    item = await add(scenario)
    m = maintenance(scenario)
    await m.log(item, scenario.member("Erin"), m.today(), "16x25")
    said = await m.log(item, scenario.member("Erin"), m.today(), "from the shed")
    assert said == "Added that to the notes for Change the furnace filter."
    assert [r[3] for r in runs(scenario)] == ["16x25 from the shed"]


async def test_changing_an_item_keeps_what_isnt_said(scenario: Scenario) -> None:
    await add(scenario, months=(3, 4, 5))
    scenario.primary.queue_tool_call(
        "set_maintenance",
        {
            "name": "furnace filter",
            "interval_days": 60,
            "active_months": [],
            "steps": [],
            "last_done": "",
            "owner": "",
            "new_name": "",
        },
    )
    scenario.primary.queue_text("Changed.")
    await scenario.say("Erin", "The furnace filter wants doing every 60 days now")
    (item,) = maintenance(scenario).items()
    assert (item.interval_days, item.active_months, item.guide) == (
        60,
        (3, 4, 5),
        tuple(FILTER_STEPS),
    )


async def test_removed_in_chat(scenario: Scenario) -> None:
    await add(scenario)
    scenario.primary.queue_tool_call("remove_maintenance", {"name": "furnace filter"})
    scenario.primary.queue_text("Removed.")
    await scenario.say("Erin", "Take the furnace filter off the maintenance list")
    assert maintenance(scenario).items() == []
    assert scenario.primary.pending() == 0  # "Change the..." wasn't her words: the model says it


async def test_removed_in_her_words_ends_the_turn(scenario: Scenario) -> None:
    # F33a: the tool's line is the reply, with no second round
    await add(scenario)
    scenario.primary.queue_tool_call("remove_maintenance", {"name": "furnace filter"})
    replies = await scenario.say("Erin", "No more change the furnace filter, please remove it")
    assert maintenance(scenario).items() == []
    assert replies == ['Removed "Change the furnace filter" from the maintenance list.']


# ----- the family calendar -------------------------------------------------------------


@pytest.fixture
async def linked(
    scenario: Scenario, fake_google: FakeGoogle, fake_gcal: FakeGcal, site: httpx.AsyncClient
) -> FakeGcal:
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gcal


async def test_due_dates_go_on_the_family_calendar_and_follow_the_item(
    scenario: Scenario, linked: FakeGcal
) -> None:
    item = await add(scenario, last_done=date(2026, 9, 1))  # due 30 Nov
    (action,) = scenario.app.db.query(
        "SELECT * FROM pending_actions WHERE category = 'calendar_write'"
    )
    assert action["summary"] == (
        "For the family calendar: Change the furnace filter, due Mon Nov 30, moved along "
        "each time it's done"
    )
    assert linked.events(ERIN) == []
    await scenario.app.services.autonomy.resolve(
        action["id"], Decision.APPROVE, by=scenario.member("Erin")
    )
    await scenario.run_jobs()
    (event,) = linked.events(ERIN)
    assert (event["summary"], event["start"]["date"]) == ("Change the furnace filter", "2026-11-30")
    assert "- Turn the furnace off" in event["description"]

    m = maintenance(scenario)
    await m.log(item, scenario.member("Erin"), m.today())  # done early: 90 days from today
    await scenario.run_jobs()
    (event,) = linked.events(ERIN)
    assert event["start"]["date"] == "2027-01-19"
    assert (
        scenario.app.db.scalar(  # the yes covers keeping it true
            "SELECT COUNT(*) FROM pending_actions WHERE category = 'calendar_write'"
        )
        == 1
    )

    await m.remove(item, scenario.member("Erin"))
    await scenario.run_jobs()
    assert linked.events(ERIN) == []


# ----- the website ---------------------------------------------------------------------


async def test_managed_on_the_website(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Husband")
    page = await site.get("/maintenance")
    assert "Nothing on the maintenance list yet." in page.text
    assert 'href="/maintenance"' in (await site.get("/more")).text
    csrf = csrf_of(page.text)
    await site.post(
        "/maintenance",
        data={
            "csrf": csrf,
            "name": "Clean the gutters",
            "interval_days": "182",
            "m4": "on",
            "m10": "on",
            "steps": "Ladder from the garage\nScoop into the bin bags\n",
            "owner": str(scenario.member("Husband").id),
            "last_done": "2026-10-01",
        },
    )
    assert "Added Clean the gutters." in await flash(site, "/maintenance")
    (item,) = maintenance(scenario).items()
    assert (item.interval_days, item.active_months, item.guide, item.owner) == (
        182,
        (4, 10),
        ("Ladder from the garage", "Scoop into the bin bags"),
        scenario.member("Husband").id,
    )
    page = (await site.get("/maintenance")).text
    assert "Clean the gutters" in page and "April and October" in page
    assert "Due Thu 1 Apr" in page  # 1 Oct + 182 days is 1 April

    await site.post(f"/maintenance/{item.id}/done", data={"csrf": csrf, "notes": "Two bags full"})
    assert "Noted Clean the gutters as done with your notes." in await flash(site, "/maintenance")
    assert runs(scenario)[-1][3] == "Two bags full"
    assert "Two bags full" in (await site.get("/maintenance")).text

    await site.post(
        f"/maintenance/{item.id}",
        data={"csrf": csrf, "name": "Clear the gutters", "interval_days": "365", "steps": ""},
    )
    assert "Saved Clear the gutters." in await flash(site, "/maintenance")
    (item,) = maintenance(scenario).items()
    assert (item.name, item.interval_days, item.active_months, item.owner) == (
        "Clear the gutters",
        365,
        (),
        None,
    )

    await site.post(f"/maintenance/{item.id}/delete", data={"csrf": csrf})
    assert "Removed Clear the gutters." in await flash(site, "/maintenance")
    assert maintenance(scenario).items() == []


async def test_a_bad_interval_on_the_website_says_so(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    csrf = csrf_of((await site.get("/maintenance")).text)
    await site.post("/maintenance", data={"csrf": csrf, "name": "Gutters", "interval_days": "0"})
    assert "The interval is 1 to 3650 days." in await flash(site, "/maintenance")
    assert maintenance(scenario).items() == []


def _assignee(scenario: Scenario) -> int:
    return scenario.app.db.scalar("SELECT assignee FROM tasks ORDER BY id DESC LIMIT 1")
