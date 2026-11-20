"""The wall (WL1): pairing the frame, its own sign-in, and signing it out."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.app import family_modules
from themi_home.wall import WALL_COOKIE, WallDevices, WallModule


@pytest.fixture
async def wall(family: SeededFamily, fake_telegram: FakeTelegram) -> AsyncIterator[Scenario]:
    scenario = Scenario(family, fake_telegram, modules=[*family_modules(), WallModule()])
    await scenario.start()
    try:
        yield scenario
    finally:
        await scenario.stop()


def devices(scenario: Scenario) -> WallDevices:
    return scenario.app.services.get(WallDevices)


async def paired(scenario: Scenario, frame: httpx.AsyncClient) -> str:
    """Pair `frame` with a fresh code; returns its cookie."""
    code = devices(scenario).new_code(scenario.member("Erin"))
    response = await frame.post("/wall/pair", data={"code": code, "name": "Hall"})
    assert response.status_code == 303 and response.headers["location"] == "/wall"
    return response.cookies[WALL_COOKIE]


async def test_an_admin_gets_a_code_and_the_frame_pairs_with_it(wall: Scenario) -> None:
    async with web_client(wall) as phone, web_client(wall) as frame:
        csrf = await sign_in(wall, phone, "Erin")
        page = await phone.post("/wall/frames/code", data={"csrf": csrf})
        match = re.search(r'aria-label="Pairing code">(\d{3}) (\d{3})<', page.text)
        assert page.status_code == 200 and match
        assert (await frame.get("/wall")).headers["location"] == "/wall/pair"
        response = await frame.post("/wall/pair", data={"code": match[1] + match[2]})
        assert response.status_code == 303
        shown = await frame.get("/wall")
        assert shown.status_code == 200 and 'class="wall-screen"' in shown.text
        listed = await phone.get("/wall/frames")
    assert "Last seen" in listed.text and 'id="frame-' in listed.text


async def test_a_code_works_once_and_not_after_ten_minutes(wall: Scenario) -> None:
    erin = wall.member("Erin")
    code = devices(wall).new_code(erin)
    assert devices(wall).pair(code) is not None
    assert devices(wall).pair(code) is None
    late = devices(wall).new_code(erin)
    clock.advance(timedelta(minutes=10))
    assert devices(wall).pair(late) is None
    fresh = devices(wall).new_code(erin)
    clock.advance(timedelta(minutes=9, seconds=59))
    assert devices(wall).pair(fresh) is not None


async def test_a_new_code_retires_the_last_one(wall: Scenario) -> None:
    first = devices(wall).new_code(wall.member("Erin"))
    second = devices(wall).new_code(wall.member("Erin"))
    assert first == second or devices(wall).pair(first) is None
    assert devices(wall).pair(second) is not None


async def test_five_wrong_codes_lock_pairing_for_ten_minutes(wall: Scenario) -> None:
    async with web_client(wall) as frame:
        for _ in range(4):  # no code is open yet, so any code is wrong
            wrong = await frame.post("/wall/pair", data={"code": "000000"})
            assert wrong.status_code == 400 and "didn" in wrong.text
        code = devices(wall).new_code(wall.member("Erin"))
        await frame.post("/wall/pair", data={"code": f"{(int(code) + 1) % 10**6:06d}"})
        locked = await frame.post("/wall/pair", data={"code": code})
        assert locked.status_code == 429 and "Too many wrong codes" in locked.text
        clock.advance(timedelta(minutes=10, seconds=1))
        code = devices(wall).new_code(wall.member("Erin"))
        assert (await frame.post("/wall/pair", data={"code": code})).status_code == 303


async def test_the_frame_reaches_only_the_wall(wall: Scenario) -> None:
    async with web_client(wall) as frame:
        cookie = await paired(wall, frame)
        frame.cookies.set(WALL_COOKIE, cookie)
        assert (await frame.get("/wall")).status_code == 200
        for path in ("/", "/tasks", "/lists", "/settings", "/admin/usage", "/wall/frames"):
            response = await frame.get(path)
            assert response.status_code == 303, path
            assert response.headers["location"] == "/signed-out", path


async def test_signing_a_frame_out_works_at_its_next_request(wall: Scenario) -> None:
    async with web_client(wall) as phone, web_client(wall) as frame:
        await paired(wall, frame)
        assert (await frame.get("/wall")).status_code == 200
        csrf = await sign_in(wall, phone, "Erin")
        [device] = devices(wall).all()
        response = await phone.post(f"/wall/frames/{device.id}/revoke", data={"csrf": csrf})
        assert response.status_code == 303
        assert (await frame.get("/wall")).headers["location"] == "/wall/pair"
    assert devices(wall).all() == []


async def test_only_admins_pair_or_sign_frames_out(wall: Scenario) -> None:
    async with web_client(wall) as phone, web_client(wall) as frame:
        await paired(wall, frame)
        [device] = devices(wall).all()
        csrf = await sign_in(wall, phone, "Husband")
        assert (await phone.get("/wall/frames")).status_code == 403
        assert (await phone.post("/wall/frames/code", data={"csrf": csrf})).status_code == 403
        revoke = await phone.post(f"/wall/frames/{device.id}/revoke", data={"csrf": csrf})
        assert revoke.status_code == 403
    assert len(devices(wall).all()) == 1


async def test_a_member_can_look_at_the_wall_from_their_phone(wall: Scenario) -> None:
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Husband")
        page = await phone.get("/wall")
    assert page.status_code == 200 and 'class="wall-screen"' in page.text


async def test_the_token_and_code_are_never_kept_or_logged_in_clear(
    wall: Scenario, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with web_client(wall) as frame:
        code = devices(wall).new_code(wall.member("Erin"))
        response = await frame.post("/wall/pair", data={"code": code})
        token = response.cookies[WALL_COOKIE]
        frame.cookies.set(WALL_COOKIE, token)
        await frame.get("/wall")
    db = wall.app.store.db
    stored = [
        str(v)
        for table in ("wall_devices", "wall_pairing_codes")
        for row in db.query(f"SELECT * FROM {table}")
        for v in row.values()
    ]
    assert not any(token in v for v in stored) and code not in stored
    assert token not in caplog.text


async def test_the_module_is_listed_in_your_day(wall: Scenario) -> None:
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Erin")
        page = await phone.get("/modules/wall")
    assert page.status_code == 200 and "Your day" in page.text and "Wall frames" in page.text
