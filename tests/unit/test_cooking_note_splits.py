"""CF8: a long step split on the screen where a cooking note says, instead of RC3b's own
choice; kept whole when asked; the session stays on the words it was on. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json

import pytest

from tests.fixtures.cookbook import load, recipe
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import lines
from tests.unit.test_cooking_note_sort import answer, live, note_and_sort
from themi.core import keys
from themi_home.cooking import Cooking, step_parts

S1 = "Mix the flour, salt and yeast in a large bowl until there are no lumps left at all."
S2 = ("Pour in the warm water and stir with a spatula until a shaggy, sticky dough forms and no "
      "dry flour is left at the bottom of the bowl.")  # fmt: skip
S3 = ("Cover the bowl with a damp towel and leave it somewhere warm until it has doubled in "
      "size, which takes about an hour in a warm kitchen.")  # fmt: skip
S4 = "Butter two loaf pans generously while it rises, so they're ready."
LONG = f"{S1} {S2} {S3} {S4}"
BREAD = [("T", "Madicen Family Cookbook"), ("H1", "Breakfast"),
         *recipe("Peasant Bread", ["4 Cups flour", "2 tsp salt", "2 tsp yeast", "2 Cups water"],
                 ["Heat the oven.", LONG, "Bake 35 minutes."])]  # fmt: skip


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services, BREAD)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def on_part(scenario: Scenario, cooking: Cooking, label: str):  # type: ignore[no-untyped-def]
    scenario.primary.queue_structured(lines(["flour", "salt", "yeast", "water"]))
    bread = next(r for r in cooking.recipes.all() if r.name == "Peasant Bread")
    session = await cooking.start(scenario.member("Erin"), bread)
    scenario.primary.queue_structured({"jobs": []})
    while live(cooking, session.id).phase != "cook":
        await cooking.advance(live(cooking, session.id), "next")
    labels = [p.label for p in step_parts(bread)]
    for _ in range(labels.index(label)):
        await cooking.advance(live(cooking, session.id), "next")
    return live(cooking, session.id)


def labels_and_starts(cooking: Cooking) -> list[tuple[str, str]]:
    bread = next(r for r in cooking.recipes.all() if r.name == "Peasant Bread")
    return [(p.label, p.text[:12]) for p in step_parts(bread)]


async def test_split_where_the_note_says(scenario: Scenario, cooking: Cooking) -> None:
    assert labels_and_starts(cooking)[1:3] == [("2a", S1[:12]), ("2b", S4[:12])]  # RC3b's own
    session = await on_part(scenario, cooking, "2a")
    data = answer("display", split={"after": [1, 3], "whole": False})
    note = await note_and_sort(scenario, cooking, session, data, said="split after the mixing")
    assert (note.kind, note.status) == ("display", "fixed")
    bread = next(r for r in cooking.recipes.all() if r.name == "Peasant Bread")
    assert [(p.label, p.text) for p in step_parts(bread)][1:4] == [
        ("2a", S1), ("2b", f"{S2} {S3}"), ("2c", S4)]  # fmt: skip
    state = cooking.state(scenario.member("Erin"))
    assert state["step"]["text"] == S1 and state["line"] == "Step 2 is split as you said."


async def test_a_session_keeps_its_words(scenario: Scenario, cooking: Cooking) -> None:
    session = await on_part(scenario, cooking, "2b")  # RC3b's 2b: the last sentence
    shown = cooking.state(scenario.member("Erin"))["step"]["text"]
    data = answer("display", split={"after": [], "whole": True})
    await note_and_sort(scenario, cooking, session, data, said="keep this as one step")
    bread = next(r for r in cooking.recipes.all() if r.name == "Peasant Bread")
    assert [p.label for p in step_parts(bread)] == ["1", "2", "3"]
    state = cooking.state(scenario.member("Erin"))
    assert state["step"]["label"] == "2" and shown[:30] in state["step"]["text"]


async def test_a_split_fix_retires_with_new_words(scenario: Scenario, cooking: Cooking) -> None:
    session = await on_part(scenario, cooking, "2a")
    await note_and_sort(
        scenario,
        cooking,
        session,
        answer("display", split={"after": [1], "whole": False}),
        said="split",
    )
    bread = next(r for r in cooking.recipes.all() if r.name == "Peasant Bread")
    assert bread.splits == ((1, (1,)),)
    steps = [{"text": s.text, "group": s.group} for s in bread.steps]
    steps[1]["text"] = LONG + " Then rest it."
    scenario.app.db.execute("UPDATE recipes SET steps = ? WHERE id = ?",
                            (json.dumps(steps), bread.id))  # fmt: skip
    assert cooking.recipes.get(bread.id).splits == ()  # type: ignore[union-attr]


async def test_out_of_range_split_is_dropped(scenario: Scenario, cooking: Cooking) -> None:
    session = await on_part(scenario, cooking, "2a")
    data = answer("display", split={"after": [9], "whole": False})
    note = await note_and_sort(scenario, cooking, session, data, said="split")
    assert note.kind == "other"
