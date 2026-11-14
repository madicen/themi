"""GW6: the family's own weights guide, checked: a line that can't be right, or more than
25% off what two web sources agree on, is asked about, never changed. The Pi's guide says
"1 Tbsp Water: 5g"; a tablespoon of water is about 15 g. The clock starts Wednesday
21 October 2026, 9 am."""

from __future__ import annotations

import pytest

from tests.fakes.search import FakeSearch
from tests.scenarios.harness import Scenario
from themi.core import keys
from themi_home.gram_weights import GramWeights

WATER = "1mL Water / 1 Tbsp Water: Weight in Grams 1g / 5g"


@pytest.fixture
def weights(scenario: Scenario) -> GramWeights:
    guides = scenario.app.services.maybe(keys.guides)
    assert guides is not None
    text = "Weights of Common Ingredients\n" + WATER + "\n1 Cup Flour: Weight in Grams 120g"
    guides.save(scenario.member("Erin"), "Weights of Common Ingredients", text, personal=False)
    found = scenario.app.services.maybe(GramWeights)
    assert found is not None
    return found


def outbox(scenario: Scenario, name: str) -> list[str]:
    rows = scenario.app.db.query(
        "SELECT text FROM outbox WHERE member_id = ? ORDER BY id", (scenario.member(name).id,)
    )
    return [r["text"] for r in rows]


def water_results(fake_search: FakeSearch) -> None:
    fake_search.result(
        "water 1 tablespoon",
        "Water",
        "https://a.example",
        "1 tablespoon of water weighs 14.8 grams",
    )
    fake_search.result("water 1 tablespoon", "Kitchen", "https://b.example",
                       "Water: 1 Tbsp = 15 g")  # fmt: skip


def answers(scenario: Scenario) -> None:
    """The model's reading, for the three checks the run makes, in the guide's order: 1 mL
    water (nothing), 1 Tbsp water (two sources), 1 cup flour (nothing)."""
    scenario.primary.queue_structured({"weights": [
        {"source": 1, "grams": 14.8, "per_amount": 1, "per_unit": "tbsp",
         "quote": "1 tablespoon of water weighs 14.8 grams"},
        {"source": 2, "grams": 15, "per_amount": 1, "per_unit": "tbsp",
         "quote": "water: 1 tbsp = 15 g"},
    ]})  # fmt: skip


async def test_the_pis_water_line_is_asked_about_once(
    scenario: Scenario, weights: GramWeights, fake_search: FakeSearch
) -> None:
    water_results(fake_search)
    answers(scenario)
    await weights.check_guide()
    assert outbox(scenario, "Erin") == [
        "Your guide says 1 Tbsp water is 5 g; it's usually about 15 g. Change it?"
    ]
    guide = weights.guide()
    assert guide is not None and WATER in guide.text  # not changed
    searches = len(fake_search.queries())
    await weights.check_guide()
    assert len(fake_search.queries()) == searches  # each line once
    assert len(outbox(scenario, "Erin")) == 1


async def test_change(scenario: Scenario, weights: GramWeights, fake_search: FakeSearch) -> None:
    water_results(fake_search)
    answers(scenario)
    await weights.check_guide()
    await scenario.app.outbox.flush()
    await scenario.advance(hours=3)  # a low line waits for a good moment
    await scenario.tap("Erin", "Change")
    assert weights.book().grams("water", 1, "tbsp") == 15


async def test_keep_is_remembered(
    scenario: Scenario, weights: GramWeights, fake_search: FakeSearch
) -> None:
    water_results(fake_search)
    answers(scenario)
    await weights.check_guide()
    await scenario.advance(hours=3)
    await scenario.tap("Erin", "Keep")
    assert weights.book().grams("water", 1, "tbsp") == 5
    state = scenario.app.db.scalar(
        "SELECT state FROM gram_weights_checked WHERE line = ? AND part = 1", (WATER,)
    )
    assert state == "kept"


async def test_a_fine_line_isnt_asked_about(
    scenario: Scenario, weights: GramWeights, fake_search: FakeSearch
) -> None:
    fake_search.result("flour 1 cup", "Flour", "https://a.example", "Flour: 1 cup = 120 grams")
    fake_search.result("flour 1 cup", "Baking", "https://b.example", "1 cup of flour is 125g")
    scenario.primary.queue_structured({"weights": [
        {"source": 1, "grams": 120, "per_amount": 1, "per_unit": "cup",
         "quote": "flour: 1 cup = 120 grams"},
        {"source": 2, "grams": 125, "per_amount": 1, "per_unit": "cup",
         "quote": "1 cup of flour is 125g"},
    ]})  # fmt: skip
    await weights.check_guide()
    assert outbox(scenario, "Erin") == []
    state = scenario.app.db.scalar(
        "SELECT state FROM gram_weights_checked WHERE line = ?",
        ("1 Cup Flour: Weight in Grams 120g",),
    )
    assert state == "fine"


async def test_a_line_that_cant_be_right_needs_no_search(
    scenario: Scenario, weights: GramWeights
) -> None:
    guides = scenario.app.services.maybe(keys.guides)
    guide = weights.guide()
    assert guides is not None and guide is not None
    guides.append_line(guide.id, "1 tsp Cinnamon: Weight in Grams 30g")
    await weights.check_guide()
    assert outbox(scenario, "Erin") == [
        "Your guide says 1 tsp cinnamon is 30 g, which can't be right (maybe 3 g?). Change it?"
    ]


async def test_an_edited_line_is_checked_again(
    scenario: Scenario, weights: GramWeights, fake_search: FakeSearch
) -> None:
    water_results(fake_search)
    answers(scenario)
    await weights.check_guide()
    await weights.correct(scenario.member("Erin"), "water", 1, "tbsp", 15)  # Themi's now
    guides = scenario.app.services.maybe(keys.guides)
    guide = weights.guide()
    assert guides is not None and guide is not None
    guides.append_line(guide.id, "1 Cup Sugar: Weight in Grams 200g")  # a new family line
    before = len(fake_search.queries())
    scenario.primary.queue_structured({"weights": []})
    await weights.check_guide()
    assert any("sugar" in q for q in fake_search.queries()[before:])
