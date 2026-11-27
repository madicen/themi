"""CF3: a note is sorted in the background: Themi's own display fixes apply at once and are
reported, a change is checked against the recipe's words, a note is kept for wrap-up. The
clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fixtures.cookbook import load, recipe
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import lines
from themi.ai.errors import PermanentError
from themi.core import keys
from themi_home.cooking import Cooking, Session

CHANA = [
    ("T", "Madicen Family Cookbook"),
    ("H1", "Entrees"),
    *recipe(
        "Chana Masala",
        ["1 onion, diced", "1 tsp cumin", "1 tsp smoked paprika", "1 can chickpeas"],
        ["Fry the onion until soft.", "Add the onion and spices and cook 2 minutes.",
         "Stir in the chickpeas and simmer 10 minutes."],
    ),
]  # fmt: skip
ITEMS = ["onion", "cumin", "smoked paprika", "chickpeas"]
ENERGY_WORDS = ("energy", "capacity", "score")


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services, CHANA)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None and found.notes is not None
    return found


async def at_step(scenario: Scenario, cooking: Cooking, step: int):  # type: ignore[no-untyped-def]
    scenario.primary.queue_structured(lines(ITEMS))
    chana = next(r for r in cooking.recipes.all() if r.name == "Chana Masala")
    session = await cooking.start(scenario.member("Erin"), chana)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next", f"goto:{step}"):
        await cooking.advance(session, action)
    found = cooking.get(session.id)
    assert found is not None
    return found


def live(cooking: Cooking, session_id: int) -> Session:
    """The session as it's kept now (it must be there)."""
    found = cooking.get(session_id)
    assert found is not None
    return found


def answer(kind: str, **more: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": kind, "summary": "", "links": {"add": [], "remove": []},
        "grams": {"ingredient": "", "amount": 0, "unit": "", "grams": 0}, "ops": [],
        "note": "", "report": "none", "bug": "",
    }  # fmt: skip
    return {**base, **more}


def op(name: str, **fields: Any) -> dict[str, Any]:
    return {"op": name, "old": "", "olds": [], "new": [], "after": "", "group": "", **fields}


