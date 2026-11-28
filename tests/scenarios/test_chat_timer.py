"""WA6: a timer from chat ("start a 6 minute timer"), report #284: it set a reminder instead,
which the wall doesn't show. Wednesday 21 October 2026, 9 am in Los Angeles.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import frame, with_wall, words
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys
from themi.core.tools import ToolContext, ToolFailed
from themi_home.cooking_timers import start_timer
from themi_home.wall_view import WallView


@pytest.fixture
async def wall(family: SeededFamily, fake_telegram: FakeTelegram) -> AsyncIterator[Scenario]:
    s = with_wall(family, fake_telegram)
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def rows(s: Scenario) -> list[dict]:
    return s.app.db.query("SELECT * FROM cooking_timers ORDER BY id")


async def test_start_a_six_minute_timer(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("start_timer", {"minutes": 6, "label": ""})
    await scenario.say("Erin", "Start a 6 minute timer")
    (row,) = rows(scenario)
    assert (row["session_id"], row["step"], row["label"], row["minutes"]) == (
        None, "", "6 min timer", 6,
    )  # fmt: skip
    assert datetime.fromisoformat(row["ends_at"]) == clock.now() + timedelta(minutes=6)
    assert scenario.app.db.query("SELECT 1 FROM outbox WHERE kind = 'reminder'") == []  # #284


async def test_it_ends_with_its_own_words(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    cooking.timers.start_alone(erin, 6)
    cooking.timers.start_alone(erin, 20, "the tea")
    clock.advance(timedelta(minutes=6))
    await scenario.run_jobs()
    await scenario.app.outbox.flush()
    assert "Time's up: 6 min timer." in scenario.inbox("Erin")
    assert "Time's up: the tea." not in scenario.inbox("Erin")


async def test_how_long_add_and_cancel_work_on_it(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    cooking.timers.start_alone(erin, 6, "tea")
    clock.advance(timedelta(minutes=2))
    assert (await scenario.say("Erin", "How long left?"))[-1] == "4 min left on the tea."
    said = (await scenario.say("Erin", "Add 2 minutes"))[-1]
    assert re.fullmatch(r"Added 2 min: the tea is done at \d+:\d\d (am|pm)\.", said)
    assert (await scenario.say("Erin", "Cancel the timer"))[-1] == "Timer cancelled."
    assert rows(scenario)[0]["cancelled_at"] is not None


async def test_the_tool_says_when_and_refuses_odd_lengths(scenario: Scenario) -> None:
    ctx = ToolContext(member=scenario.member("Erin"), services=scenario.app.services)
    said = await start_timer.handler(ctx, {"minutes": 20, "label": "the tea"})
    assert re.fullmatch(r"Timer set: 20 min for tea, done at \d+:\d\d (am|pm)\.", said)
    assert rows(scenario)[0]["label"] == "tea"
    for minutes in (0, -3, 481):
        with pytest.raises(ToolFailed):
            await start_timer.handler(ctx, {"minutes": minutes, "label": ""})


async def test_on_the_wall_with_a_clock_and_got_it(wall: Scenario) -> None:
    wall.primary.queue_tool_call("start_timer", {"minutes": 6, "label": ""})
    await wall.say("Erin", "Start a 6 minute timer")
    clock.advance(timedelta(minutes=2))
    (card,) = WallView(wall.app.services).alerts()
    assert (card.icon, card.label, card.title, card.numerals) == (
        "clock", "Timer", "6 min timer", "4:00",
    )  # fmt: skip
    clock.advance(timedelta(minutes=4))
    await wall.run_jobs()
    async with web_client(wall) as client:
        await frame(wall, client)
        part = (await client.get("/wall/part/alerts")).text
        assert "alert-up" in part and words(part).startswith("6 min timer Time&#39;s up")
        key = re.search(r'data-alert="([^"]+)"', part)
        csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', (await client.get("/wall")).text)
        assert key and csrf
        done = await client.post(
            "/wall/alert", data={"key": key.group(1), "answer": "got_it"},
            headers={"X-CSRF-Token": csrf.group(1)},
        )  # fmt: skip
    assert "wall-alert" not in done.text
    assert rows(wall)[0]["cleared_at"] is not None
