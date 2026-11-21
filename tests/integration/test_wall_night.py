"""WL6: the wall by time of day, the night view, and the frame's app. The scenario's day is
Wednesday 21 October 2026, from 9 am, Los Angeles. Erin's quiet hours start at 21:30, so her
evening routine ends at 20:30."""

from __future__ import annotations

from datetime import timedelta

import httpx

from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import column, frame, screen, step, wall, words
from tests.scenarios.harness import Scenario
from themi import clock
from themi_home.wall_view import WallSettings, WallView

__all__ = ["wall"]  # the fixture


def at(s: Scenario, hour: int, minute: int = 0) -> None:
    """Move the clock to that time today (the scenario starts at 9 am)."""
    now = WallView(s.app.services).now()
    target = now.replace(hour=hour, minute=minute)
    clock.advance(target - now)


async def get(s: Scenario, path: str) -> httpx.Response:
    async with web_client(s) as client:
        await frame(s, client)
        return await client.get(path)


def routines(s: Scenario) -> None:
    step(s, "Erin", "Morning", "Walk dog")
    step(s, "Erin", "Afternoon", "Go for a run")
    step(s, "Husband", "Evening", "Take meds")


async def test_each_part_of_the_day_shows_its_own_routine(wall: Scenario) -> None:
    routines(wall)
    erin = f"m{wall.member('Erin').id}"
    morning = words(column(await screen(wall), erin))
    assert "Morning routine 🐕 Walk dog" in morning and "Go for a run" not in morning
    at(wall, 14)
    afternoon = words(column(await screen(wall), erin))
    assert "Afternoon routine 🏃 Go for a run" in afternoon and "Walk dog" not in afternoon
    at(wall, 19, 42)
    evening = await screen(wall)
    assert "Nothing set for this evening" in words(column(evening, erin))
    assert "Evening routine 💊 Take meds" in words(column(evening, f"m{wall.member('Husband').id}"))
    assert 'class="wall night"' not in evening


async def test_after_bedtime_the_night_view_shows_tomorrow(wall: Scenario) -> None:
    """The plan's mock-up at 11:33 pm: tomorrow, not Erin's morning walk as if it were now."""
    routines(wall)
    at(wall, 23, 33)
    page = await screen(wall)
    assert 'class="wall night"' in page and 'data-night="1"' in page
    night = words(page[page.index('<section class="wall-night"') : page.index("</section>")])
    assert night.startswith("11:33 PM Wednesday, October 21 Tomorrow, Thursday")
    assert "Walk dog · Erin, morning" in night
    assert "Nothing needs doing now." in night
    assert "Walk dog" not in words(column(page, f"m{wall.member('Erin').id}"))


async def test_after_midnight_its_this_morning_and_it_wakes_with_the_first_routine(
    wall: Scenario,
) -> None:
    routines(wall)
    clock.advance(timedelta(hours=16))  # 1 am Thursday
    page = await screen(wall)
    assert "This morning" in page and 'data-night="1"' in page
    clock.advance(timedelta(hours=7))  # 8 am
    page = await screen(wall)
    assert 'data-night="0"' in page and 'class="wall night"' not in page


async def test_the_bedtime_setting_moves_the_night(wall: Scenario) -> None:
    at(wall, 22, 30)
    assert 'data-night="0"' in await screen(wall)
    erin = wall.member("Erin")
    wall.app.store.save_household(erin, WallSettings, bedtime="22:00")
    assert 'data-night="1"' in await screen(wall)


async def test_the_night_part_refreshes_and_a_touch_wakes_it(wall: Scenario) -> None:
    at(wall, 23, 33)
    page = await screen(wall)
    assert 'hx-get="/wall/part/night" hx-trigger="every 60s"' in page
    part = await get(wall, "/wall/part/night")
    assert 'data-night="1"' in part.text and "<html" not in part.text
    assert "Touch the screen to see everything." in page


async def test_the_frame_installs_the_wall_as_its_own_app(wall: Scenario) -> None:
    page = await screen(wall)
    assert '<link rel="manifest" href="/wall/manifest.webmanifest">' in page
    manifest = (await get(wall, "/wall/manifest.webmanifest")).json()
    assert manifest["start_url"] == "/wall" and manifest["display"] == "fullscreen"
    assert manifest["orientation"] == "portrait" and manifest["scope"] == "/wall"
    assert [i["sizes"] for i in manifest["icons"]] == ["192x192", "512x512"]
    worker = await get(wall, "/wall/sw.js")
    assert worker.headers["content-type"].startswith("text/javascript")
    assert worker.headers["Service-Worker-Allowed"] == "/wall"
    assert 'cache.match("/wall")' in worker.text


async def test_the_guide_says_how_to_set_the_frame_up(wall: Scenario) -> None:
    from tests.fixtures.web import sign_in

    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Erin")
        page = await phone.get("/modules/wall")
    assert "Add to Home screen" in page.text and "Bedtime" in page.text