def reports(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query("SELECT kind, text, context FROM feedback ORDER BY id")


async def note_and_sort(scenario: Scenario, cooking: Cooking, session, data: dict[str, Any],  # type: ignore[no-untyped-def]
                        **note: Any):  # fmt: skip
    assert cooking.notes is not None
    left = cooking.notes.add(session, scenario.member("Erin"), **note)
    assert left is not None
    scenario.primary.queue_structured(data)
    await scenario.run_jobs()
    sorted_note = cooking.notes.get(left.id)
    assert sorted_note is not None
    return sorted_note


async def test_the_missing_spices_are_added_at_once_and_reported(
    scenario: Scenario, cooking: Cooking
) -> None:
    erin = scenario.member("Erin")
    session = await at_step(scenario, cooking, 2)
    before = [a["line"] for a in cooking.state(erin)["amounts"]["uses"]]
    assert before == ["1 onion, diced"]  # the spices bug, with no model answer cached
    data = answer("display", summary="The spices weren't listed", report="bug",
                  bug="Collective 'spices' not linked",
                  links={"add": [{"line": 2, "item": "cumin"}, {"line": 3, "item": "paprika"},
                                 {"line": 4, "item": "butter"}],  # not in its line: dropped
                         "remove": []})  # fmt: skip
    note = await note_and_sort(scenario, cooking, session, data, chip="Missing ingredients")
    assert (note.kind, note.status) == ("display", "fixed")
    assert note.proposal == {"links": {"add": [1, 2], "remove": []}}
    state = cooking.state(erin)
    assert [a["line"] for a in state["amounts"]["uses"]] == [
        "1 onion, diced", "1 tsp cumin", "1 tsp smoked paprika"]  # fmt: skip
    assert state["line"] == "Added the cumin and smoked paprika to step 2."
    ((kind, text, context),) = [tuple(r.values()) for r in reports(scenario)]
    assert kind == "bug" and text.startswith("Cooking: Collective 'spices' not linked")
    snap = json.loads(context)["cooking"]
    assert snap["recipe"] == "Chana Masala" and snap["step"] == "2"
    assert snap["shown"]["amounts"] == ["1 onion, diced"] and snap["note"] == "Missing ingredients"
    assert not any(w in context.lower() for w in ENERGY_WORDS)
    assert note.bug_id is not None


async def test_a_fix_is_retired_when_the_steps_words_change(
    scenario: Scenario, cooking: Cooking
) -> None:
    session = await at_step(scenario, cooking, 2)
    data = answer("display", links={"add": [{"line": 2, "item": "cumin"}], "remove": [
        {"line": 1, "item": "onion"}]})  # fmt: skip
    await note_and_sort(scenario, cooking, session, data, said="no onion here, cumin yes")
    chana = cooking.recipes.get(session.recipe_id)
    assert chana is not None
    items = cooking.groceries.known(chana)
    assert cooking.links.links(chana, items)[1] == [1]
    steps = [{"text": s.text, "group": s.group} for s in chana.steps]
    steps[1]["text"] = "Add the spices and cook 2 minutes."
    scenario.app.db.execute("UPDATE recipes SET steps = ? WHERE id = ?",
                            (json.dumps(steps), chana.id))  # fmt: skip
    changed = cooking.recipes.get(chana.id)
    assert changed is not None
    assert cooking.links.links(changed, items)[1] == []  # the fix no longer fits the step


async def test_a_change_is_checked_against_the_recipes_words(
    scenario: Scenario, cooking: Cooking
) -> None:
    session = await at_step(scenario, cooking, 3)
    split = answer("change", summary="Split step 3", ops=[op(
        "split_step", old="Stir in the chickpeas and simmer 10 minutes.",
        new=["Stir in the chickpeas.", "Simmer 10 minutes."])])  # fmt: skip
    note = await note_and_sort(scenario, cooking, session, split, chip="Split this step")
    assert (note.kind, note.status) == ("change", "open")
    assert note.proposal["ops"][0]["new"] == ["Stir in the chickpeas.", "Simmer 10 minutes."]
    assert reports(scenario) == []  # a recipe change isn't Themi's bug
    made_up = answer("change", ops=[op("replace_step", old="Bake for an hour.",
                                       new=["Bake for 70 minutes."])])  # fmt: skip
    note = await note_and_sort(scenario, cooking, session, made_up, said="longer")
    assert (note.kind, note.status) == ("note", "open")  # words the recipe never had
    assert note.proposal["ops"] == [
        {"op": "add_note", "old": "", "olds": [], "new": ["Note: Longer (cooked Oct 21)"],
         "after": "", "group": ""}]  # fmt: skip


async def test_a_note_to_keep(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, 1)
    data = answer("note", note="less salt next time")
    note = await note_and_sort(scenario, cooking, session, data, said="next time less salt")
    assert note.kind == "note" and note.proposal["ops"][0]["new"] == [
        "Note: Less salt next time (cooked Oct 21)"]  # fmt: skip


async def test_about_themi_is_only_reported(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, 1)
    data = answer("other", report="idea", bug="A louder chime option")
    note = await note_and_sort(scenario, cooking, session, data, said="chime is too quiet")
    assert (note.kind, note.status) == ("other", "reported")
    assert [r["kind"] for r in reports(scenario)] == ["idea"]


async def test_with_no_model_the_note_is_kept_and_reported(
    scenario: Scenario, cooking: Cooking
) -> None:
    session = await at_step(scenario, cooking, 2)
    assert cooking.notes is not None
    left = cooking.notes.add(session, scenario.member("Erin"), said="the spices are missing")
    assert left is not None
    scenario.primary.queue_error(PermanentError("no key"), op="structured")
    scenario.fallback.queue_error(PermanentError("no key"), op="structured")
    await scenario.run_jobs()
    note = cooking.notes.get(left.id)
    assert note is not None and (note.kind, note.status) == ("note", "open")
    assert note.proposal["ops"][0]["new"] == ["Note: The spices are missing (cooked Oct 21)"]
    assert [r["kind"] for r in reports(scenario)] == ["bug"]


async def test_a_wrong_gram_weight_waits_for_wrap_up(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, 2)
    data = answer("display", grams={"ingredient": "cumin", "amount": 1, "unit": "tsp",
                                    "grams": 2.5})  # fmt: skip
    note = await note_and_sort(scenario, cooking, session, data, said="1 tsp cumin is 2.5 g")
    assert (note.kind, note.status) == ("display", "open")  # the guide is a doc: a tap first
    assert note.proposal == {"grams": {"ingredient": "cumin", "amount": 1.0, "unit": "tsp",
                                       "grams": 2.5}}  # fmt: skip
