"""The wall's home screen (WL2): what the frame shows, read-only.

The scenario's day is Wednesday 21 October 2026 in Los Angeles. Most tests move to 7:42 pm,
the evening on the plan's mock-up. Erin is the first member (her column first), her husband
the second; Together sits between them.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.weather import FakeWeather
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.app import family_modules
from themi.core import keys
from themi.standard.tasks import Task
from themi_home.wall import WALL_COOKIE, WallDevices, WallModule
from themi_home.wall_view import WallView, since

EVENING = timedelta(hours=10, minutes=42)  # 9:00 am to 7:42 pm


def with_wall(family: SeededFamily, telegram: FakeTelegram, **fakes: Any) -> Scenario:
    """The family's app with the wall module on, and any fakes (`weather=`)."""
    options = connector_options(**fakes, timezone=family.family.timezone)
    return Scenario(family, telegram, **fakes, modules=[*family_modules(**options), WallModule()])


@pytest.fixture
async def wall(family: SeededFamily, fake_telegram: FakeTelegram) -> AsyncIterator[Scenario]:
    scenario = with_wall(family, fake_telegram)
    await scenario.start()
    try:
        yield scenario
    finally:
        await scenario.stop()


def today(s: Scenario) -> date:
    return s.today()


async def task(
    s: Scenario,
    name: str,
    title: str,
    *,
    due: date | None = None,
    chore: bool = False,
    both: str = "",  # "either" (a chore either can do) or "shared" (a family to-do)
    importance: str = "normal",
    off_displays: bool = False,
) -> Task:
    board = s.app.services.get(keys.taskboard)
    member = s.member(name)
    made = await board.create(
        member, title, "errand", 1, due, nudge=False, assignee=member,
        importance=importance, off_displays=off_displays,
    )  # fmt: skip
    if chore:
        s.app.db.execute("UPDATE tasks SET times_per_week = 2 WHERE id = ?", (made.id,))
    if both == "either":
        s.app.db.execute("UPDATE tasks SET either = 1, shared = 1 WHERE id = ?", (made.id,))
    elif both == "shared":
        s.app.db.execute("UPDATE tasks SET shared = 1 WHERE id = ?", (made.id,))
    return board.get(made.id)


def step(s: Scenario, name: str, routine: str, title: str) -> int:
    routines = s.app.services.get(keys.routines)
    found = routines.find(s.member(name), routine)
    assert found is not None
    return routines.add_item(found, title, (), None).id


async def frame(s: Scenario, client: httpx.AsyncClient) -> None:
    code = s.app.services.get(WallDevices).new_code(s.member("Erin"))
    response = await client.post("/wall/pair", data={"code": code})
    client.cookies.set(WALL_COOKIE, response.cookies[WALL_COOKIE])


async def screen(s: Scenario) -> str:
    async with web_client(s) as client:
        await frame(s, client)
        page = await client.get("/wall")
    assert page.status_code == 200
    return page.text


def column(page: str, key: str) -> str:
    match = re.search(
        rf'<section class="wall-col[^"]*"[^>]*id="col-{key}">(.*?)</section>', page, re.S
    )
    assert match, f"no column {key}"
    return match.group(1)


