"""CK7: the cook screen's preferences (in Settings and A- A+ on the screen), and a lighter
screen after a low start: must-do look-ahead only, optional steps folded, [Skip the
checklist], and never a word about why. The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.fixtures.cookbook import ALFREDO as ALFREDO_BLOCKS
from tests.fixtures.cookbook import PANCAKES as PANCAKES_BLOCKS
from tests.fixtures.cookbook import load, recipe
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ENERGY_WORDS, lines
from themi.core import keys
from themi_home.cooking import Cooking, CookingPreferences

PANCAKE_ITEMS = [
    "white whole wheat flour", "all-purpose flour", "baking powder", "cinnamon", "kosher salt",
    "almond milk", "applesauce", "vanilla extract",
]  # fmt: skip
# A pasta night: water to boil (not a must) and an oven (a must), both in later steps.
PASTA = recipe(
    "Pasta Bake",
    [b[1] for b in ALFREDO_BLOCKS if b[0] == "P"][:9],
    [
        "Blend the cashews and all other ingredients until smooth.",
        "Taste, and add more lemon juice if you'd like.",
        "Bring a large pot of salted water to a boil and cook the pasta.",
        "Preheat the oven to 400°F, toss the pasta with the sauce and bake for 20 minutes.",
    ],
)


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services, [*PANCAKES_BLOCKS, *PASTA])
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def start(scenario: Scenario, cooking: Cooking, name: str, *, low: bool) -> int:
    names = PANCAKE_ITEMS if name == "Pancakes" else ["cashews", "water", "garlic", "miso",
                                                      "lemon juice", "salt", "nutmeg",
                                                      "onion powder", "black pepper"]  # fmt: skip
    scenario.primary.queue_structured(lines(names))
    found = next(r for r in cooking.recipes.all() if r.name == name)
    session = await cooking.start(scenario.member("Erin"), found)
    # The level as BD1a reads it at the start (`suggested_level`), set here directly.
    scenario.app.db.execute(
        "UPDATE cooking_sessions SET energy_at_start = ? WHERE id = ?",
        ("low" if low else "high", session.id),
    )
    return session.id


async def tap(cooking: Cooking, scenario: Scenario, session_id: int, action: str, **form: str):  # type: ignore[no-untyped-def]
    erin = scenario.member("Erin")
    return await cooking.act_from_page(erin, session_id, action, cooking.state(erin)["seq"], form)


def no_why(state: dict) -> None:
    text = json.dumps(state).lower()
    assert "energy" not in text and "lighter" not in text
    assert not any(f'"{word}"' in text for word in ENERGY_WORDS)


async def test_each_preference_is_in_the_state(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "Pasta Bake", low=False)
    assert cooking.state(erin)["view"] == {
        "text_size": 100,
        "theme": "auto",
        "steps_view": "one",
        "voice": False,
    }
    scenario.app.store.save_preferences(
        erin, erin.id, CookingPreferences,
        cooking_text_size=140, cooking_theme="kitchen", cooking_steps_view="all",
    )  # fmt: skip
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "next")
    state = cooking.state(erin)
    assert state["view"] == {
        "text_size": 140,
        "theme": "kitchen",
        "steps_view": "all",
        "voice": False,
    }
    assert [(s["label"], s["current"], s["done"]) for s in state["steps"]] == [
        ("1", False, True), ("2", True, False), ("3", False, False), ("4", False, False),
    ]  # fmt: skip
    husband = scenario.member("Husband")
    assert cooking.state(husband)["active"] is False  # each person's own, on their own screen


async def test_settings_and_a_minus_a_plus(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert 'id="cooking"' in page and 'name="cooking_theme"' in page
    await site.post("/settings", data={
        "csrf": csrf, "cooking_text_size": "120", "cooking_theme": "dark",
        "cooking_steps_view": "all", "cooking_units": "grams", "cooking_chime_volume": "40",
        "sprint_work_minutes": "25", "sprint_break_minutes": "5",
    })  # fmt: skip
    erin = scenario.member("Erin")
    prefs = scenario.app.store.preferences(erin.id, CookingPreferences)
    saved = (prefs.cooking_text_size, prefs.cooking_theme, prefs.cooking_steps_view,
             prefs.cooking_units, prefs.cooking_chime_volume)  # fmt: skip
    assert saved == (120, "dark", "all", "grams", 40)
    await start(scenario, cooking, "Pasta Bake", low=False)
    bigger = await site.post("/session/cook/prefs", data={"csrf": csrf, "text_size": "up"})
    assert bigger.json()["view"]["text_size"] == 140
    for _ in range(5):
        await site.post("/session/cook/prefs", data={"csrf": csrf, "text_size": "up"})
    capped = await site.post("/session/cook/prefs", data={"csrf": csrf, "text_size": "up"})
    assert capped.json()["view"]["text_size"] == 200
    smaller = await site.post("/session/cook/prefs", data={"csrf": csrf, "text_size": "down"})
    assert smaller.json()["view"]["text_size"] == 170
    page = (await site.get("/session")).text
    assert 'data-theme="dark"' in page and 'data-text-size="170"' in page
    bad = await site.post("/session/cook/prefs", data={"csrf": csrf, "theme": "neon"})
    assert bad.status_code == 400


async def test_a_low_start_leans_lighter(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "Pasta Bake", low=True)
    await tap(cooking, scenario, session_id, "skip")  # past "before anything else"
    gather = cooking.state(erin)
    assert gather["skip_checklist"] is True
    assert [b["label"] for b in gather["buttons"]] == ["Skip the checklist", "All here"]
    assert gather["strip"]["key"] == "preheat:3"  # the boil (not a must) isn't offered
    no_why(gather)
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "skip")  # [Skip the checklist]; no prep: step 1
    await tap(cooking, scenario, session_id, "next")
    step = cooking.state(erin)
    assert step["step"]["label"] == "2" and step["step"]["folded"] is True  # "if you'd like"
    no_why(step)


async def test_a_usual_start_shows_everything(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "Pasta Bake", low=False)
    await tap(cooking, scenario, session_id, "skip")
    gather = cooking.state(erin)
    assert gather["skip_checklist"] is False
    assert [b["label"] for b in gather["buttons"]] == ["All here"]
    assert gather["strip"]["key"] == "boil:2"  # the nearest, a must or not
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "next")
    assert cooking.state(erin)["step"]["folded"] is False
