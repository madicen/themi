"""WL9d: the Person and Together views are whole pages over the wall. The scenario's day is
Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re
from datetime import timedelta

from tests.fakes.gcal_api import FakeGcal
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import (
    calendar,
    column,
    frame,
    screen,
    share,
    step,
    task,
    wall,
    words,
)
from tests.integration.test_wall_taps import tap
from tests.integration.test_wall_views import get
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import local
from tests.scenarios.test_triage import ERIN
from themi import clock
from themi.core import keys

__all__ = ["calendar", "wall"]  # fixtures


def page_of(html: str) -> str:
    found = re.search(r'<section class="wall-sheet wall-page[^"]*"[^>]*>.*</section>', html, re.S)
    assert found, html
    return found[0]


def part(html: str, cls: str) -> str:
    found = re.search(rf'<section class="{cls}"[^>]*>(.*?)</section>', html, re.S)
    assert found, f"no {cls}"
    return words(found[1])


# ----- Person ----------------------------------------------------------------------------


async def test_the_person_page_is_a_whole_page_with_a_way_back(wall: Scenario) -> None:
    await task(wall, "Erin", "Process the mail")
    await task(wall, "Erin", "Clean the bird cage", due=wall.today(), chore=True)
    erin = wall.member("Erin")
    shown = page_of((await get(wall, f"/wall/view/person/{erin.id}")).text)
    assert re.search(r'<button type="button" class="page-back" data-close>', shown)
    assert 'data-close-after="120"' in shown
    assert "Wednesday, October 21 Erin's day" in words(shown).replace("&#39;", "'")
    assert part(shown, "page-banner") == "This morning 1 chore and 1 to-do on your list"
    assert "The whole family, at a glance" in words(shown)
    assert "sheet-back" not in shown  # a page, not a card


async def test_the_banner_counts_whats_done(wall: Scenario) -> None:
    errand = await task(wall, "Erin", "Process the mail")
    await task(wall, "Erin", "Call the vet")
    erin = wall.member("Erin")
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, f"task-{errand.id}")
    shown = page_of((await get(wall, f"/wall/view/person/{erin.id}")).text)
    assert part(shown, "page-banner") == "1 done today 1 to-do on your list"


async def test_the_schedule_in_order_with_its_times(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(18, 30), local(20, 30), summary="Book club")
    fake_gcal.add_event(ERIN, local(10), local(11), summary="Dentist")
    await calendar.run_periodic("calendar.busy")
    erin = calendar.member("Erin")
    shown = page_of((await get(calendar, f"/wall/view/person/{erin.id}")).text)
    schedule = part(shown, "page-schedule")
    assert schedule.startswith("Schedule 2 things today")
    assert schedule.index("10\u201311 am Dentist") < schedule.index("6:30\u20138:30 pm Book club")
    assert "Room to breathe" not in schedule  # Book club is still to come


async def test_an_unshared_calendar_is_busy_on_the_page_too(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    fake_gcal.add_event(ERIN, local(10), local(11), summary="Dentist", location="Smile Dental")
    await calendar.run_periodic("calendar.busy")
    erin = calendar.member("Erin")
    shown = page_of((await get(calendar, f"/wall/view/person/{erin.id}")).text)
    assert "10\u201311 am Busy" in part(shown, "page-schedule")
    assert "Dentist" not in shown and "Smile Dental" not in shown


async def test_room_to_breathe_once_nothing_else_is_on(
    calendar: Scenario, fake_gcal: FakeGcal
) -> None:
    share(calendar)
    fake_gcal.add_event(ERIN, local(10), local(11), summary="Dentist")
    await calendar.run_periodic("calendar.busy")
    erin = calendar.member("Erin")
    before = page_of((await get(calendar, f"/wall/view/person/{erin.id}")).text)
    assert "Room to breathe" not in before
    clock.advance(timedelta(hours=2, minutes=5))  # 11:05 am
    after = part(
        page_of((await get(calendar, f"/wall/view/person/{erin.id}")).text), "page-schedule"
    )
    assert "Room to breathe Nothing else this morning" in after
    assert re.search(r"10\u201311 am Dentist", after)


async def test_a_quiet_day_says_so(wall: Scenario) -> None:
    erin = wall.member("Erin")
    shown = page_of((await get(wall, f"/wall/view/person/{erin.id}")).text)
    schedule = part(shown, "page-schedule")
    assert "Nothing on the calendar today" in schedule and "Room to breathe" in schedule


async def test_this_part_of_the_day_first_and_the_others_folded(wall: Scenario) -> None:
    step(wall, "Husband", "Morning", "Walk dog")
    step(wall, "Husband", "Morning", "Make the bed")
    evening = step(wall, "Husband", "Evening", "Take meds")
    husband = wall.member("Husband")
    shown = words(page_of((await get(wall, f"/wall/view/person/{husband.id}")).text))
    assert "Morning routine 2 to do 🐕 Walk dog" in shown
    assert "Evening routine · 1 step" in shown and "Take meds" not in shown
    routines = wall.app.services.get(keys.routines)
    found = routines.item(evening)
    assert found is not None
    opened = (await get(wall, f"/wall/view/person/{husband.id}?open={found.routine_id}")).text
    assert "💊 Take meds" in words(page_of(opened))
    assert f'hx-get="/wall/view/person/{husband.id}"' in opened  # a tap folds it again


async def test_a_tick_on_the_page_keeps_an_unfolded_part_open(wall: Scenario) -> None:
    item_id = step(wall, "Husband", "Evening", "Take meds")
    husband = wall.member("Husband")
    routines = wall.app.services.get(keys.routines)
    found = routines.item(item_id)
    assert found is not None
    day = routines.today(husband)
    async with web_client(wall) as client:
        await frame(wall, client)
        answer = await tap(
            wall,
            client,
            f"step-{item_id}-{day.isoformat()}",
            view=f"person/{husband.id}",
            open=str(found.routine_id),
        )
    assert routines.ticked(found, day)
    assert answer.headers["HX-Trigger"] == "wall-refresh"
    assert re.search(r'class="wall-item done" data-key="step-', answer.text)


async def test_the_whole_to_do_list_at_your_own_pace(wall: Scenario) -> None:
    for title in ("Vet", "Mail", "Gate", "Shelf", "Tyres"):
        await task(wall, "Erin", title)
    erin = wall.member("Erin")
    shown = page_of((await get(wall, f"/wall/view/person/{erin.id}")).text)
    todo = part(shown, "page-box page-todo")
    assert todo.startswith("To-do 5 open Work through these at your own pace.")
    assert all(t in todo for t in ("Vet", "Mail", "Gate", "Shelf", "Tyres"))


# ----- Together --------------------------------------------------------------------------


async def test_together_is_its_own_page(wall: Scenario) -> None:
    await task(wall, "Erin", "Move Mimi's box upstairs", both="shared")
    await task(wall, "Erin", "Fix the gate", both="shared")
    bins = await task(wall, "Erin", "Bring bins in", due=wall.today(), chore=True, both="either")
    async with web_client(wall) as client:
        await frame(wall, client)
        await tap(wall, client, f"task-{bins.id}", by=str(wall.member("Husband").id))
    page = await screen(wall)
    together = column(page, "together")
    assert together.count('hx-get="/wall/view/together"') == 2  # its header and its foot
    shown = page_of((await get(wall, "/wall/view/together")).text)
    assert part(shown, "page-banner") == "This morning 2 open · 1 done"
    open_part = part(shown, "page-box page-open")
    assert "Family to-do" in open_part and "Fix the gate" in open_part
    assert (
        part(shown, "page-box page-done")
        == "Done today 1 done 🗑️ Bring bins in Husband did it"  # a chore's round: no undo
    )


async def test_ticking_on_the_together_page_asks_who_and_a_done_one_unticks(
    wall: Scenario,
) -> None:
    gate = await task(wall, "Erin", "Fix the gate", both="shared")
    husband = wall.member("Husband")
    board = wall.app.services.get(keys.taskboard)
    async with web_client(wall) as client:
        await frame(wall, client)
        asked = await tap(wall, client, f"task-{gate.id}", view="together")
        assert "Who did it?" in words(asked.text) and board.get(gate.id).status == "open"
        done = await tap(wall, client, f"task-{gate.id}", view="together", by=str(husband.id))
        assert board.get(gate.id).status == "done"
        assert done.headers["HX-Trigger"] == "wall-refresh"
        # a one-off keeps no "who" (only a chore's round does), so it's listed without it
        assert part(page_of(done.text), "page-box page-done").startswith(
            "Done today 1 done · tap to undo"
        )
        assert "Fix the gate" in part(page_of(done.text), "page-box page-done")
        undone = await tap(wall, client, f"task-{gate.id}", view="together")
    assert board.get(gate.id).status == "open"
    assert "Fix the gate" in part(page_of(undone.text), "page-box page-open")
