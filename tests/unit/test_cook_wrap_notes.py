"""CF5: the notes at wrap-up, one at a time before CK6's offers: a change shown before and
after, a note to keep, a display fix to keep or undo. Only the session's owner decides. In
chat, with no screen open, the same offers come as messages. The clock starts Wednesday
21 October 2026, 9 am."""

from __future__ import annotations

from typing import Any

import pytest

from tests.scenarios.harness import Scenario
from tests.unit.test_cooking_note_sort import answer, at_step, live, note_and_sort, op
from tests.unit.test_cooking_note_sort import cooking as cooking  # a fixture
from themi_home.cooking import Cooking
from themi_home.cooking_notes_wrap import marked

STEP_3 = "Stir in the chickpeas and simmer 10 minutes."
SPLIT = answer("change", summary="Split step 3", ops=[op(
    "split_step", old=STEP_3, new=["Stir in the chickpeas.", "Simmer 10 minutes."])])  # fmt: skip
LINKS = answer("display", summary="The spices weren't listed",
               links={"add": [{"line": 2, "item": "cumin"}], "remove": []})  # fmt: skip


@pytest.fixture(autouse=True)
def web_recipe(scenario: Scenario, cooking: Cooking) -> None:
    """No cookbook doc in these tests: the recipe's changes go to Themi's own copy."""
    scenario.app.db.execute("UPDATE recipes SET source = 'web' WHERE name = 'Chana Masala'")


async def finished(
    scenario: Scenario,
    cooking: Cooking,
    notes: list[tuple[dict, dict]],
    *,
    in_group: bool = False,
    screen: bool = True,
):  # type: ignore[no-untyped-def]
    session = await at_step(scenario, cooking, 3)
    if in_group:
        scenario.app.db.execute("UPDATE cooking_sessions SET in_group = 1 WHERE id = ?",
                                (session.id,))  # fmt: skip
        session = live(cooking, session.id)
    for data, left in notes:
        await note_and_sort(scenario, cooking, session, data, **left)
    if screen:
        cooking.seen(scenario.member("Erin"))
    await cooking.advance(live(cooking, session.id), "finish")
    return live(cooking, session.id)


def wrap(cooking: Cooking, scenario: Scenario, name: str = "Erin") -> dict[str, Any]:
    return cooking.state(scenario.member(name))["wrap"]


async def tap(cooking: Cooking, scenario: Scenario, session_id: int, action: str,
              name: str = "Erin") -> Any:  # fmt: skip
    state = cooking.state(scenario.member(name))
    return await cooking.act_from_page(scenario.member(name), session_id, action, state["seq"],
                                       {"note": str(state["wrap"]["note"])})  # fmt: skip


def test_marked_words() -> None:
    assert marked("Bake for 20 minutes.", "Bake for 25 minutes, until golden.") == [
        {"text": "Bake for", "new": False},
        {"text": "25 minutes, until golden.", "new": True},
    ]
    assert marked("", "Toast the spices.") == [{"text": "Toast the spices.", "new": True}]


async def test_the_notes_come_first_one_at_a_time(scenario: Scenario, cooking: Cooking) -> None:
    session = await finished(scenario, cooking, [
        (LINKS, {"chip": "Missing ingredients"}),
        (SPLIT, {"chip": "Split this step"}),
        (answer("note", note="less salt next time"), {"said": "next time less salt"}),
    ])  # fmt: skip
    shown = wrap(cooking, scenario)
    assert (shown["kind"], shown["choice"], shown["left"]) == ("note", "fixed", 3)
    assert shown["text"] == "Fixed on Themi's side, and reported." and shown["can_decide"]
    assert (await tap(cooking, scenario, session.id, "wrap_note_ok")).ok
    shown = wrap(cooking, scenario)
    assert shown["choice"] == "change" and shown["said"] == "Split this step"
    (change,) = shown["changes"]
    assert change["what"] == "Step 3" and change["before"] == [STEP_3]
    assert change["after"] == [  # what's new in each, marked: the words, split, are the same
        [{"text": "Stir in the", "new": False}, {"text": "chickpeas.", "new": True}],
        [{"text": "Simmer", "new": True}, {"text": "10 minutes.", "new": False}]]  # fmt: skip
    tapped = await tap(cooking, scenario, session.id, "wrap_note_change")
    assert tapped.said == "Changed Chana Masala in Themi's copy."
    chana = cooking.recipes.get(session.recipe_id)
    assert chana is not None and [s.text for s in chana.steps][2:] == [
        "Stir in the chickpeas.", "Simmer 10 minutes."]  # fmt: skip
    shown = wrap(cooking, scenario)
    assert shown["choice"] == "note" and shown["text"] == "Keep this as a note on the recipe?"
    tapped = await tap(cooking, scenario, session.id, "wrap_note_keep")
    assert tapped.said == "Added the note to Chana Masala in Themi's copy."
    chana = cooking.recipes.get(session.recipe_id)
    assert chana is not None and chana.notes[-1] == "Note: Less salt next time (cooked Oct 21)"
    after = wrap(cooking, scenario)
    assert after is None or after["kind"] != "note"  # then CK6's offers, as before


