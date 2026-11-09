"""CK4: look-ahead on the cook screen: what a later step needs started early, [Later]
bringing it back at the step before, and "while that simmers" only with a long timer. The
clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.fixtures.cookbook import ALFREDO, document, load, recipe
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home import cookbook as book
from themi_home.cooking import Cooking
from themi_home.cooking_ahead import look_ahead

# Alfredo Sauce baked over pasta: the fixture's lines and steps, then an oven step later on.
LINES = [*[b[1] for b in ALFREDO if b[0] == "P"][:9], "2 scallions, sliced"]
BAKED = recipe(
    "Alfredo Sauce",
    LINES,
    [
        "Drain and discard water from soaked cashews.",
        "Blend cashews and all other ingredients in a blender until creamy and smooth.",
        "Transfer the sauce to a saucepan and cook for 10 minutes, stirring often.",
        "Preheat the oven to 400°F. Pour the sauce over cooked pasta, top with the scallions "
        "and bake for 20 minutes.",
    ],
)
ITEMS = ["cashews", "water", "garlic", "miso", "lemon juice", "salt", "nutmeg", "onion powder",
         "black pepper", "scallions"]  # fmt: skip
NOT_SAID = re.compile(r"\byou should\b|\bdon'?t forget\b|\bneed to\b|\bmust\b|\bremember\b", re.I)


def items() -> dict:
    return {
        "lines": [
            {"n": n, "item": item, "quantity": "", "unit": "",
             "note": "sliced" if item == "scallions" else "", "optional": False, "staple": False}
            for n, item in enumerate(ITEMS, start=1)
        ]
    }  # fmt: skip


def parsed(blocks: list | None = None) -> list[Any]:
    """The cookbook's recipes as the parser reads them (the fields look_ahead uses)."""
    return book.parse(document(blocks)).recipes


def test_later_steps_on_the_fixture() -> None:
    found = {
        r.name: [(a.kind, a.part, a.text) for a in look_ahead(r)] for r in parsed() if look_ahead(r)
    }
    assert found["Lasagna"] == [("preheat", 0, "Step 1 wants the oven at 350°F. Start it now?")]
    assert found["Chana Masala"][0] == ("soak", 0, "Step 1 has a soak. Start it now?")
    assert "Alfredo Sauce" not in found  # "soaked cashews": the soak was done before
    (baked,) = parsed(BAKED)
    assert [(a.kind, a.part) for a in look_ahead(baked)] == [("preheat", 3)]


def test_the_offers_are_offers() -> None:
    every = [a.text for r in parsed() for a in look_ahead(r)]
    every += [a.text for a in look_ahead(parsed(BAKED)[0])]
    assert every and not [t for t in every if NOT_SAID.search(t)]
    assert all(t.endswith("?") for t in every)


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services, BAKED)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def start(scenario: Scenario, cooking: Cooking, ready: str) -> int:
    scenario.primary.queue_structured(items())
    (baked,) = cooking.recipes.all()
    session = await cooking.start(scenario.member("Erin"), baked)
    assert cooking.state(scenario.member("Erin"))["phase"] == "ready"
    await cooking.advance(session, ready)  # [Done] or [Skip] on "before anything else"
    return session.id


async def tap(cooking: Cooking, scenario: Scenario, session_id: int, action: str, **form: str):  # type: ignore[no-untyped-def]
    erin = scenario.member("Erin")
    return await cooking.act_from_page(erin, session_id, action, cooking.state(erin)["seq"], form)


async def test_done_in_the_ready_phase_isnt_offered_again(
    scenario: Scenario, cooking: Cooking
) -> None:
    await start(scenario, cooking, "next")  # [Done]: the soak and the preheat were seen to
    assert cooking.state(scenario.member("Erin"))["strip"] is None


async def test_later_comes_back_at_the_step_before(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "skip")
    offer = cooking.state(erin)["strip"]
    assert offer == {"kind": "offer", "key": "preheat:3",
                     "text": "Step 4 wants the oven at 400°F. Start it now?"}  # fmt: skip
    assert await tap(cooking, scenario, session_id, "ahead_later", key="preheat:3")
    assert cooking.state(erin)["strip"] is None  # gathering: hidden
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")  # no prep jobs: on to step 1
    assert cooking.state(erin)["step"]["label"] == "1" and cooking.state(erin)["strip"] is None
    await tap(cooking, scenario, session_id, "next")
    assert cooking.state(erin)["step"]["label"] == "2" and cooking.state(erin)["strip"] is None
    await tap(cooking, scenario, session_id, "next")
    assert cooking.state(erin)["step"]["label"] == "3"
    assert cooking.state(erin)["strip"]["key"] == "preheat:3"  # the step before: back
    assert await tap(cooking, scenario, session_id, "ahead_done", key="preheat:3")
    assert cooking.state(erin)["strip"] is None
    assert not await tap(cooking, scenario, session_id, "ahead_done", key="'; DROP")


async def test_the_simmer_line_only_with_a_long_timer(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    session_id = await start(scenario, cooking, "next")
    scenario.primary.queue_structured({"jobs": []})
    await tap(cooking, scenario, session_id, "next")
    await tap(cooking, scenario, session_id, "goto", to="3")
    await tap(cooking, scenario, session_id, "timer", minutes="5", step="3")
    assert cooking.state(erin)["strip"] is None  # 5 minutes: not long enough
    await tap(cooking, scenario, session_id, "timer", minutes="10", step="3")
    simmer = cooking.state(erin)["strip"]
    assert simmer == {"kind": "simmer", "text": "Step 4 uses the scallions, sliced."}
    assert not NOT_SAID.search(simmer["text"])
