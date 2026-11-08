"""W2: the website's Tasks as rows with Done, and Home's short list and appliances."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi.localtime import to_utc_iso
from themi.standard.repeat import parse
from themi.standard.tasks import DONE_TEXT, SETTLED_TEXT, TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.maybe(keys.taskboard) is not None
    return scenario.app.services.get(keys.taskboard)


async def done(site: httpx.AsyncClient, task_id: int, **headers: str) -> httpx.Response:
    csrf = csrf_of((await site.get("/tasks")).text)
    return await site.post(f"/tasks/{task_id}/done", data={"csrf": csrf}, headers=headers)


async def test_done_on_the_website_marks_it_done_once(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Post the parcel", "errand", 1, assignee=erin)
    await sign_in(scenario, site, "Erin")
    response = await done(site, task.id)
    assert response.status_code == 303 and response.headers["location"] == "/tasks"
    page = await flash(site, "/tasks")
    assert "Marked done: Post the parcel." in page
    assert board(scenario).get(task.id).status == "done"
    assert 'id="task-' not in page  # off the list
    again = await done(site, task.id)
    assert SETTLED_TEXT.replace("'", "&#39;") in await flash(site, again.headers["location"])


async def test_htmx_gets_just_the_row_back(scenario: Scenario, site: httpx.AsyncClient) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Post the parcel", "errand", 1, assignee=erin)
    await sign_in(scenario, site, "Erin")
    response = await done(site, task.id, **{"HX-Request": "true"})
    assert response.status_code == 200
    assert response.text.startswith('<div class="row-item row-done"')
    assert "Marked done: Post the parcel." in response.text and "<html" not in response.text


async def test_a_repeating_chore_moves_on_one_round(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    erin = scenario.member("Erin")
    bins = await board(scenario).create(erin, "Bring bins in", "physical", 1, assignee=erin)
    await board(scenario).set_schedule(
        bins.id, erin, repeat=parse("every Wednesday", scenario.today())
    )
    before = board(scenario).get(bins.id).due_on
    await sign_in(scenario, site, "Erin")
    await done(site, bins.id)
    after = board(scenario).get(bins.id)
    assert after.status == "open" and after.due_on is not None and before is not None
    assert after.due_on == before + timedelta(days=7)
    assert len([r for r in board(scenario).runs(bins.id) if not r.missed]) == 1


async def test_someone_elses_task_cant_be_marked_done_here(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    erin = scenario.member("Erin")
    task = await board(scenario).create(erin, "Erin's own errand", "errand", 1, assignee=erin)
    await sign_in(scenario, site, "Husband")  # not an admin, not doing it, didn't add it
    response = await done(site, task.id)
    assert "That task isn&#39;t one you can mark done here." in await flash(
        site, response.headers["location"]
    )
    assert board(scenario).get(task.id).status == "open"


async def test_overdue_tasks_come_first(scenario: Scenario, site: httpx.AsyncClient) -> None:
    erin, today = scenario.member("Erin"), scenario.today()
    later = await board(scenario).create(
        erin, "Later one", "errand", 1, today + timedelta(3), assignee=erin
    )
    undated = await board(scenario).create(erin, "Whenever one", "errand", 1, assignee=erin)
    late = await board(scenario).create(
        erin, "Late one", "errand", 1, today - timedelta(2), assignee=erin
    )
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/tasks")).text
    order = [page.index(f'id="task-{t.id}"') for t in (late, later, undated)]
    assert order == sorted(order)
    late_row = page[order[0] : order[1]]
    assert '<span class="chip warn">Overdue</span>' in late_row and "Was due" in late_row
    assert "Overdue" not in page[order[1] :]


async def test_home_shows_the_first_five_and_the_appliances(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    erin, today = scenario.member("Erin"), scenario.today()
    for n in range(6):
        await board(scenario).create(
            erin, f"Job {n}", "errand", 1, today + timedelta(n + 1), assignee=erin
        )
    await sign_in(scenario, site, "Erin")
    home = (await site.get("/")).text
    assert all(f"Job {n}" in home for n in range(5)) and "Job 5" not in home
    assert 'href="/tasks">All 6 tasks' in home
    assert 'name="back" value="home"' in home
    assert "Around the house" not in home  # nothing linked

    store = scenario.app.store
    washer = store.add_device(erin, "lg_thinq", "w-1", "Washer", "washer")
    dryer = store.add_device(erin, "lg_thinq", "d-1", "Dryer", "dryer")
    vacuum = store.add_device(erin, "roborock", "v-1", "Robbie", "vacuum")
    now = to_utc_iso(clock.now())
    for device, state in ((washer, "finished"), (dryer, "idle"), (vacuum, "stuck")):
        scenario.app.db.execute(
            "INSERT INTO device_states (device_id, state, seen_at) VALUES (?, ?, ?)",
            (device.id, state, now),
        )
    scenario.app.db.execute(
        "INSERT INTO appliance_cycles (device_id, started_at, ended_at) VALUES (?, ?, ?)",
        (washer.id, now, now),
    )
    home = (await site.get("/")).text
    assert "Around the house" in home
    assert "Washer: finished at" in home and "Robbie: stuck" in home
    assert "Dryer" not in home  # not running: nothing to know


async def test_erin_marks_a_shared_overdue_chore_done_on_the_website(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """Done on the website goes the way Done in chat does: the husband's nudge about the
    shared chore is settled too, so it stops asking him."""
    erin = scenario.member("Erin")
    task = await board(scenario).create(
        erin, "Descale the kettle", "physical", 1, scenario.today(), assignee=erin
    )
    await board(scenario).reassign(task.id, None, shared=True)
    await scenario.advance(hours=1)
    assert any("Descale the kettle" in text for text in scenario.inbox("Husband"))

    await sign_in(scenario, site, "Erin")
    tasks = (await site.get("/tasks")).text
    assert "On both your lists" in tasks
    await done(site, task.id)

    assert board(scenario).get(task.id).status == "done"
    settled = DONE_TEXT.format(title="Descale the kettle")
    assert any(e["text"] == settled for e in scenario.edits("Husband"))