async def test_not_now_and_undo(scenario: Scenario, cooking: Cooking) -> None:
    session = await finished(scenario, cooking, [(LINKS, {"chip": "Missing ingredients"}),
                                                 (SPLIT, {"chip": "Split this step"})])  # fmt: skip
    chana = cooking.recipes.get(session.recipe_id)
    assert chana is not None
    items = cooking.groceries.known(chana)
    assert 1 in cooking.links.links(chana, items)[2]  # left on step 3
    tapped = await tap(cooking, scenario, session.id, "wrap_note_undo")
    assert tapped.said == "Put back as it was shown."
    assert 1 not in cooking.links.links(chana, items)[2]
    assert (await tap(cooking, scenario, session.id, "wrap_note_later")).ok
    after = wrap(cooking, scenario)
    assert after is None or after["kind"] != "note"
    assert cooking.notes is not None
    assert [n.status for n in cooking.notes.for_session(session.id)] == ["undone", "waiting"]
    assert [s.text for s in chana.steps] == [s.text for s in cooking.recipes.get(chana.id).steps]  # type: ignore[union-attr]


async def test_only_the_owner_decides(scenario: Scenario, cooking: Cooking) -> None:
    session = await finished(scenario, cooking, [(SPLIT, {"chip": "Split this step"})],
                             in_group=True)  # fmt: skip
    state = cooking.state(scenario.member("Erin"))
    assert state["wrap"]["can_decide"] is True
    husband = scenario.member("Husband")  # a tap of theirs (with the screen's seq) does nothing
    tapped = await cooking.act_from_page(husband, session.id, "wrap_note_change", state["seq"],
                                         {"note": str(state["wrap"]["note"])})  # fmt: skip
    assert not tapped.ok
    assert cooking.notes is not None
    assert [n.status for n in cooking.notes.for_session(session.id)] == ["open"]


async def test_a_partners_note_says_whose(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, 3)
    scenario.app.db.execute("UPDATE cooking_sessions SET in_group = 1 WHERE id = ?", (session.id,))
    assert cooking.notes is not None
    left = cooking.notes.add(
        live(cooking, session.id), scenario.member("Husband"), said="two steps"
    )
    assert left is not None
    scenario.primary.queue_structured(SPLIT)
    await scenario.run_jobs()
    cooking.seen(scenario.member("Erin"))
    await cooking.advance(live(cooking, session.id), "finish")
    assert wrap(cooking, scenario)["who"] == "Husband"


async def test_a_note_still_sorting_waits(scenario: Scenario, cooking: Cooking) -> None:
    session = await at_step(scenario, cooking, 3)
    assert cooking.notes is not None
    cooking.notes.add(session, scenario.member("Erin"), said="two steps")  # not sorted yet
    cooking.seen(scenario.member("Erin"))
    await cooking.advance(live(cooking, session.id), "finish")
    shown = wrap(cooking, scenario)
    assert shown is None or shown["kind"] != "note"


async def test_in_chat_with_no_screen(scenario: Scenario, cooking: Cooking) -> None:
    await finished(scenario, cooking, [(SPLIT, {"chip": "Split this step"}),
                                       (LINKS, {"chip": "Missing ingredients"})],
                   screen=False)  # fmt: skip
    text = scenario.inbox("Erin")[-1]
    assert text.startswith('Your note: "Split this step"')
    assert f"Step 3 was:\n> {STEP_3}" in text and "Now:\n> Simmer 10 minutes." in text
    assert scenario.last_buttons("Erin") == ["Change the recipe", "Keep as a note", "Not now"]
    await scenario.tap("Erin", "Change the recipe")
    assert scenario.edits("Erin")[-1]["text"] == "Changed Chana Masala in Themi's copy."
    assert scenario.inbox("Erin")[-1].endswith("Fixed on Themi's side, and reported.")
    assert scenario.last_buttons("Erin") == ["OK", "Undo"]
    await scenario.tap("Erin", "OK")
    assert scenario.edits("Erin")[-1]["text"] == "OK."
