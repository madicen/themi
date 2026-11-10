"""CK12: the tablet layout's state: the step strip and its titles (with the prep call, cached,
first words when there are none), the headline and the rest, the ingredient card's two
columns, the timer's length, and ticks that stay on the screen. The clock starts Wednesday
21 October 2026, 9 am."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from themi.ai.errors import PermanentError
from themi.core import keys
from themi_home.cooking import Cooking
from themi_home.cooking_links import digest
from themi_home.cooking_screen import meta, name_and_amount, split_headline
from themi_home.cooking_titles import checked, clean, fallback_title
from themi_home.recipes import Recipe


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


def alfredo(cooking: Cooking) -> Recipe:
    return next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")


async def to_steps(scenario: Scenario, cooking: Cooking, prep: dict) -> int:
    """Alfredo Sauce through ready and gather to its steps, the prep call answered by `prep`."""
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(scenario.member("Erin"), alfredo(cooking))
    scenario.primary.queue_structured(prep)
    for action in ("next", "next"):
        await cooking.advance(session, action)
    return session.id


@pytest.mark.parametrize(
    ("step", "title"),
    [
        ("Add the mushrooms to the hot olive oil. Cook for 7 minutes.", "Add the mushrooms"),
        ("Drain and discard water from soaked cashews.", "Drain and discard"),
        ("In a pot, bring water to a boil.", "In a pot"),
        ("Heat a large nonstick skillet or griddle over medium-low heat.", "Heat a large"),
        ("Serve.", "Serve"),
        ("whisk together the flours", "Whisk together"),
        ("Add the", "Add"),  # never ends on a word that reads as cut off
        ("Supercalifragilisticexpialidocious-ly stir it", "Supercalifragilisticexpi"),
    ],
)
def test_first_words_when_theres_no_title(step: str, title: str) -> None:
    assert fallback_title(step) == title
    assert len(fallback_title(step)) <= 24


def test_a_models_title_is_kept_only_when_its_short() -> None:
    assert clean(" sauté mushrooms. ") == "Sauté mushrooms"
    assert clean('"Boil pasta"') == "Boil pasta"
    assert clean("Make the sauce and then also toss") == ""  # too many words
    assert clean("Caramelise the onions slowly") == ""  # too long
    assert clean("") == "" and clean(None) == "" and clean(7) == ""


async def test_titles_come_with_the_prep_call(scenario: Scenario, cooking: Cooking) -> None:
    titles = ["Drain the cashews", "Blend until smooth", "Caramelise everything slowly"]
    await to_steps(scenario, cooking, {"jobs": [], "titles": titles})
    prep = scenario.primary.requests[-1]
    assert prep.schema is not None and "titles" in prep.schema["required"]
    assert '<data source="recipe Alfredo Sauce">' in prep.prompt  # the recipe is data
    assert "short title for each step" in prep.system
    state = cooking.state(scenario.member("Erin"))
    third = alfredo(cooking).steps[2].text
    assert state["strip_steps"] == [
        {"n": 1, "title": "Drain the cashews", "done": False, "current": True},
        {"n": 2, "title": "Blend until smooth", "done": False, "current": False},
        {"n": 3, "title": fallback_title(third), "done": False, "current": False},  # too long
    ]
    assert state["step"]["title"] == "Drain the cashews"
    assert state["next_title"] == "Blend until smooth"
    calls = len(scenario.primary.requests)
    await cooking.titles.ensure(scenario.member("Erin"), alfredo(cooking))
    assert len(scenario.primary.requests) == calls  # kept: never asked on its own
    assert cooking.titles.cached(alfredo(cooking)) == [s["title"] for s in state["strip_steps"]]


async def test_the_strip_marks_done_and_this_step(scenario: Scenario, cooking: Cooking) -> None:
    session_id = await to_steps(scenario, cooking, {"jobs": []})
    session = cooking.get(session_id)
    assert session is not None
    await cooking.advance(session, "goto:3")
    strip = cooking.state(scenario.member("Erin"))["strip_steps"]
    assert [(s["done"], s["current"]) for s in strip] == [
        (True, False),
        (True, False),
        (False, True),
    ]
    assert cooking.state(scenario.member("Erin"))["next_title"] == ""  # the last step


async def test_a_failed_prep_call_leaves_first_words(scenario: Scenario, cooking: Cooking) -> None:
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(scenario.member("Erin"), alfredo(cooking))
    scenario.primary.queue_error(PermanentError("no key"), op="structured")
    scenario.fallback.queue_error(PermanentError("no key"), op="structured")
    for action in ("next", "next"):
        await cooking.advance(session, action)
    recipe = alfredo(cooking)
    assert cooking.titles.cached(recipe) is None
    calls = len(scenario.primary.requests) + len(scenario.fallback.requests)
    await cooking.titles.ensure(scenario.member("Erin"), recipe)  # no prep kept: no call
    assert len(scenario.primary.requests) + len(scenario.fallback.requests) == calls
    titles = [s["title"] for s in cooking.state(scenario.member("Erin"))["strip_steps"]]
    assert titles == [fallback_title(s.text) for s in recipe.steps]


async def test_a_recipe_prepped_before_ck12_asks_once(scenario: Scenario, cooking: Cooking) -> None:
    recipe = alfredo(cooking)
    erin = scenario.member("Erin")
    scenario.app.db.execute(
        "INSERT INTO recipe_prep (recipe_id, hash, data, created_at) VALUES (?, ?, '[]', ?)",
        (recipe.id, digest(recipe), "2026-11-01T00:00:00+00:00"),
    )  # the prep read before titles came with it
    scenario.primary.queue_structured({"titles": ["Drain", "Blend", "Simmer"]})
    await cooking.titles.ensure(erin, recipe)
    asked = scenario.primary.requests[-1]
    assert asked.schema is not None and asked.schema["required"] == ["titles"]
    assert '<data source="recipe Alfredo Sauce">' in asked.prompt
    assert cooking.titles.titles(recipe) == ["Drain", "Blend", "Simmer"]
    calls = len(scenario.primary.requests)
    await cooking.titles.ensure(erin, recipe)
    assert len(scenario.primary.requests) == calls  # kept
    changed = replace(recipe, steps=(replace(recipe.steps[0], text="Blend all ingredients well"),))
    assert cooking.titles.cached(changed) is None  # new words: the next prep call brings them


async def test_a_failed_titles_call_keeps_first_words_and_doesnt_ask_again(
    scenario: Scenario, cooking: Cooking
) -> None:
    recipe = alfredo(cooking)
    erin = scenario.member("Erin")
    scenario.app.db.execute(
        "INSERT INTO recipe_prep (recipe_id, hash, data, created_at) VALUES (?, ?, '[]', ?)",
        (recipe.id, digest(recipe), "2026-11-01T00:00:00+00:00"),
    )
    scenario.primary.queue_error(PermanentError("no key"), op="structured")
    scenario.fallback.queue_error(PermanentError("no key"), op="structured")
    await cooking.titles.ensure(erin, recipe)
    assert cooking.titles.cached(recipe) == [fallback_title(s.text) for s in recipe.steps]
    calls = len(scenario.primary.requests) + len(scenario.fallback.requests)
    await cooking.titles.ensure(erin, recipe)
    assert len(scenario.primary.requests) + len(scenario.fallback.requests) == calls


def test_checked_fills_gaps_and_ignores_extras(cooking: Cooking) -> None:
    recipe = alfredo(cooking)
    out = checked(recipe, ["Drain", "", "Simmer", "Extra"])
    assert out == ["Drain", fallback_title(recipe.steps[1].text), "Simmer"]
    assert checked(recipe, "not a list") == [fallback_title(s.text) for s in recipe.steps]


def test_the_headline_is_the_first_sentence() -> None:
    assert split_headline("Add the mushrooms to the hot oil. Cook for 7 minutes. Stir.") == (
        "Add the mushrooms to the hot oil.", "Cook for 7 minutes. Stir.")  # fmt: skip
    assert split_headline("Serve warm.") == ("Serve warm.", "")
    long_first = "Stir " + "and stir " * 12 + "until thick. Then serve."
    assert split_headline(long_first) == (long_first, "")  # too long to be a headline


@pytest.mark.parametrize(
    ("line", "name", "amount"),
    [
        ("2 cloves garlic, minced", "Garlic, minced", "2 cloves"),
        ("1 Cup (130 g) cashews, soaked", "Cashews, soaked", "1 Cup (130 g)"),
        ("1 Tbsp + 1 tsp baking powder (20g)", "Baking powder (20g)", "1 Tbsp + 1 tsp"),
        ("1/2 cup of milk", "Milk", "1/2 cup"),
        ("Salt & black pepper, to taste", "Salt & black pepper, to taste", ""),
        ("Juice of 1 lemon", "Juice of 1 lemon", ""),
    ],
)
def test_an_ingredient_in_two_columns(line: str, name: str, amount: str) -> None:
    assert name_and_amount(line) == (name, amount)


def test_the_headers_quiet_line() -> None:
    base = {"scale_words": "", "scales": {"for": None}, "step_total": 6, "section": "Dinner"}
    assert meta(base) == "6 steps · Dinner"
    assert meta({**base, "scales": {"for": 2}}) == "for 2 · 6 steps · Dinner"
    assert (
        meta({**base, "scale_words": "double", "step_total": 1, "section": ""}) == "double · 1 step"
    )


async def test_a_timer_knows_its_length(scenario: Scenario, cooking: Cooking) -> None:
    session_id = await to_steps(scenario, cooking, {"jobs": []})
    session = cooking.get(session_id)
    assert session is not None and cooking.timers is not None
    erin = scenario.member("Erin")
    cooking.timers.start(erin, session, alfredo(cooking), "1", 8)
    (timer,) = cooking.state(erin)["timers"]
    assert (timer["seconds"], timer["of"], timer["text"]) == (480, "8:00", "8:00")
    cooking.timers.add(erin.id, timer["id"], 1)
    (timer,) = cooking.state(erin)["timers"]
    assert (timer["seconds"], timer["of"]) == (540, "9:00")


async def test_a_tick_shows_on_the_screen_only(
    scenario: Scenario, cooking: Cooking, site: httpx.AsyncClient
) -> None:
    """Michael, 2026-11-09: ticking an ingredient is for the screen; the chat card stays."""
    csrf = await sign_in(scenario, site, "Erin")
    session_id = await to_steps(scenario, cooking, {"jobs": []})
    session = cooking.get(session_id)
    assert session is not None
    await cooking.show(session)
    await scenario.app.outbox.flush()
    state = (await site.get("/session/state")).json()
    uses = state["amounts"]["uses"]
    assert uses and state["amounts"]["added"] == 0 and state["amounts"]["total"] == len(uses)
    edits = len(scenario.edits("Erin"))
    sent = len(scenario.inbox("Erin"))
    tapped = await site.post(
        f"/session/cook/{session_id}/act",
        headers={"X-Requested-With": "fetch"},
        data={"csrf": csrf, "action": "use", "n": str(uses[0]["n"]), "seq": str(state["seq"])},
    )
    assert tapped.status_code == 200
    await scenario.app.outbox.flush()
    after = (await site.get("/session/state")).json()
    assert after["amounts"]["added"] == 1 and after["amounts"]["uses"][0]["used"] is True
    assert after["seq"] > state["seq"]  # the other screens redraw
    assert len(scenario.edits("Erin")) == edits and len(scenario.inbox("Erin")) == sent
