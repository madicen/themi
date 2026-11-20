"""F52b: the wall's look, from the Wall module's setting. The scenario's day is Wednesday
21 October 2026, from 9 am, Los Angeles; routines' evening starts at 5 pm and the first
morning one at 8 am."""

from __future__ import annotations

import re
from datetime import timedelta

from tests.fixtures.web import sign_in, web_client
from tests.integration.test_wall_night import at, get
from tests.integration.test_wall_screen import screen, wall
from tests.scenarios.harness import Scenario
from themi import clock
from themi_home.wall_view import WallSettings, WallView

__all__ = ["wall"]  # the fixture


def choose(s: Scenario, look: str) -> None:
    s.app.store.save_household(s.member("Erin"), WallSettings, look=look)


def root(page: str) -> str:
    match = re.search(r"<html [^>]*>", page)
    assert match
    return match[0]


def theme_colors(page: str) -> list[str]:
    return re.findall(r'<meta name="theme-color"[^>]*>', page)


async def test_it_follows_the_frame_by_default(wall: Scenario) -> None:
    assert wall.app.store.household(WallSettings).look == "Follow the frame"
    page = await screen(wall)
    assert root(page) == '<html lang="en" class="wall-root" data-look="auto">'
    assert theme_colors(page) == [
        '<meta name="theme-color" content="#e8ece6" media="(prefers-color-scheme: light)">',
        '<meta name="theme-color" content="#111317" media="(prefers-color-scheme: dark)">',
    ]


async def test_light_and_dark(wall: Scenario) -> None:
    choose(wall, "Dark")
    page = await screen(wall)
    assert root(page) == '<html lang="en" class="wall-root dark" data-look="dark">'
    assert theme_colors(page) == ['<meta name="theme-color" content="#111317">']
    choose(wall, "Light")
    page = await screen(wall)
    assert root(page) == '<html lang="en" class="wall-root" data-look="light">'
    assert theme_colors(page) == ['<meta name="theme-color" content="#e8ece6">']


async def test_dark_in_the_evening_turns_with_the_routines(wall: Scenario) -> None:
    choose(wall, "Dark in the evening")
    at(wall, 16, 59)
    assert 'data-look="light"' in root(await screen(wall))
    at(wall, 17)
    assert 'data-look="dark"' in root(await screen(wall))
    at(wall, 23, 30)
    assert 'data-look="dark"' in root(await screen(wall))
    clock.advance(timedelta(hours=8))  # 7:30 am Thursday
    assert 'data-look="dark"' in root(await screen(wall))
    clock.advance(timedelta(minutes=30))  # 8 am, the first morning routine
    assert 'data-look="light"' in root(await screen(wall))


async def test_the_night_part_carries_the_look_for_the_turn(wall: Scenario) -> None:
    choose(wall, "Dark in the evening")
    at(wall, 17, 30)
    part = (await get(wall, "/wall/part/night")).text
    assert 'data-night="0" data-look="dark"' in part
    assert WallView(wall.app.services).look() == "dark"


async def test_a_touch_at_night_shows_the_dark_look(wall: Scenario) -> None:
    """Whatever the setting: the dark tokens are on body.night, awake or not."""
    from tests.unit.test_wall_look import CSS

    choose(wall, "Light")
    at(wall, 23, 33)
    page = await screen(wall)
    assert 'class="wall night"' in page and 'data-look="light"' in root(page)
    assert "html.dark, body.night {" in CSS


async def test_the_look_is_on_the_modules_page(wall: Scenario) -> None:
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Erin")
        page = (await phone.get("/modules/wall")).text
    assert "Look" in page and "Dark in the evening" in page and "Follow the frame" in page
