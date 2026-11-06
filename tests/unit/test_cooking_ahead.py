"""RC3a: what needs time before cooking starts."""

from __future__ import annotations

from datetime import UTC, datetime

from themi.core.cookbook import Line
from themi.core.cooking import Ahead, _names_line, _rule_jobs, ahead_of_time
from themi.core.recipe_groceries import read_line
from themi.core.recipes import Recipe


def recipe(lines: list[str], steps: list[str]) -> tuple[Recipe, list]:
    made = Recipe(
        1, "h.1", "doc", None, "Entrees", "", "Test", tuple(Line(t) for t in lines),
        tuple(Line(s) for s in steps), (), "", "recipe", (), None, None, "", False,
        datetime(2026, 11, 6, tzinfo=UTC),
    )  # fmt: skip
    return made, [read_line(line) for line in lines]


def test_a_soak_with_its_time() -> None:
    made, items = recipe(["1 Cup cashews, soaked in water for at least 10 minutes (130g)"], [])
    assert ahead_of_time(made, items) == [Ahead("soak the cashews (10 min)")]


def test_an_overnight_soak_is_one_item() -> None:
    made, items = recipe(
        ["2 Cups dried chickpeas, soaked overnight"],
        ["Soak the chickpeas in cold water overnight. Drain, rinse and set aside."],
    )
    assert ahead_of_time(made, items) == [Ahead("soak the dried chickpeas", overnight=True)]


def test_an_overnight_soak_only_in_the_steps() -> None:
    made, items = recipe(
        ["3/4 Cup split mung beans, rinsed"],
        ["Cover with lukewarm water and soak (covered) for at least 6 hours or overnight."],
    )
    assert ahead_of_time(made, items) == [Ahead("an overnight soak", overnight=True)]


def test_room_temperature_thawing_and_the_oven() -> None:
    made, items = recipe(
        ["½ Cup (120 ml) room temperature soy milk", "1 bag frozen peas, thawed"],
        ["Preheat the oven to 350 degrees", "Bake."],
    )
    assert ahead_of_time(made, items) == [
        Ahead("bring the soy milk to room temperature"),
        Ahead("thaw the frozen peas"),
        Ahead("preheat the oven to 350°F"),
    ]


def test_nothing_ahead() -> None:
    made, items = recipe(["1 tsp salt"], ["Blend ingredients together until smooth"])
    assert ahead_of_time(made, items) == []


def test_prep_jobs_by_rule_and_the_line_check() -> None:
    _, items = recipe(
        ["2 garlic cloves, peeled and left whole", "½ tsp salt", "1 onion, sliced"], []
    )
    assert _rule_jobs(items) == [
        {"text": "garlic cloves: peeled and left whole", "line": 1, "tool": "knife"},
        {"text": "onion: sliced", "line": 3, "tool": "knife"},
    ]
    assert _names_line("Garlic: peel, keep whole", "2 garlic cloves, peeled and left whole")
    assert not _names_line("Tofu: press it", "1 Cup cashews, soaked")


def test_a_long_step_splits_at_sentence_ends() -> None:
    from themi.core.cooking import step_parts

    long = "Stir the pot slowly. " * 30
    made, _ = recipe([], ["Short.", long.strip()])
    parts = step_parts(made)
    assert [p.label for p in parts][:3] == ["1", "2a", "2b"]
    assert all(len(p.text) <= 400 for p in parts)
    assert " ".join(p.text for p in parts[1:]) == long.strip()  # the words unchanged
