"""CF7: a prep job and a step's timer, fixed on Themi's side from a cooking note, at once,
retired when the step's words change. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json

from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import lines
from tests.unit.test_cooking_note_sort import ITEMS, answer, at_step, live, note_and_sort
from tests.unit.test_cooking_note_sort import cooking as cooking  # a fixture
from themi_home.cooking import Cooking


async def test_a_timer_changed_at_once_and_next_time(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session = await at_step(scenario, cooking, 3)  # "... simmer 10 minutes."
    assert [o["label"] for o in cooking.state(erin)["offers"]] == ["Timer 10 min"]
    data = answer("display", timer={"said": "10 min", "minutes": 12}, report="bug")
    note = await note_and_sort(scenario, cooking, session, data, said="that's 12 minutes")
    assert (note.kind, note.status) == ("display", "fixed")
    state = cooking.state(erin)
    assert [o["label"] for o in state["offers"]] == ["Timer 12 min"]
    assert state["offers"][0]["minutes"] == 12 and state["line"] == "Step 3: a 12 min timer."
    await cooking.advance(live(cooking, session.id), "stop")
    await at_step(scenario, cooking, 3)  # the next cook too
    assert [o["label"] for o in cooking.state(erin)["offers"]] == ["Timer 12 min"]


async def test_a_timer_taken_off_and_one_added(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session = await at_step(scenario, cooking, 3)
    await note_and_sort(scenario, cooking, session,
                        answer("display", timer={"said": "10 min", "minutes": 0}),
                        said="no timer needed")  # fmt: skip
    assert cooking.state(erin)["offers"] == []
    await cooking.advance(live(cooking, session.id), "goto:1")
    await note_and_sort(scenario, cooking, live(cooking, session.id),
                        answer("display", timer={"said": "", "minutes": 8}),
                        said="this needs 8 minutes")  # fmt: skip
    assert [o["label"] for o in cooking.state(erin)["offers"]] == ["Timer 8 min"]


async def test_a_timer_fix_that_doesnt_fit_is_dropped(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, 3)
    data = answer("display", timer={"said": "45 min", "minutes": 50})  # no such button
    note = await note_and_sort(scenario, cooking, session, data, said="longer")
    assert note.kind == "other" and note.status == "reported"


async def test_a_prep_job_fixed(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    scenario.primary.queue_structured(lines(ITEMS))
    chana = next(r for r in cooking.recipes.all() if r.name == "Chana Masala")
    session = await cooking.start(erin, chana)
    scenario.primary.queue_structured({"jobs": [
        {"text": "dice the onion", "line": 1, "tool": "knife"},
        {"text": "chop the cumin", "line": 2, "tool": "knife"}]})  # fmt: skip
    while live(cooking, session.id).phase != "prep":
        await cooking.advance(live(cooking, session.id), "next")
    session = live(cooking, session.id)
    data = answer("display", prep={"job": "chop the cumin", "to": ""}, report="bug")
    note = await note_and_sort(scenario, cooking, session, data, said="you don't chop cumin")
    assert note.status == "fixed" and note.step_label == "prep"
    assert [job["text"] for job in live(cooking, session.id).prep] == ["dice the onion"]
    assert cooking.state(erin)["line"] == 'Took "chop the cumin" off the prep.'
    assert [j["text"] for j in await cooking.prep_jobs(erin, chana)] == ["dice the onion"]
    made_up = answer("display", prep={"job": "peel the garlic", "to": ""})  # never shown
    note = await note_and_sort(scenario, cooking, live(cooking, session.id), made_up, said="no")
    assert note.kind == "other"


async def test_undo_takes_every_fix_of_the_note(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session = await at_step(scenario, cooking, 3)
    note = await note_and_sort(scenario, cooking, session,
                               answer("display", timer={"said": "10 min", "minutes": 15}),
                               said="15")  # fmt: skip
    assert cooking.notes is not None
    cooking.notes.undo_fix(note)
    assert [o["label"] for o in cooking.state(erin)["offers"]] == ["Timer 10 min"]
    row = scenario.app.db.one("SELECT data FROM recipe_fixes WHERE note_id = ?", (note.id,))
    assert row is not None and json.loads(row["data"])["minutes"] == 15
