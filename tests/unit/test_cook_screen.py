"""CK1: the cook screen's state, in every phase, and `seq` on each move. The clock starts
Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fixtures.cookbook import load
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home.cooking import Cooking
from themi_home.recipes import Recipe

ENERGY_WORDS = ("energy", "capacity", "score", "low", "medium", "high")
ALFREDO = [
    "cashews", "water", "garlic", "miso", "lemon juice", "salt", "nutmeg", "onion powder",
    "black pepper",
]  # fmt: skip
RANCH = [
    "silken tofu", "water", "olive oil", "garlic", "onion powder", "salt", "apple cider vinegar",
    "nutritional yeast", "fresh herbs", "peppercorns",
]  # fmt: skip


def lines(names: list[str]) -> dict[str, Any]:
    return {
        "lines": [
            {"n": n, "item": item, "quantity": "", "unit": "", "note": "", "optional": False,
             "staple": False}
            for n, item in enumerate(names, start=1)
        ]
    }  # fmt: skip


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


def recipe(cooking: Cooking, name: str) -> Recipe:
    return next(r for r in cooking.recipes.all() if r.name == name)


def no_energy(state: dict[str, Any]) -> None:
    text = json.dumps(state).lower()
    assert "energy" not in text
    assert not any(f'"{word}"' in text for word in ENERGY_WORDS)


async def test_the_state_in_every_phase(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    assert cooking.state(erin) == {"active": False, "now": "2026-10-21T16:00:00+00:00"}
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(erin, recipe(cooking, "Alfredo Sauce"), scale=2.0,
                                  scale_said="double")  # fmt: skip
    ready = cooking.state(erin)
    assert (ready["kind"], ready["phase"], ready["recipe"]) == ("cooking", "ready", "Alfredo Sauce")
    assert ready["heading"] == "Alfredo Sauce, a double batch of"
    assert ready["ahead"] == [
        {"n": 0, "text": "soak the cashews (10 min)", "overnight": False, "done": False}
    ]
    assert [b["label"] for b in ready["buttons"]] == ["Done", "Skip"]
    no_energy(ready)

    await cooking.advance(session, "next")
    gather = cooking.state(erin)
    assert gather["phase"] == "gather" and gather["seq"] > ready["seq"]
    assert gather["gather"][0] == {
        "n": 0, "line": "2 Cups cashews, soaked in water for at least 10 minutes (260g)",
        "group": "", "ticked": False,
    }  # fmt: skip
    assert [b["label"] for b in gather["buttons"]] == ["All here"]
    no_energy(gather)

    scenario.primary.queue_structured(
        {"jobs": [{"text": "Garlic: peel, keep whole", "line": 3, "tool": "knife"}]}
    )
    await cooking.advance(session, "next")
    prep = cooking.state(erin)
    assert prep["prep"] == [{"n": 0, "text": "Garlic: peel, keep whole", "done": False}]
    assert [b["label"] for b in prep["buttons"]] == ["Prep done", "Skip prep"]
    no_energy(prep)

    await cooking.advance(session, "next")
    first = cooking.state(erin)
    assert first["step"] == {
        "index": 0, "label": "1", "text": "Drain and discard water from soaked cashews.",
        "group": "", "words": "Step 1 of 3", "first": True, "last": False,
    }  # fmt: skip
    assert first["peek"].startswith("Next, step 2: Blend cashews and all other ingredients")
    assert [b["label"] for b in first["buttons"]] == ["Next"]
    await cooking.advance(session, "goto:3")
    last = cooking.state(erin)
    assert last["step"]["words"] == "Step 3 of 3" and last["peek"] == ""
    assert last["offers"] == [{"label": "Timer 10 min", "minutes": 10.0, "step": "3"}]
    assert [b["label"] for b in last["buttons"]] == ["Back", "All done"]
    no_energy(last)
    assert scenario.app.db.scalar(
        "SELECT energy_at_start IS NOT NULL OR hour_of_week IS NOT NULL FROM cooking_sessions"
    )  # kept at start, as BD1a keeps it, and never shown


async def test_seq_bumps_on_every_move(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    scenario.primary.queue_structured(lines(RANCH))
    session = await cooking.start(erin, recipe(cooking, "Silken Tofu Ranch Dressing"))
    seqs = [cooking.state(erin)["seq"]]
    await cooking.act_from_page(erin, session.id, "tick", seqs[-1], {"list": "gather", "n": "0"})
    seqs.append(cooking.state(erin)["seq"])
    assert cooking.state(erin)["gather"][0]["ticked"] is True
    await cooking.act_from_page(erin, session.id, "untick", seqs[-1], {"list": "gather", "n": "0"})
    seqs.append(cooking.state(erin)["seq"])
    assert cooking.state(erin)["gather"][0]["ticked"] is False
    scenario.primary.queue_structured({"jobs": []})
    await scenario.say("Erin", "next")  # typed in chat: the same session moves
    seqs.append(cooking.state(erin)["seq"])
    assert seqs == sorted(set(seqs)) and len(seqs) == 4
    assert cooking.state(erin)["phase"] == "cook"


async def test_an_old_seq_or_someone_else_does_nothing(
    scenario: Scenario, cooking: Cooking
) -> None:
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    scenario.primary.queue_structured(lines(RANCH))
    session = await cooking.start(erin, recipe(cooking, "Silken Tofu Ranch Dressing"))
    seq = cooking.state(erin)["seq"]
    assert not await cooking.act_from_page(erin, session.id, "next", seq - 1, {})
    assert not await cooking.act_from_page(husband, session.id, "next", seq, {})
    assert cooking.state(erin)["phase"] == "gather"
    assert cooking.state(husband) == {"active": False, "now": "2026-10-21T16:00:00+00:00"}
    assert not await cooking.act_from_page(erin, session.id, "back", seq, {})  # not before steps


async def test_a_group_session_is_open_to_either_partner(
    scenario: Scenario, cooking: Cooking
) -> None:
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    scenario.primary.queue_structured(lines(RANCH))
    session = await cooking.start(
        erin, recipe(cooking, "Silken Tofu Ranch Dressing"), in_group=True
    )
    state = cooking.state(husband)
    assert state["id"] == session.id and state["group"] is True
    scenario.primary.queue_structured({"jobs": []})
    assert await cooking.act_from_page(husband, session.id, "next", state["seq"], {})
    assert cooking.state(erin)["phase"] == "cook"


async def test_a_timer_chip_starts_one(scenario: Scenario, cooking: Cooking) -> None:
    erin = scenario.member("Erin")
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(erin, recipe(cooking, "Alfredo Sauce"))
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await cooking.advance(session, action)
    await cooking.advance(session, "goto:3")
    state = cooking.state(erin)
    await cooking.act_from_page(erin, session.id, "timer", state["seq"],
                                {"minutes": "10", "step": "3"})  # fmt: skip
    (timer,) = cooking.state(erin)["timers"]
    assert timer["ends_at"] == "2026-10-21T16:10:00+00:00" and timer["fired"] is False
    assert timer["label"] == "Step 3" and timer["text"] == "10:00"
