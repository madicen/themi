"""F52a: the wall goes full screen on the frame, whichever way it's opened, and Wall frames
says how each frame shows it."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from tests.fixtures.web import sign_in, web_client
from tests.integration.test_wall_page import devices, paired, wall
from tests.scenarios.harness import Scenario
from themi_home.wall import DISPLAY_HEADER, DISPLAYS

__all__ = ["wall"]  # the fixture

STATIC = Path(__file__).parents[2] / "src" / "themi_home" / "web" / "static"


async def frames_page(s: Scenario) -> str:
    async with web_client(s) as phone:
        await sign_in(s, phone, "Erin")
        return (await phone.get("/wall/frames")).text


async def poll(frame: httpx.AsyncClient, display: str | None) -> None:
    headers = {DISPLAY_HEADER: display} if display is not None else {}
    response = await frame.get("/wall/part/top", headers=headers)
    assert response.status_code == 200


def test_a_touch_asks_for_full_screen_on_the_root_element() -> None:
    script = (STATIC / "wall.js").read_text()
    assert 'addEventListener("pointerdown", fullScreen)' in script
    assert "document.documentElement" in script and "root.requestFullscreen(" in script
    assert 'navigationUI: "hide"' in script and "document.fullscreenElement" in script
    assert "(display-mode: " in script
    assert f'headers["{DISPLAY_HEADER}"] = shownAs()' in script


def test_the_views_still_scroll_in_full_screen() -> None:
    css = (STATIC / "wall.css").read_text()
    sheet = re.search(r"\.wall-sheet \{([^}]*)\}", css)
    assert sheet and "overflow: auto" in sheet[1]
    root = re.search(r"html\.wall-root \{([^}]*)\}", css)
    assert root and "overflow" not in root[1]


async def test_a_frame_in_a_chrome_tab_says_so_on_wall_frames(wall: Scenario) -> None:
    async with web_client(wall) as frame:
        await paired(wall, frame)
        assert "In a Chrome tab" not in await frames_page(wall)
        await poll(frame, "browser")
    [device] = devices(wall).all()
    assert device.display == "browser"
    page = await frames_page(wall)
    assert "In a Chrome tab: see the guide" in page


async def test_an_installed_frame_and_one_made_full_screen_by_a_touch(wall: Scenario) -> None:
    async with web_client(wall) as frame:
        await paired(wall, frame)
        await poll(frame, "fullscreen")
        assert "Full screen app" in await frames_page(wall)
        await poll(frame, "fullscreen-api")
    assert "Full screen after a touch" in await frames_page(wall)


async def test_an_unknown_value_or_no_header_leaves_what_was_kept(wall: Scenario) -> None:
    async with web_client(wall) as frame:
        await paired(wall, frame)
        await poll(frame, "<script>")
        assert devices(wall).all()[0].display is None
        await poll(frame, "fullscreen")
        await poll(frame, None)
        await poll(frame, "kiosk")
    assert devices(wall).all()[0].display == "fullscreen"
    assert set(DISPLAYS) == {"fullscreen", "fullscreen-api", "standalone", "browser"}


async def test_the_manifest_still_asks_for_full_screen(wall: Scenario) -> None:
    async with web_client(wall) as frame:
        await paired(wall, frame)
        manifest = (await frame.get("/wall/manifest.webmanifest")).json()
    assert manifest["display"] == "fullscreen"
    assert manifest["display_override"] == ["fullscreen", "standalone"]
    assert manifest["id"] == "/wall" and manifest["scope"] == "/wall"


async def test_the_guide_says_to_install_and_what_to_do_without_google_play(
    wall: Scenario,
) -> None:
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Erin")
        page = (await phone.get("/modules/wall")).text
    assert "Install app" in page and "Add to Home screen" in page
    assert "kiosk browser" in page and "Full screen app" in page
