"""WL4: ticking things off on the wall, through the trust tiers as the person it's for."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import (
    EVENING,
    column,
    frame,
    step,
    task,
    with_wall,
    words,
)
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi_home.wall import WallDevices


@pytest.fixture
async def wall(family: SeededFamily, fake_telegram: FakeTelegram) -> AsyncIterator[Scenario]:
    scenario = with_wall(family, fake_telegram)
    await scenario.start()
    try:
        yield scenario
    finally:
        await scenario.stop()


async def tap(s: Scenario, client: httpx.AsyncClient, key: str, **more: str) -> httpx.Response:
    page = await client.get("/wall")
    csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', page.text)
    assert csrf
    return await client.post(
        "/wall/tap",
        data={"key": key, **more},
        headers={"X-CSRF-Token": csrf[1], "HX-Request": "true"},
    )


def status(s: Scenario, task_id: int) -> str:
    return s.app.services.get(keys.taskboard).get(task_id).status


def audit(s: Scenario) -> list[tuple[str, str, int]]:
    return [
        (r["event"], r["detail"] or "", r["member_id"])
        for r in s.app.db.query(
            "SELECT * FROM action_audit WHERE category = 'wall_tap' ORDER BY id"
        )
    ]


async def test_a_tap_ticks_a_to_do_as_the_person_whose_column_its_in(wall: Scenario) -> None:
    errand = await task(wall, "Husband", "Vacuum upstairs")
    husband = wall.member("Husband")
    async with web_client(wall) as client:
        await frame(wall, client)
        response = await tap(wall, client, f"task-{errand.id}")
    assert response.status_code == 200 and "<html" not in response.text
    assert status(wall, errand.id) == "done"
    shown = column(response.text, f"m{husband.id}")
    assert re.search(rf'class="wall-item done"[^>]*data-key="task-{errand.id}"', shown)
    assert ("staged", "Tick off Vacuum upstairs on the wall", husband.id) in audit(wall)
    assert ("auto_approved", "Tier 2", husband.id) in audit(wall)


async def test_a_second_tap_unticks_a_one_off(wall: Scenario) -> None:
    errand = await task(wall, "Erin", "Process the mail")
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, f"task-{errand.id}")
        await tap(wall, client, f"task-{errand.id}")
    assert status(wall, errand.id) == "open"
    assert ("staged", "Untick Process the mail on the wall", wall.member("Erin").id) in audit(wall)


async def test_routine_steps_tick_and_untick(wall: Scenario) -> None:
    item_id = step(wall, "Husband", "Evening", "Take meds")
    clock.advance(EVENING)
    routines = wall.app.services.get(keys.routines)
    day = routines.today(wall.member("Husband"))
    key = f"step-{item_id}-{day.isoformat()}"
    found = routines.item(item_id)
    assert found is not None
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, key)
        assert routines.ticked(found, day)
        await tap(wall, client, key)
    assert not routines.ticked(found, day)


async def test_a_done_chore_stays_ticked_and_cant_be_unticked(wall: Scenario) -> None:
    chore = await task(wall, "Erin", "Refill pet feeders", due=wall.today(), chore=True)
    async with web_client(wall) as client:
        await frame(wall, client)
        first = await tap(wall, client, f"task-{chore.id}")
        erin = column(first.text, f"m{wall.member('Erin').id}")
        assert re.search(rf'<div class="wall-item done" data-key="task-{chore.id}"', erin)
        await tap(wall, client, f"task-{chore.id}")
    runs = wall.app.services.get(keys.taskboard).runs(chore.id)
    assert len(runs) == 1 and runs[0].done_by == wall.member("Erin").id


async def test_together_asks_who_and_records_them(wall: Scenario) -> None:
    yesterday = wall.today() - timedelta(days=1)
    bins = await task(wall, "Erin", "Bring bins in", due=yesterday, chore=True, both="either")
    husband = wall.member("Husband")
    async with web_client(wall) as client:
        await frame(wall, client)
        asked = await tap(wall, client, f"task-{bins.id}")
        together = column(asked.text, "together")
        assert "Who did it?" in together and "Not yet" in together
        assert status(wall, bins.id) == "open" and audit(wall) == []
        cancelled = await tap(wall, client, "", cancel="1")
        assert "Who did it?" not in cancelled.text
        done = await tap(wall, client, f"task-{bins.id}", by=str(husband.id))
    runs = wall.app.services.get(keys.taskboard).runs(bins.id)
    assert [r.done_by for r in runs] == [husband.id]
    assert "Bring bins in Husband did it" in words(column(done.text, "together"))
    assert ("staged", "Tick off Bring bins in on the wall", husband.id) in audit(wall)


async def test_the_tick_ends_the_note_about_it(wall: Scenario) -> None:
    yesterday = wall.today() - timedelta(days=1)
    bins = await task(wall, "Erin", "Bring bins in", due=yesterday, chore=True, both="either")
    async with web_client(wall) as client:
        await frame(wall, client)
        assert "still waiting" in (await client.get("/wall/part/note")).text
        await tap(wall, client, f"task-{bins.id}", by=str(wall.member("Erin").id))
        note = await client.get("/wall/part/note")
    assert "still waiting" not in note.text


async def test_only_what_the_wall_shows_can_be_tapped(wall: Scenario) -> None:
    hidden = await task(wall, "Erin", "Email audit", off_displays=True)
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, f"task-{hidden.id}")
        await tap(wall, client, "task-99999")
    assert status(wall, hidden.id) == "open" and audit(wall) == []


async def test_a_tap_needs_the_frames_token_and_a_paired_frame(wall: Scenario) -> None:
    errand = await task(wall, "Erin", "Process the mail")
    async with web_client(wall) as client:
        await frame(wall, client)
        forged = await client.post(
            "/wall/tap", data={"key": f"task-{errand.id}"}, headers={"X-CSRF-Token": "forged"}
        )
        assert forged.status_code == 403
        [device] = wall.app.services.get(WallDevices).all()
        wall.app.services.get(WallDevices).revoke(device.id)
        gone = await client.post("/wall/tap", data={"key": f"task-{errand.id}"})
    assert gone.status_code == 401 and gone.headers["HX-Redirect"] == "/wall/pair"
    assert status(wall, errand.id) == "open"


async def test_a_tick_on_the_wall_reaches_cozyla(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_cozyla: FakeCozyla
) -> None:
    s = with_wall(family, fake_telegram, cozyla=fake_cozyla)
    await s.start()
    try:
        errand = await task(s, "Erin", "Call the vet")
        await s.run_periodic("cozyla.sync")
        [todo] = [t for t in fake_cozyla.in_list(s.cozyla_list) if t["todoTitle"] == "Call the vet"]
        assert todo["completeStatus"] == 0
        async with web_client(s) as client:
            await frame(s, client)
            await tap(s, client, f"task-{errand.id}")
        await s.run_periodic("cozyla.sync")
        [todo] = [t for t in fake_cozyla.in_list(s.cozyla_list) if t["todoTitle"] == "Call the vet"]
    finally:
        await s.stop()
    assert todo["completeStatus"] == 1


async def test_a_member_on_their_phone_can_tap_too(wall: Scenario) -> None:
    from tests.fixtures.web import sign_in

    errand = await task(wall, "Erin", "Process the mail")
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Husband")
        await tap(wall, phone, f"task-{errand.id}")
    assert status(wall, errand.id) == "done"
    assert audit(wall)[0][2] == wall.member("Erin").id  # as the person whose column it's in


async def test_the_person_hears_a_warm_word_as_for_a_tick_on_cozyla(wall: Scenario) -> None:
    """Erin added the bins for her husband; he ticks them on the wall. The warm word is his,
    a moment later, as for a tick made on Cozyla's own screen."""
    board = wall.app.services.get(keys.taskboard)
    erin, husband = wall.member("Erin"), wall.member("Husband")
    bins = await board.create(erin, "Bring bins in", "errand", 1, wall.today(), assignee=husband)
    await wall.app.outbox.flush()
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, f"task-{bins.id}")
    await wall.advance(minutes=10)
    assert wall.inbox("Husband")[-1] == "Ticked off on the wall: Bring bins in. Good job."
    assert wall.inbox("Erin") == []
