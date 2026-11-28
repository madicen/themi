"""F58c (Michael's bug #249, "on the wall, the frame goes off the bottom"): a column holds
only what fits, and counts the rest into its "+N more". `fitColumn` (wall-fit.js) is run
under node with made-up heights; the page wiring is checked in test_wall_look.py."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIT = Path(__file__).parents[2] / "src/themi_home/web/static/wall-fit.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node isn't installed")


def fit(
    sections: list[dict[str, object]], other: float, room: float, more: float, fold: float = 0
) -> list:
    script = (
        f"const f = require({json.dumps(str(FIT))});"
        f"const out = f.fitColumn({json.dumps(sections)}, {other}, {room}, {more}, {fold});"
        "console.log(JSON.stringify(out));"
    )
    run = subprocess.run(
        [str(NODE), "-e", script], capture_output=True, text=True, check=True, timeout=20
    )
    return json.loads(run.stdout)


def test_eight_items_with_room_for_five_show_four_and_say_four_more() -> None:
    assert fit([{"items": [1] * 8, "more": 0}], 0, 5, 1) == [{"shown": 4, "more": 4}]


def test_the_servers_own_more_is_added_to() -> None:
    assert fit([{"items": [1] * 8, "more": 2}], 0, 5, 1) == [{"shown": 4, "more": 6}]


def test_what_fits_is_left_alone() -> None:
    assert fit([{"items": [1, 1], "more": 0}], 1, 5, 1) == [{"shown": 2, "more": 0}]


def test_the_last_section_gives_way_first() -> None:
    routines = {"items": [1, 1], "more": 0}
    todos = {"items": [1, 1, 1], "more": 0}
    assert fit([routines, todos], 0, 4, 1) == [{"shown": 2, "more": 0}, {"shown": 1, "more": 2}]
    # with less room still, the earlier section gives way too once the last is empty
    assert fit([routines, todos], 0, 2, 1) == [{"shown": 0, "more": 2}, {"shown": 0, "more": 3}]


def test_bug_283_done_items_cut_fold_into_done_not_more() -> None:
    """F65c: four open to-dos and three just done in room for five: the cut done ones were
    counted as "+2 more", and "+2 more" opened a list without them."""
    family = {"items": [1] * 7, "more": 0, "done": [False] * 4 + [True] * 3, "folded": 3}
    assert fit([family], 0, 5, 1, 1) == [{"shown": 5, "more": 0, "folded": 5}]


def test_open_items_cut_still_say_more() -> None:
    family = {"items": [1] * 4, "more": 0, "done": [False] * 4, "folded": 0}
    assert fit([family], 0, 3, 1, 1) == [{"shown": 2, "more": 2, "folded": 0}]


def test_a_fold_that_appears_takes_its_room() -> None:
    family = {"items": [1] * 3, "more": 0, "done": [False, True, True], "folded": 0}
    assert fit([family], 0, 2, 1, 1) == [{"shown": 1, "more": 0, "folded": 2}]
