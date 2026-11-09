"""CK5: company in the kitchen: the chameleon's cooking states, Themi's lines at the
boundaries (to chat only while the screen is open), the stuck line once and never while a
timer runs, music with BD5c's suggestion, and Spotify on the cook screen. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from tests.fakes.spotify import FakeSpotify
from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_body_double import own_playlists
from tests.unit.test_cook_screen import ALFREDO, lines
from themi import clock
from themi.core import keys
from themi_home import cooking as cooking_module
from themi_home.body_double_guided import STUCK_TEXT
from themi_home.body_double_scene import pick_cooking_state
from themi_home.cooking import Cooking

SRC = Path(__file__).parents[2] / "src"
STATIC = SRC / "themi_home" / "web" / "static"
NOT_SAID = re.compile(r"\byou should\b|\bdon'?t forget\b|\bneed to\b|\bmust\b|\bremember\b", re.I)


def test_the_cooking_states() -> None:
    now = clock.now()
    assert pick_cooking_state(now=now, timer_running=False) == "watching"
    assert pick_cooking_state(now=now, timer_running=True) == "stirring"
    later = now + timedelta(seconds=10)
    assert pick_cooking_state(now=now, timer_running=True, cheer_until=later) == "cheering"
    assert pick_cooking_state(now=later, timer_running=False, cheer_until=later) == "watching"


def test_the_kitchen_scene_is_drawn() -> None:
    scenes = (STATIC / "chameleon" / "scenes.svg").read_text()
    chameleon = (STATIC / "chameleon" / "chameleon.svg").read_text()
    css = (SRC / "themi" / "web" / "static" / "themi.css").read_text()
    assert 'class="scene scene-cooking"' in scenes
    assert '.session-scene[data-mode="cooking"] .scene-cooking' in css
    for prop in ("apron", "spoon"):
        assert f'class="prop prop-{prop}"' in chameleon


def test_the_lines_are_offers_or_plain_words() -> None:
    every = [*cooking_module.PHASE_LINES.values(), cooking_module.DONE_LINE, STUCK_TEXT,
             "I'm here. Pancakes for 4, whenever you're ready.", "Time's up: Step 5."]  # fmt: skip
    assert not [line for line in every if NOT_SAID.search(line)]


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def start(scenario: Scenario, cooking: Cooking, **kw: object) -> int:
    scenario.primary.queue_structured(lines(ALFREDO))
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    session = await cooking.start(scenario.member("Erin"), alfredo, **kw)  # type: ignore[arg-type]
    return session.id


async def tap(cooking: Cooking, scenario: Scenario, session_id: int, action: str, **form: str):  # type: ignore[no-untyped-def]
    erin = scenario.member("Erin")
    return await cooking.act_from_page(erin, session_id, action, cooking.state(erin)["seq"], form)


async def test_the_start_line_and_phase_lines(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    scenario.app.db.execute("UPDATE recipes SET yield_said = '2' WHERE name = 'Alfredo Sauce'")
    scenario.primary.queue_structured(lines(ALFREDO))
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    session = await cooking.start(erin, alfredo, scale=2.0, scale_said="for 4")
    assert cooking.state(erin)["line"] == "I'm here. Alfredo Sauce for 4, whenever you're ready."
    sent = len(scenario.inbox("Erin"))
    await tap(cooking, scenario, session.id, "next")
    assert cooking.state(erin)["line"] == "Gathering first. Tap each one as it's out."
    assert len(scenario.inbox("Erin")) == sent  # the screen isn't open: the chat card is enough
    cooking.seen(erin)  # the cook screen asked for its state
    scenario.primary.queue_structured({"jobs": [{"text": "Garlic: peel", "line": 3,
                                                 "tool": "knife"}]})  # fmt: skip
    await tap(cooking, scenario, session.id, "next")
    assert scenario.inbox("Erin")[-1] == "Prep next, then the steps."


async def test_the_scene_follows_the_timers(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking)
    assert cooking.state(erin)["scene"] == "watching"
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await tap(cooking, scenario, session_id, action)
    await tap(cooking, scenario, session_id, "goto", to="3")
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    assert cooking.state(erin)["scene"] == "stirring"
    await tap(cooking, scenario, session_id, "finish")
    done = cooking.state(erin)  # the kept timer keeps the screen
    assert done["scene"] == "cheering" and done["line"] == "All done. Enjoy it!"
    clock.advance(timedelta(seconds=30))
    assert cooking.state(erin)["scene"] == "stirring"


async def test_the_stuck_line_once(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await tap(cooking, scenario, session_id, action)
    clock.advance(timedelta(minutes=19))
    cooking.seen(erin)
    assert await cooking.stuck() == 0
    clock.advance(timedelta(minutes=2))
    cooking.seen(erin)
    assert await cooking.stuck() == 1
    assert scenario.inbox("Erin")[-1] == STUCK_TEXT
    assert cooking.state(erin)["line"] == STUCK_TEXT
    await tap(cooking, scenario, session_id, "next")
    clock.advance(timedelta(minutes=25))
    cooking.seen(erin)
    assert await cooking.stuck() == 0  # once a session


async def test_no_stuck_line_while_a_timer_runs(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await tap(cooking, scenario, session_id, action)
    await tap(cooking, scenario, session_id, "goto", to="3")
    await tap(cooking, scenario, session_id, "timer", minutes="30", step="3")
    clock.advance(timedelta(minutes=25))
    cooking.seen(erin)
    assert await cooking.stuck() == 0
    assert STUCK_TEXT not in scenario.inbox("Erin")


async def test_music_with_the_suggestion_for_cooking(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    await start(scenario, cooking)
    music = cooking.state(erin)["music"]
    assert (music["sound"], music["offer"]) == ("lofi", "Some lofi while you cook?")
    from themi_home.body_double_music import set_sound

    set_sound(scenario.app.store, erin, "rain")
    assert cooking.state(erin)["music"]["offer"] == "Rain again, like last time?"


async def test_their_spotify_on_the_cook_screen(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify, cooking: Cooking
) -> None:
    await own_playlists(scenario, site, fake_spotify)
    csrf = await sign_in(scenario, site, "Erin")
    await start(scenario, cooking)
    page = (await site.get("/session")).text
    assert "My Spotify" in page
    spotify = (await site.get("/session/state")).json()["music"]["spotify"]
    assert spotify[0]["name"] == "Kitchen Dance"  # one that fits cooking first
    played = await site.post(
        "/session/spotify",
        headers={"X-Requested-With": "fetch"},
        data={"csrf": csrf, "action": "play", "uri": spotify[0]["uri"]},
    )
    assert played.json()["said"].startswith("Playing")
    assert fake_spotify.playing["context_uri"] == spotify[0]["uri"]  # type: ignore[index]
