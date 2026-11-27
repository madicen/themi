"""CF2: notes left while cooking: saved on the step shown, from a tap, chat or voice, with
nothing asked. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from tests.unit.test_cooking_note_sort import live
from themi.core import keys
from themi_home import cooking_voice
from themi_home.cooking import Cooking, CookingPreferences
from themi_home.cooking_notes import NOTED, said_note


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None and found.notes is not None
    return found


async def at_step(scenario: Scenario, cooking: Cooking, step: str = "2", *, in_group: bool = False):  # type: ignore[no-untyped-def]
    scenario.primary.queue_structured(lines(ALFREDO))
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    session = await cooking.start(scenario.member("Erin"), alfredo, in_group=in_group)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next", f"goto:{step}"):
        await cooking.advance(session, action)
    found = cooking.get(session.id)
    assert found is not None and found.phase == "cook"
    return found


def test_said_note() -> None:
    assert said_note("note: split this into two") == "split this into two"
    assert said_note("Note that the spices aren't listed") == "the spices aren't listed"
    assert said_note("Themi, note less salt") == "less salt"
    assert said_note("make a note the oven runs hot") == "the oven runs hot"
    assert said_note("next time less garlic") == "next time less garlic"
    for not_a_note in ("note", "notes", "next", "what's next", "noted", "a note on timing?"):
        assert said_note(not_a_note) is None, not_a_note


async def test_a_note_is_saved_on_the_step_shown(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session = await at_step(scenario, cooking, "2")
    assert cooking.notes is not None
    note = cooking.notes.add(session, erin, chip="Split this step")
    assert note is not None
    assert (note.step_label, note.step_index, note.how) == ("2", 1, "tap")
    assert note.step_text.startswith("Blend cashews and all other ingredients")
    assert note.status == "new" and note.kind is None
    assert note.shown["amounts"]  # what the screen showed, for the sort and the report
    earlier = cooking.notes.add(session, erin, said="soak longer", label="1")  # the sheet's step
    assert earlier is not None and earlier.step_label == "1"
    line = cooking.notes.add(session, erin, chip="Not used here", line=2)
    assert line is not None and line.shown["line_text"].startswith("2 garlic cloves")
    assert cooking.notes.add(session, erin) is None  # empty
    assert cooking.notes.add(session, erin, chip="Make it vegan") is None  # not a chip
    assert cooking.notes.add(session, erin, chip="Wrong amount", line=40) is None
    assert [n.id for n in cooking.notes.for_session(session.id)] == [note.id, earlier.id, line.id]


async def test_a_typed_note_is_noted_and_nothing_is_asked(
    scenario: Scenario, cooking: Cooking
) -> None:
    session = await at_step(scenario, cooking, "3")
    calls = len(scenario.primary.requests)
    await scenario.say("Erin", "note: less salt next time")
    assert scenario.inbox("Erin")[-1] == NOTED
    assert len(scenario.primary.requests) == calls  # no model call to answer it
    assert cooking.notes is not None
    (note,) = cooking.notes.for_session(session.id)
    assert (note.said, note.how, note.step_label) == ("less salt next time", "typed", "3")
    assert live(cooking, session.id).step == session.step  # the session didn't move


async def test_the_cooking_note_tool(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, "1")
    scenario.primary.queue_tool_call("cooking_note", {"note": "the cashews need longer"})
    scenario.primary.queue_text(NOTED)
    await scenario.say("Erin", "can you remember the cashews needed longer to soak")
    assert cooking.notes is not None
    (note,) = cooking.notes.for_session(session.id)
    assert note.said == "the cashews need longer" and note.step_label == "1"


async def test_a_spoken_note(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session = await at_step(scenario, cooking, "2")
    heard = await cooking_voice.say(cooking, erin, session, "Note: blend it longer.")
    assert heard.said == NOTED and not heard.ask
    assert cooking.notes is not None
    (note,) = cooking.notes.for_session(session.id)
    assert (note.said, note.how) == ("blend it longer.", "voice")
    assert live(cooking, session.id).line == NOTED and scenario.inbox("Erin")[-1:] != [NOTED]


async def test_the_note_sheet_on_the_screen(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    session = await at_step(scenario, cooking, "2")
    state = (await site.get("/session/state")).json()
    assert state["notes"] == {"on": True, "count": 0, "chips": [
        "Missing ingredients", "Split this step", "Wrong amount", "Something else"],
        "line_chips": ["Not used here", "Wrong amount"]}  # fmt: skip
    page = (await site.get("/session/cook/view")).text
    assert "A note for after. Nothing to answer now." in page and "Save note" in page

    async def tap(**form: str) -> httpx.Response:
        return await site.post(
            f"/session/cook/{session.id}/act", headers={"X-Requested-With": "fetch"},
            data={"csrf": csrf, **form},
        )  # fmt: skip

    stale = str(state["seq"] - 1)  # from an older screen: still saved, on the step it showed
    tapped = (await tap(action="note", seq=stale, chip="Split this step", label="2")).json()
    assert tapped["said"] == NOTED and tapped["notes"]["count"] == 1
    tapped = (await tap(action="line_note", seq=stale, chip="Not used here", n="3")).json()
    assert tapped["notes"]["count"] == 2
    tapped = (await tap(action="note", seq=stale, said="", label="2")).json()
    assert tapped["notes"]["count"] == 2  # an empty note isn't saved
    assert cooking.notes is not None
    assert [(n.chip, n.line) for n in cooking.notes.for_session(session.id)] == [
        ("Split this step", None), ("Not used here", 3)]  # fmt: skip
    assert scenario.inbox("Erin") == [] or NOTED not in scenario.inbox("Erin")


async def test_partners_share_a_group_sessions_notes(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    session = await at_step(scenario, cooking, "2", in_group=True)
    csrf = await sign_in(scenario, site, "Husband")
    state = (await site.get("/session/state")).json()
    await site.post(
        f"/session/cook/{session.id}/act", headers={"X-Requested-With": "fetch"},
        data={"csrf": csrf, "action": "note", "seq": str(state["seq"]), "said": "more garlic"},
    )  # fmt: skip
    assert cooking.notes is not None
    (note,) = cooking.notes.for_session(session.id)
    assert note.member_id == scenario.member("Husband").id


async def test_voice_hint_only_with_voice_on(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    await at_step(scenario, cooking, "2")
    assert 'Or say "note:"' not in (await site.get("/session/cook/view")).text
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_voice=True)
    assert 'Or say "note:"' in (await site.get("/session/cook/view")).text
