# ruff: noqa: RUF001  (the doc's own quote marks, kept as written)
"""CF4: a change from a cooking note, written into the cookbook doc on a yes: steps split
and numbered as the entry numbers them, lines kept in their groups, a note before
"Source:", the doc read again, and undo. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tests.fakes.gdocs_api import FakeGdocs
from tests.fixtures.cookbook import COOKBOOK_ID
from tests.scenarios.harness import Scenario
from tests.scenarios.test_cookbook import choose
from tests.scenarios.test_cookbook import linked as linked  # a fixture
from themi.core import keys
from themi_home.cookbook_edit import Rejected
from themi_home.cooking import Cooking
from themi_home.cooking_links import digest
from themi_home.cooking_notes import Note
from themi_home.recipes import Recipe


@pytest.fixture
async def ready(scenario: Scenario, linked: FakeGdocs, site: httpx.AsyncClient) -> FakeGdocs:
    await choose(scenario, site)
    return linked


def cooking(scenario: Scenario) -> Cooking:
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None and found.notes is not None and found.notes.edits is not None
    return found


def named(scenario: Scenario, name: str, n: int = 0) -> Recipe:
    return [r for r in cooking(scenario).recipes.all() if r.name == name][n]


def a_note(scenario: Scenario, recipe: Recipe, ops: list[dict[str, Any]],
           kind: str = "change") -> Note:  # fmt: skip
    full = [{"op": "", "old": "", "olds": [], "new": [], "after": "", "group": "", **o}
            for o in ops]  # fmt: skip
    note_id = scenario.app.db.execute(
        "INSERT INTO cooking_notes (recipe_id, member_id, how, recipe_digest, created_at, kind, "
        "proposal, status, summary) VALUES (?, ?, 'page', ?, '2026-10-21T09:00:00+00:00', ?, ?, "
        "'open', 'as noted')",
        (recipe.id, scenario.member("Erin").id, digest(recipe), kind, json.dumps({"ops": full})),
    )  # fmt: skip
    note = cooking(scenario).notes.get(note_id)  # type: ignore[union-attr]
    assert note is not None
    return note


async def approve(scenario: Scenario, note: Note) -> str:
    edits = cooking(scenario).notes.edits  # type: ignore[union-attr]
    outcome = await edits.stage(scenario.member("Erin"), note)  # type: ignore[union-attr]
    assert outcome.action.status == "done", outcome.message
    return outcome.message


def entry(fake: FakeGdocs, name: str, n: int = 0) -> list[tuple[str, str]]:
    paragraphs = fake.paragraphs(COOKBOOK_ID)
    starts = [k for k, p in enumerate(paragraphs) if p == (name, "HEADING_4")]
    start = starts[n]
    end = paragraphs.index(("-----", "NORMAL_TEXT"), start)
    return paragraphs[start : end + 1]


ALFREDO_STEP_3 = (
    "Transfer the sauce to a medium-sized saucepan, turn the heat to the lowest possible setting "
    "and cook for 10 minutes, stirring often so the sauce doesn’t stick to the bottom of the pan."
)


async def test_a_split_step_goes_into_the_doc(scenario: Scenario, ready: FakeGdocs) -> None:
    alfredo = named(scenario, "Alfredo Sauce")
    note = a_note(
        scenario,
        alfredo,
        [
            {
                "op": "split_step",
                "old": ALFREDO_STEP_3,
                "new": [
                    "Transfer the sauce to a medium-sized saucepan.",
                    "Turn the heat to the lowest setting and cook for 10 minutes, stirring often.",
                ],
            }
        ],
    )
    said = await approve(scenario, note)
    assert said == "Changed Alfredo Sauce in the cookbook."
    paragraphs = entry(ready, "Alfredo Sauce")
    at = paragraphs.index(("Transfer the sauce to a medium-sized saucepan.", "NORMAL_TEXT"))
    assert paragraphs[at + 1] == (
        "Turn the heat to the lowest setting and cook for 10 minutes, stirring often.",
        "NORMAL_TEXT")  # fmt: skip
    assert paragraphs[at + 2][0].startswith("Recipe Notes:")
    assert (ALFREDO_STEP_3, "NORMAL_TEXT") not in paragraphs
    again = cooking(scenario).recipes.get(alfredo.id)  # read from the doc again
    assert again is not None and len(again.steps) == 4
    done = cooking(scenario).notes.get(note.id)  # type: ignore[union-attr]
    assert done is not None and done.status == "done" and done.edit_id is not None
    with pytest.raises(Rejected):  # made already: Themi's copy has the new words now
        await cooking(scenario).notes.edits.stage(scenario.member("Erin"), done)  # type: ignore[union-attr]


async def test_a_numbered_entry_is_numbered_again(scenario: Scenario, ready: FakeGdocs) -> None:
    parmesan = named(scenario, "Simple Parmesan")
    first = parmesan.steps[0].text
    note = a_note(
        scenario,
        parmesan,
        [
            {
                "op": "split_step",
                "old": first,
                "new": [
                    "Combine the melted coconut oil, water, extra-virgin olive oil, salt, and "
                    "soy lecithin.",
                    "Using a hand blender, blend on high for about 2 minutes, until emulsified.",
                ],
            }
        ],
    )
    await approve(scenario, note)
    steps = [t for t, _ in entry(ready, "Simple Parmesan") if t[:1].isdigit() and "\\." in t[:4]]
    assert [s[:3] for s in steps] == ["1\\.", "2\\.", "3\\.", "4\\."]
    assert steps[1].startswith("2\\. Using a hand blender") and steps[3].startswith("4\\. Store")
    again = cooking(scenario).recipes.get(parmesan.id)
    assert again is not None and again.steps[3].text.startswith("Store in a tupperware")


async def test_lines_stay_in_their_groups(scenario: Scenario, ready: FakeGdocs) -> None:
    parmesan = named(scenario, "Simple Parmesan")
    note = a_note(scenario, parmesan, [
        {"op": "replace_line", "old": "35g water", "new": ["40g water"]},
        {"op": "insert_line", "new": ["1g garlic powder"], "group": "Dry"}])  # fmt: skip
    await approve(scenario, note)
    paragraphs = entry(ready, "Simple Parmesan")
    wet, dry = paragraphs.index(("*Wet*", "HEADING_6")), paragraphs.index(("*Dry*", "HEADING_6"))
    assert paragraphs.index(("40g water", "NORMAL_TEXT")) in range(wet, dry)
    assert paragraphs.index(("1g garlic powder", "NORMAL_TEXT")) > dry
    again = cooking(scenario).recipes.get(parmesan.id)
    assert again is not None
    assert ("1g garlic powder", "Dry") in [(i.text, i.group) for i in again.ingredients]


async def test_a_note_goes_before_the_source(scenario: Scenario, ready: FakeGdocs) -> None:
    alfredo = named(scenario, "Alfredo Sauce")
    note = a_note(scenario, alfredo, [{"op": "add_note", "new": [
        "Note: Less salt next time (cooked Oct 21)"]}], kind="note")  # fmt: skip
    assert await approve(scenario, note) == "Added the note to Alfredo Sauce in the cookbook."
    paragraphs = [t for t, _ in entry(ready, "Alfredo Sauce")]
    at = paragraphs.index("Note: Less salt next time (cooked Oct 21)")
    assert paragraphs[at + 1].startswith("Source:") and paragraphs[at - 1].startswith(
        "Recipe Notes"
    )
    again = cooking(scenario).recipes.get(alfredo.id)
    assert again is not None and "Note: Less salt next time (cooked Oct 21)" in again.notes
    assert len(again.steps) == 3
    kept = cooking(scenario).notes.get(note.id)  # type: ignore[union-attr]
    assert kept is not None and kept.status == "kept"


async def test_the_search_stays_in_its_entry(scenario: Scenario, ready: FakeGdocs) -> None:
    """Biryani's second "Ingredients" heading is over its steps; and of the two recipes
    named "Chocolate Peanut Butter Bars", only the one noted changes."""
    biryani = named(scenario, "Biryani")
    old = "Add in the sliced onions and fry till the onions are soft."
    note = a_note(
        scenario,
        biryani,
        [{"op": "replace_step", "old": old, "new": ["Add the sliced onions and fry until soft."]}],
    )
    await approve(scenario, note)
    assert ("Add the sliced onions and fry until soft.", "NORMAL_TEXT") in entry(ready, "Biryani")
    bars = named(scenario, "Chocolate Peanut Butter Bars", 1)
    note = a_note(scenario, bars, [{"op": "replace_line", "old": "1/2 Cup peanut butter",
                                    "new": ["3/4 Cup peanut butter"]}])  # fmt: skip
    await approve(scenario, note)
    assert ("1 Cup peanut butter", "NORMAL_TEXT") in entry(ready, "Chocolate Peanut Butter Bars")
    assert ("3/4 Cup peanut butter", "NORMAL_TEXT") in entry(
        ready, "Chocolate Peanut Butter Bars", 1)  # fmt: skip


async def test_words_changed_in_the_doc_are_left_alone(
    scenario: Scenario, ready: FakeGdocs
) -> None:
    alfredo = named(scenario, "Alfredo Sauce")
    note = a_note(scenario, alfredo, [{"op": "replace_step", "old": ALFREDO_STEP_3,
                                       "new": ["Simmer 10 minutes."]}])  # fmt: skip

    def typed(blocks: list[Any]) -> None:  # someone rewrote step 3 in the doc
        for block in blocks:
            if getattr(block, "text", "") == ALFREDO_STEP_3:
                block.text = "Simmer gently for 10 minutes, stirring."

    ready.edit(COOKBOOK_ID, typed)
    before = ready.paragraphs(COOKBOOK_ID)
    edits = cooking(scenario).notes.edits  # type: ignore[union-attr]
    outcome = await edits.stage(scenario.member("Erin"), note)  # type: ignore[union-attr]
    assert (
        outcome.message
        == "Alfredo Sauce changed in the cookbook since the note, so nothing was written."
    )
    assert ready.paragraphs(COOKBOOK_ID) == before
    stale = cooking(scenario).notes.get(note.id)  # type: ignore[union-attr]
    assert stale is not None and stale.status == "stale" and stale.edit_id is None


async def test_an_edit_in_between_is_read_again(scenario: Scenario, ready: FakeGdocs) -> None:
    alfredo = named(scenario, "Alfredo Sauce")
    note = a_note(scenario, alfredo, [{"op": "replace_step", "old": ALFREDO_STEP_3,
                                       "new": ["Simmer 10 minutes."]}])  # fmt: skip
    ready.edits_before_write = 1
    await approve(scenario, note)
    assert ("Simmer 10 minutes.", "NORMAL_TEXT") in entry(ready, "Alfredo Sauce")


async def test_undo_puts_it_back(scenario: Scenario, ready: FakeGdocs) -> None:
    alfredo = named(scenario, "Alfredo Sauce")
    before = entry(ready, "Alfredo Sauce")
    note = a_note(
        scenario,
        alfredo,
        [
            {
                "op": "split_step",
                "old": ALFREDO_STEP_3,
                "new": ["Move to a saucepan.", "Simmer 10 minutes."],
            }
        ],
    )
    await approve(scenario, note)
    done = cooking(scenario).notes.get(note.id)  # type: ignore[union-attr]
    assert done is not None and done.edit_id is not None
    edits = cooking(scenario).notes.edits  # type: ignore[union-attr]
    outcome = await edits.stage_undo(scenario.member("Erin"), done.edit_id)  # type: ignore[union-attr]
    assert outcome.message == "Put Alfredo Sauce back as it was in the cookbook."
    assert entry(ready, "Alfredo Sauce") == before
    undone = cooking(scenario).notes.get(note.id)  # type: ignore[union-attr]
    assert undone is not None and undone.status == "undone"


async def test_undo_refused_once_the_words_changed(scenario: Scenario, ready: FakeGdocs) -> None:
    alfredo = named(scenario, "Alfredo Sauce")
    note = a_note(scenario, alfredo, [{"op": "replace_step", "old": ALFREDO_STEP_3,
                                       "new": ["Simmer 10 minutes."]}])  # fmt: skip
    await approve(scenario, note)

    def typed(blocks: list[Any]) -> None:
        for block in blocks:
            if getattr(block, "text", "") == "Simmer 10 minutes.":
                block.text = "Simmer 12 minutes."

    ready.edit(COOKBOOK_ID, typed)
    before = ready.paragraphs(COOKBOOK_ID)
    done = cooking(scenario).notes.get(note.id)  # type: ignore[union-attr]
    assert done is not None and done.edit_id is not None
    edits = cooking(scenario).notes.edits  # type: ignore[union-attr]
    outcome = await edits.stage_undo(scenario.member("Erin"), done.edit_id)  # type: ignore[union-attr]
    assert outcome.message == "Alfredo Sauce changed in the cookbook since, so it wasn't put back."
    assert ready.paragraphs(COOKBOOK_ID) == before


async def test_a_web_recipe_changes_in_themis_copy(scenario: Scenario) -> None:
    from tests.fixtures.cookbook import load

    load(scenario.app.services)
    scenario.app.db.execute("UPDATE recipes SET source = 'web' WHERE name = 'Alfredo Sauce'")
    alfredo = named(scenario, "Alfredo Sauce")
    note = a_note(scenario, alfredo, [{"op": "replace_step", "old": ALFREDO_STEP_3,
                                       "new": ["Simmer 10 minutes."]}])  # fmt: skip
    await approve(scenario, note)
    again = cooking(scenario).recipes.get(alfredo.id)
    assert again is not None and again.steps[2].text == "Simmer 10 minutes."
