"""CK3: the cook screen's timer rail: labels, [+1] [+5] and [Cancel], a fired timer cleared
by a tap, and the ending's [Keep timers] [Cancel them]. The clock starts Wednesday 21
October 2026, 9 am."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from themi.core import keys
from themi_home.cooking import Cooking, CookingPreferences
from themi_home.cooking_timers import CookingTimers, default_label


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None and found.timers is not None
    return found


def timers(cooking: Cooking) -> CookingTimers:
    assert cooking.timers is not None
    return cooking.timers


async def at_step_three(scenario: Scenario, cooking: Cooking) -> int:
    scenario.primary.queue_structured(lines(ALFREDO))
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    session = await cooking.start(scenario.member("Erin"), alfredo)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await cooking.advance(session, action)
    await cooking.advance(session, "goto:3")
    return session.id


async def tap(cooking: Cooking, scenario: Scenario, session_id: int, action: str, **form: str):  # type: ignore[no-untyped-def]
    erin = scenario.member("Erin")
    seq = cooking.state(erin)["seq"]
    return await cooking.act_from_page(erin, session_id, action, seq, form)


def test_the_default_label_names_the_steps_group(scenario: Scenario, cooking: Cooking) -> None:
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    assert default_label(alfredo, "3") == "Step 3"
    grouped = replace(alfredo, steps=[replace(s, group="Sauce") for s in alfredo.steps])
    assert default_label(grouped, "3") == "Sauce, step 3"


async def test_a_label_of_their_own(scenario: Scenario, cooking: Cooking) -> None:
    session_id = await at_step_three(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="5", label="  The  rice ")
    await tap(cooking, scenario, session_id, "timer", typed="12")
    labels = [(t["label"], t["ends_at"]) for t in cooking.state(scenario.member("Erin"))["timers"]]
    assert labels == [("The rice", "2026-10-21T16:05:00+00:00"),
                      ("Step 3", "2026-10-21T16:12:00+00:00")]  # fmt: skip


async def test_plus_one_and_five_move_the_job(scenario: Scenario, cooking: Cooking) -> None:
    session_id = await at_step_three(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    (timer,) = cooking.state(scenario.member("Erin"))["timers"]
    assert await tap(
        cooking, scenario, session_id, "timer_add", timer=str(timer["id"]), minutes="1"
    )
    assert await tap(
        cooking, scenario, session_id, "timer_add", timer=str(timer["id"]), minutes="5"
    )
    (moved,) = cooking.state(scenario.member("Erin"))["timers"]
    assert moved["ends_at"] == "2026-10-21T16:16:00+00:00"
    await scenario.advance(minutes=10)
    await scenario.run_jobs()
    assert not any("Time's up" in t for t in scenario.inbox("Erin"))  # not at the old end
    await scenario.advance(minutes=6)
    await scenario.run_jobs()
    await scenario.app.outbox.flush()
    assert scenario.inbox("Erin")[-1] == "Time's up: 16 min for step 3 of Alfredo Sauce."
    assert cooking.state(scenario.member("Erin"))["timers"][0]["fired"] is True


async def test_cancel_and_clear(scenario: Scenario, cooking: Cooking) -> None:
    session_id = await at_step_three(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    await tap(cooking, scenario, session_id, "timer", minutes="1", step="3")
    short, long = cooking.state(scenario.member("Erin"))["timers"]
    assert await tap(cooking, scenario, session_id, "timer_cancel", timer=str(long["id"]))
    await scenario.advance(minutes=1)
    await scenario.run_jobs()
    (fired,) = cooking.state(scenario.member("Erin"))["timers"]
    assert fired["id"] == short["id"] and fired["fired"] is True
    assert not await tap(cooking, scenario, session_id, "timer_cancel", timer=str(short["id"]))
    assert await tap(cooking, scenario, session_id, "timer_clear", timer=str(short["id"]))
    assert cooking.state(scenario.member("Erin"))["timers"] == []
    await scenario.advance(minutes=10)
    await scenario.run_jobs()
    assert sum("Time's up" in t for t in scenario.inbox("Erin")) == 1  # the cancelled one: never


async def test_someone_elses_timer_is_left_alone(scenario: Scenario, cooking: Cooking) -> None:
    session_id = await at_step_three(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    (timer,) = cooking.state(scenario.member("Erin"))["timers"]
    assert not timers(cooking).cancel(scenario.member("Husband").id, timer["id"])
    assert timers(cooking).add(scenario.member("Husband").id, timer["id"], 5) is None


async def test_ending_with_timers_asks_on_the_screen(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await at_step_three(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    await tap(cooking, scenario, session_id, "stop")
    assert scenario.inbox("Erin")[-1] == "There's a timer still running. Keep it going?"
    ending = cooking.state(erin)
    assert (ending["phase"], ending["ended"], ending["ask_timers"]) == ("done", True, True)
    assert ending["buttons"] == [] and len(ending["timers"]) == 1
    assert not await tap(cooking, scenario, session_id, "next")  # over: only the timers
    assert await tap(cooking, scenario, session_id, "timers_keep")
    kept = cooking.state(erin)
    assert kept["ask_timers"] is False and len(kept["timers"]) == 1
    assert not await tap(cooking, scenario, session_id, "timers_cancel")  # asked once
    await scenario.advance(minutes=10)
    await scenario.run_jobs()
    (fired,) = cooking.state(erin)["timers"]
    assert await tap(cooking, scenario, session_id, "timer_clear", timer=str(fired["id"]))
    assert cooking.state(erin)["active"] is False  # nothing left to show


async def test_the_chats_answer_is_the_screens(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await at_step_three(scenario, cooking)
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    await scenario.say("Erin", "stop cooking")
    await scenario.tap("Erin", "Cancel them")
    assert cooking.state(erin)["active"] is False  # cancelled in chat: gone from the screen


async def test_the_chime_volume_is_kept(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    erin = scenario.member("Erin")
    assert scenario.app.store.preferences(erin.id, CookingPreferences).cooking_chime_volume == 70
    saved = await site.post("/session/cook/chime", data={"csrf": csrf, "volume": "35"})
    assert saved.status_code == 204
    await at_step_three(scenario, cooking)
    assert cooking.state(erin)["chime_volume"] == 35
    bad = await site.post("/session/cook/chime", data={"csrf": csrf, "volume": "150"})
    assert bad.status_code == 400