def words(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def headings(html: str) -> list[str]:
    return re.findall(r"<h3>(.*?)</h3>", html)


# ----- the columns ---------------------------------------------------------------------


async def test_three_columns_with_together_between_the_two_of_you(wall: Scenario) -> None:
    page = await screen(wall)
    order = re.findall(r'id="col-([a-z0-9]+)"', page)
    erin, husband = wall.member("Erin").id, wall.member("Husband").id
    assert order == [f"m{erin}", "together", f"m{husband}"]


async def test_a_persons_column_has_this_part_of_the_days_routine(wall: Scenario) -> None:
    step(wall, "Husband", "Evening", "Cover the birdcage")
    step(wall, "Husband", "Morning", "Walk the dog")
    clock.advance(EVENING)
    page = await screen(wall)
    husband = column(page, f"m{wall.member('Husband').id}")
    erin = column(page, f"m{wall.member('Erin').id}")
    assert "Evening routine" in headings(husband) and "Cover the birdcage" in husband
    assert "Walk the dog" not in husband
    assert "Nothing set for this evening" in words(erin)


async def test_a_ticked_step_shows_done_and_counts(wall: Scenario) -> None:
    item = step(wall, "Husband", "Evening", "Take meds")
    clock.advance(EVENING)
    routines = wall.app.services.get(keys.routines)
    found = routines.item(item)
    assert found is not None
    routines.tick(found, routines.today(wall.member("Husband")))
    husband = column(await screen(wall), f"m{wall.member('Husband').id}")
    done = re.findall(r'class="wall-item done"[^>]*>.*?wall-title">([^<]+)<', husband, re.S)
    assert done == ["Take meds"]
    assert "1 done tonight" in words(husband)


async def test_chores_due_by_today_and_to_dos_in_the_walls_order(wall: Scenario) -> None:
    day = today(wall)
    await task(wall, "Erin", "Refill pet feeders", due=day, chore=True)
    await task(wall, "Erin", "Declutter the kitchen", due=day - timedelta(days=1), chore=True)
    await task(wall, "Erin", "Clean the oven", due=day + timedelta(days=3), chore=True)
    await task(wall, "Erin", "Someday shelf", due=None)
    await task(wall, "Erin", "Vacuum upstairs", due=day + timedelta(days=2))
    await task(wall, "Erin", "Call the vet", due=day, importance="high")
    await task(wall, "Erin", "Split the cat box", due=day - timedelta(days=12))
    erin = words(column(await screen(wall), f"m{wall.member('Erin').id}"))
    assert "Refill pet feeders" in erin and "Declutter the kitchen from yesterday" in erin
    assert "Clean the oven" not in erin  # not due yet
    todo = erin[erin.index("To-do") :]
    # due or overdue first (important before the rest), then the soonest; three shown
    assert todo.index("Call the vet") < todo.index("Split the cat box") < todo.index("Vacuum")
    assert "since Oct 9" in todo and "Someday shelf" not in todo and "More on the list" in todo


async def test_together_has_either_chores_and_the_family_to_dos(wall: Scenario) -> None:
    day = today(wall)
    await task(
        wall, "Erin", "Bring bins in", due=day - timedelta(days=1), chore=True, both="either"
    )
    await task(wall, "Husband", "Unjam the vacuum", both="shared")
    await task(wall, "Erin", "Erin's own errand")
    page = await screen(wall)
    together = words(column(page, "together"))
    assert "Either of you Bring bins in from yesterday" in together
    assert "Family to-do Unjam the vacuum" in together
    assert "Erin's own errand" not in together
    for key in (f"m{wall.member('Erin').id}", f"m{wall.member('Husband').id}"):
        assert "Bring bins in" not in column(page, key)  # once, in Together


async def test_snoozed_and_display_shy_tasks_stay_off(wall: Scenario) -> None:
    await task(wall, "Erin", "Email audit", off_displays=True)
    snoozed = await task(wall, "Erin", "Later thing")
    wall.app.db.execute("UPDATE tasks SET status = 'snoozed' WHERE id = ?", (snoozed.id,))
    page = await screen(wall)
    assert "Email audit" not in page and "Later thing" not in page


async def test_never_late_never_red_never_energy(wall: Scenario) -> None:
    await task(wall, "Erin", "Old chore", due=today(wall) - timedelta(days=3), chore=True)
    page = (await screen(wall)).lower()
    assert "late" not in words(page) and "overdue" not in page
    assert "energy" not in page and "points" not in page


# ----- the note -------------------------------------------------------------------------


async def test_the_note_offers_yesterdays_open_chore(wall: Scenario) -> None:
    day = today(wall)
    await task(
        wall, "Erin", "Bring bins in", due=day - timedelta(days=1), chore=True, both="either"
    )
    page = await screen(wall)
    assert (
        "Bring bins in is still waiting from yesterday. Whoever has a moment could do it." in page
    )


async def test_no_note_when_theres_nothing_worth_saying(wall: Scenario) -> None:
    await task(wall, "Erin", "Today's chore", due=today(wall), chore=True)
    assert "wall-card wall-note" not in await screen(wall)


async def test_a_weather_alert_is_the_note_and_the_weather_is_shown(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_weather: FakeWeather
) -> None:
    s = with_wall(family, fake_telegram, weather=fake_weather)
    await s.start()
    try:
        s.app.db.execute(
            "INSERT INTO family_home (id, address, lat, lon, set_at) VALUES (1, ?, ?, ?, ?)",
            ("12 Main St", 37.70, -122.40, "2026-10-01T00:00:00+00:00"),
        )
        fake_weather.day(0, high=54, low=49)
        fake_weather.alert("Wind Advisory", 6, 22)
        await s.app.services.get(keys.weather).refresh()
        await task(s, "Erin", "Bring bins in", due=today(s) - timedelta(days=1), chore=True)
        page = await screen(s)
    finally:
        await s.stop()
    assert "Wind Advisory until 10 pm. Worth a look before heading out." in page
    assert "Bring bins in is still waiting" not in page
    top = page[page.index('id="wall-top"') : page.index('id="wall-note"')]
    assert '<p class="wall-high">54°</p>' in top and "low 49° tonight" in top
    assert 'src="data:image/svg+xml;base64,' in top


# ----- the small lists and the private ones -----------------------------------------------


async def test_groceries_and_household_lists_but_never_a_personal_one(wall: Scenario) -> None:
    lists = wall.app.services.get(keys.lists)
    erin = wall.member("Erin")
    cook = lists.create(erin, "Things to cook", personal=False)
    lists.add(cook, ["Bean soup", "Creami prep"], erin)
    private = lists.create(erin, "Gift ideas", personal=True)
    lists.add(private, ["A secret"], erin)
    wall.app.services.get(keys.groceries).add(["Dried mango"], by=erin)
    page = await screen(wall)
    smalls = words(page[page.index('id="wall-smalls"') :])
    assert "Groceries Dried mango" in smalls and "Things to cook Bean soup · Creami prep" in smalls
    assert "Gift ideas" not in page and "A secret" not in page


async def test_no_email_on_the_wall(wall: Scenario) -> None:
    page = (await screen(wall)).lower()
    assert "email" not in words(page) and "inbox" not in page


# ----- staying current ---------------------------------------------------------------


async def test_each_part_refreshes_on_its_own(wall: Scenario) -> None:
    page = await screen(wall)
    assert 'hx-get="/wall/part/columns" hx-trigger="every 30s"' in page
    assert 'hx-get="/wall/part/smalls" hx-trigger="every 600s"' in page
    await task(wall, "Erin", "New errand")
    async with web_client(wall) as client:
        await frame(wall, client)
        part = await client.get("/wall/part/columns", headers={"HX-Request": "true"})
        assert part.status_code == 200 and "New errand" in part.text
        assert "<html" not in part.text
        assert (await client.get("/wall/part/nothing")).status_code == 404


async def test_the_screen_says_when_it_was_last_brought_up_to_date(wall: Scenario) -> None:
    clock.advance(EVENING)
    page = await screen(wall)
    assert 'data-at="7:42 PM"' in page and 'id="wall-stale"' in page
    assert "home/wall.js" in page


async def test_a_signed_out_frames_poll_goes_back_to_pairing(wall: Scenario) -> None:
    async with web_client(wall) as client:
        await frame(wall, client)
        [device] = wall.app.services.get(WallDevices).all()
        wall.app.services.get(WallDevices).revoke(device.id)
        part = await client.get("/wall/part/columns", headers={"HX-Request": "true"})
    assert part.status_code == 401 and part.headers["HX-Redirect"] == "/wall/pair"


async def test_a_member_sees_the_same_household_screen(wall: Scenario) -> None:
    await task(wall, "Erin", "Erin's errand")
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Husband")
        page = (await phone.get("/wall")).text
    assert "Erin&#39;s errand" in page or "Erin's errand" in page


# ----- the view's own pieces ------------------------------------------------------------


def test_since_is_gentle() -> None:
    day = date(2026, 11, 19)
    assert since(day, day) == "" and since(None, day) == ""
    assert since(day - timedelta(days=1), day) == "from yesterday"
    assert since(day - timedelta(days=3), day) == "from Monday"
    assert since(day - timedelta(days=12), day) == "since Nov 7"


async def test_the_header_reads_like_the_mock_up(wall: Scenario) -> None:
    clock.advance(EVENING)
    shown = WallView(wall.app.services).screen()
    assert (shown.weekday, shown.time, shown.meridiem) == ("Wednesday, October 21", "7:42", "PM")
