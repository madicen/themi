"""CF6: notes left waiting show on the recipe's page, with the changes made from notes and
[Undo]; and on their step, "From last time", the next time the recipe is cooked. The clock
starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import httpx

from tests.fixtures.web import csrf_of, sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_wrap_notes import LINKS, SPLIT, STEP_3, finished, tap
from tests.unit.test_cook_wrap_notes import web_recipe as web_recipe  # a fixture
from tests.unit.test_cooking_note_sort import answer, at_step
from tests.unit.test_cooking_note_sort import cooking as cooking  # a fixture
from themi_home.cooking import Cooking

NOTE = answer("note", note="less salt next time")


async def left_for_later(scenario: Scenario, cooking: Cooking) -> int:
    session = await finished(
        scenario,
        cooking,
        [(SPLIT, {"chip": "Split this step"}), (NOTE, {"said": "next time less salt"})],
    )
    for _ in range(2):
        assert (await tap(cooking, scenario, session.id, "wrap_note_later")).ok
    return session.recipe_id


async def test_waiting_notes_on_the_recipe_page(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    recipe_id = await left_for_later(scenario, cooking)
    await sign_in(scenario, site, "Erin")
    page = (await site.get(f"/recipes/{recipe_id}")).text
    assert "Notes from cooking" in page
    assert "Erin, Oct 21, step 3: &ldquo;Split this step&rdquo;" in page
    assert f"<s>{STEP_3}</s>" in page and "<mark>" in page
    assert page.count(">Change the recipe</button>") == 1
    assert page.count(">Keep as a note</button>") == 2
    csrf = csrf_of(page)
    notes = cooking.notes.for_recipe(recipe_id)  # type: ignore[union-attr]
    moved = await site.post(f"/recipes/{recipe_id}/notes/{notes[0].id}",
                            data={"csrf": csrf, "action": "wrap_note_change"})  # fmt: skip
    assert moved.status_code == 303
    page = (await site.get(moved.headers["location"])).text
    assert "Changed Chana Masala in Themi" in page
    assert ">Change the recipe</button>" not in page
    assert page.count(">Keep as a note</button>") == 1
    assert "Changed from notes" in page and "Undo" in page
    chana = cooking.recipes.get(recipe_id)
    assert chana is not None and "Simmer 10 minutes." in [s.text for s in chana.steps]
    (change,) = scenario.app.db.query("SELECT id FROM cookbook_edits")
    undone = await site.post(f"/recipes/{recipe_id}/changes/{change['id']}/undo",
                             data={"csrf": csrf})  # fmt: skip
    page = (await site.get(undone.headers["location"])).text
    assert "Put Chana Masala back as it was" in page and "(undone)" in page
    chana = cooking.recipes.get(recipe_id)
    assert chana is not None and STEP_3 in [s.text for s in chana.steps]


async def test_only_the_cook_decides_on_the_page(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    recipe_id = await left_for_later(scenario, cooking)
    await sign_in(scenario, site, "Husband")
    page = (await site.get(f"/recipes/{recipe_id}")).text
    assert "Split this step" in page and "</button>" in page
    assert ">Change the recipe</button>" not in page  # seen, not decided
    note = cooking.notes.for_recipe(recipe_id)[0]  # type: ignore[union-attr]
    await site.post(f"/recipes/{recipe_id}/notes/{note.id}",
                    data={"csrf": csrf_of(page), "action": "wrap_note_change"})  # fmt: skip
    assert cooking.notes.get(note.id).status == "waiting"  # type: ignore[union-attr]


async def test_from_last_time_on_the_step(scenario: Scenario, cooking: Cooking) -> None:
    recipe_id = await left_for_later(scenario, cooking)
    erin = scenario.member("Erin")
    await at_step(scenario, cooking, 3)  # both were left on step 3
    assert cooking.state(erin)["last_time"] == ["Split this step", "next time less salt"]
    session = cooking.current(erin)
    assert session is not None
    await cooking.advance(session, "goto:1")
    assert cooking.state(erin)["last_time"] == []
    notes = cooking.notes  # decided: no longer shown
    assert notes is not None
    first = notes.for_recipe(recipe_id)[0]
    notes._set(first, status="kept")
    await cooking.advance(session, "goto:3")
    assert cooking.state(erin)["last_time"] == ["next time less salt"]


# ----- CF9: notes from the recipe page ----------------------------------------------------


def chana_id(cooking: Cooking) -> int:
    return next(r.id for r in cooking.recipes.all() if r.name == "Chana Masala")


async def test_a_note_on_the_page_is_offered_right_there(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    recipe_id = chana_id(cooking)
    await sign_in(scenario, site, "Erin")
    page = (await site.get(f"/recipes/{recipe_id}")).text
    assert page.count('<details class="note-sheet">') == 4 + 3  # each line, each step
    scenario.primary.queue_structured(SPLIT)
    saved = await site.post(
        f"/recipes/{recipe_id}/note",
        data={"csrf": csrf_of(page), "step": "2", "chip": "Split this step"},
    )
    page = (await site.get(saved.headers["location"])).text
    assert "Noted. It" in page and "s under Notes from cooking." in page
    assert ">Change the recipe</button>" in page
    (note,) = cooking.notes.for_recipe(recipe_id)  # type: ignore[union-attr]
    assert (note.how, note.session_id, note.step_label, note.status) == ("page", None, "3", "open")
    done = await site.post(f"/recipes/{recipe_id}/notes/{note.id}",
                           data={"csrf": csrf_of(page), "action": "wrap_note_change"})  # fmt: skip
    page = (await site.get(done.headers["location"])).text
    assert "Changed Chana Masala in Themi" in page
    chana = cooking.recipes.get(recipe_id)
    assert chana is not None and chana.steps[-1].text == "Simmer 10 minutes."


async def test_a_display_fix_from_the_page(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    recipe_id = chana_id(cooking)
    await sign_in(scenario, site, "Erin")
    page = (await site.get(f"/recipes/{recipe_id}")).text
    scenario.primary.queue_structured(LINKS)
    saved = await site.post(f"/recipes/{recipe_id}/note",
                            data={"csrf": csrf_of(page), "step": "1",
                                  "said": "the spices aren't shown"})  # fmt: skip
    page = (await site.get(saved.headers["location"])).text
    assert "Noted, and fixed on Themi" in page
    await at_step(scenario, cooking, 2)  # the next cook shows it
    uses = cooking.state(scenario.member("Erin"))["amounts"]["uses"]
    assert "1 tsp cumin" in [a["line"] for a in uses]


async def test_an_empty_page_note_isnt_saved(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    recipe_id = chana_id(cooking)
    await sign_in(scenario, site, "Erin")
    page = (await site.get(f"/recipes/{recipe_id}")).text
    for data in ({"step": "1"}, {"chip": "Wrong amount"}, {"step": "40", "said": "x"}):
        await site.post(f"/recipes/{recipe_id}/note", data={"csrf": csrf_of(page), **data})
    assert cooking.notes.for_recipe(recipe_id) == []  # type: ignore[union-attr]
