"""F62c: task steps can have sub-steps ("-- wipe the mirror"), as list items can."""

from __future__ import annotations

from themi.standard.tasks import _quoted, _step_levels, clean_steps, step_depth, top_steps


def test_sub_steps_keep_their_level() -> None:
    raw = ["Bathroom", "-- mirror", "---  spots", "  -- sink", "• Kitchen", "- Hall"]
    assert clean_steps(raw) == ["Bathroom", "-- mirror", "--- spots", "-- sink", "Kitchen", "Hall"]


def test_a_first_step_or_a_jump_goes_no_deeper_than_it_can() -> None:
    assert clean_steps(["-- x", "--- y", "---- z"]) == ["x", "-- y", "--- z"]
    assert clean_steps(["a", "--- b"]) == ["a", "-- b"]  # one under a, not two


def test_depth_and_top_steps() -> None:
    assert step_depth("-- wipe the mirror") == (1, "wipe the mirror")
    assert step_depth("Wipe the mirror") == (0, "Wipe the mirror")
    steps = ["Bathroom", "-- mirror", "--- spots", "-- sink", "Kitchen"]
    assert top_steps(steps) == [("Bathroom", ["mirror", "-- spots", "sink"]), ("Kitchen", [])]


def test_shown_indented_under_their_step() -> None:
    assert _quoted(["Bathroom", "-- mirror", "--- spots"]) == (
        "> - Bathroom\n>   -- mirror\n>     --- spots"
    )


def test_a_sub_step_has_its_steps_energy_tag() -> None:
    steps = ["(Low) Tidy", "-- bin", "(High) Deep clean", "-- grout", "Done"]
    assert _step_levels(steps) == ["low", "low", "high", "high", None]
