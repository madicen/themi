"""CK8: push-to-talk on the cook screen: each phrase through the say route into the same
handlers as a typed line, anything else to Ask Themi, and nothing at all until the person
has turned voice on (403). The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from themi.core import keys
from themi_home.cooking import Cooking, CookingPreferences


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def at_step_two(scenario: Scenario, cooking: Cooking, *, voice: bool = True) -> int:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_voice=voice)
    scenario.primary.queue_structured(lines(ALFREDO))
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    session = await cooking.start(erin, alfredo)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next", "next"):
        await cooking.advance(session, action)
    return session.id


async def say(site: httpx.AsyncClient, csrf: str, session_id: int, text: str) -> httpx.Response:
    return await site.post(f"/session/cook/{session_id}/say",
                           data={"csrf": csrf, "text": text})  # fmt: skip


async def test_each_phrase(scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    session_id = await at_step_two(scenario, cooking)
    state = (await say(site, csrf, session_id, "Next.")).json()
    assert (state["heard"], state["step"]["label"]) == ("Next.", "3")
    state = (await say(site, csrf, session_id, "back")).json()
    assert state["step"]["label"] == "2"
    state = (await say(site, csrf, session_id, "go to step three")).json()
    assert state["step"]["label"] == "3"
    cards = len(scenario.inbox("Erin"))
    await say(site, csrf, session_id, "Repeat")
    assert len(scenario.inbox("Erin")) == cards + 1  # the step again, as typed "repeat"
    assert scenario.inbox("Erin")[-1].startswith("Alfredo Sauce: step 3 of 3")
    await site.post(f"/session/cook/{session_id}/act", headers={"X-Requested-With": "fetch"},
                    data={"csrf": csrf, "action": "timer", "minutes": "10", "step": "3",
                          "seq": str(cooking.get(session_id).seq)})  # type: ignore[union-attr]  # fmt: skip
    state = (await say(site, csrf, session_id, "Add two minutes")).json()
    assert state["timers"][0]["ends_at"] == "2026-10-21T16:12:00+00:00"
    state = (await say(site, csrf, session_id, "How long left?")).json()
    assert state["said"] == "12 min left on step 3."
    state = (await say(site, csrf, session_id, "cancel the timer")).json()
    assert state["timers"] == [] and state["open_chat"] is False


async def test_anything_else_goes_to_ask_themi(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    session_id = await at_step_two(scenario, cooking)
    scenario.primary.queue_text("From the recipe: 1 tsp lemon juice.")
    state = (await say(site, csrf, session_id, "how much lemon juice")).json()
    assert state["open_chat"] is True and state["step"]["label"] == "2"
    assert state["chat"][-1] == {"who": "themi", "text": "From the recipe: 1 tsp lemon juice."}


async def test_voice_is_off_until_turned_on(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    session_id = await at_step_two(scenario, cooking, voice=False)
    response = await say(site, csrf, session_id, "next")
    assert response.status_code == 403
    assert cooking.state(scenario.member("Erin"))["step"]["label"] == "2"
    page = (await site.get("/session")).text
    assert "cook-mic" not in page  # no button either
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_voice=True)
    page = (await site.get("/session")).text
    assert (
        'class="cook-mic" data-on="1"' in page and "hidden" in page
    )  # until the script sees support


async def test_someone_elses_session_is_404(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    session_id = await at_step_two(scenario, cooking)
    csrf = await sign_in(scenario, site, "Husband")
    husband = scenario.member("Husband")
    scenario.app.store.save_preferences(husband, husband.id, CookingPreferences,
                                        cooking_voice=True)  # fmt: skip
    assert (await say(site, csrf, session_id, "next")).status_code == 404


async def test_the_setting_says_where_the_audio_goes(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert "Voice on the cook screen" in page
    assert "Chrome sends the audio to Google to recognise it" in page
