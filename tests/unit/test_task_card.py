"""F43b (Michael's idea #208): the tasks picture as cards with emoji, for one person or the
family, with chores too. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from tests.unit.test_day_card import golden
from tests.unit.test_list_card import ROUTINES
from themi.drawing.emoji import CHORE_ICON, ROUTINE_ICON, icon_emoji, item_emoji
from themi.drawing.render import to_png
from themi.standard.list_card import Row, Section, list_svg, list_text
from themi.standard.task_card import (
    Card,
    Group,
    Lane,
    TaskCardData,
    cards_svg,
    cards_text,
    view,
)
from themi_home.chore_card import ChartCardData, Chore, Column, chart_svg, chart_text

DAY = date(2026, 10, 21)
MINE = TaskCardData(
    "Michael's tasks",
    DAY,
    (
        Lane(
            "Michael",
            (
                Group("Overdue", (Card("Clean the bird cage", "was due Fri 16 Oct", "🦜", True),)),
                Group("Today", (Card("Bring bins in", "shared", "🗑️"),)),
                Group(
                    "Any time", (Card("Text Susan"), Card("Add air to the Prius tires", "", "🚗"))
                ),
            ),
        ),
    ),
)
FAMILY = TaskCardData(
    "Everyone's tasks",
    DAY,
    (
        Lane("Erin", (Group("Any time", (Card("Text Susan"), Card("Towel + clothes", "", "🧺"))),)),
        Lane(
            "Michael",
            (
                Group("Overdue", (Card("Split Merlin's cat box", "was due Sat 17 Oct", "🐈"),)),
                Group("Any time", (Card("Vacuum upstairs", "", "🧹"),)),
            ),
        ),
    ),
    (
        Card("Vacuum maintenance", "was due Fri 16 Oct", "🧹", True),
        Card("Bring bins in", "Wed", "🗑️"),
    ),
)
FAMILY_CHORES = replace(
    FAMILY,
    title="Everyone's chores and tasks",
    lanes=tuple(
        replace(
            lane,
            groups=(
                Group("On the chart", (Card("Feed the cats", "since Tue", "🐈"),)),
                *lane.groups,
            ),
        )
        for lane in FAMILY.lanes
    ),
)


def test_the_cards_match_their_golden_files() -> None:
    golden("tasks", cards_svg(MINE))
    golden("tasks_family", cards_svg(FAMILY))
    golden("tasks_family_chores", cards_svg(FAMILY_CHORES))
    golden("tasks_family_dark", cards_svg(FAMILY, "dark"))
    assert to_png(cards_svg(FAMILY_CHORES), 1080)[:4] == b"\x89PNG"


def test_one_person_is_two_across_with_no_lane_name() -> None:
    (lane,) = view(MINE)["lanes"]
    assert lane["name"] == ""
    first, second = lane["cards"][2], lane["cards"][3]  # the two "Any time" ones
    assert first["y"] == second["y"] and first["x"] < second["x"]
    assert lane["cards"][0]["important"] and lane["cards"][0]["emoji"] == "🦜"
    assert (
        lane["cards"][2]["emoji"] == "" and lane["cards"][2]["text_x"] < lane["cards"][3]["text_x"]
    )


def test_the_family_is_a_column_each_and_either_of_you_across_the_bottom() -> None:
    shown = view(FAMILY)
    assert [lane["name"] for lane in shown["lanes"]] == ["Erin", "Michael"]
    assert shown["lanes"][0]["x"] < shown["lanes"][1]["x"]
    assert shown["shared"]["name"] == "Either of you"
    lowest = max(c["y"] + c["height"] for lane in shown["lanes"] for c in lane["cards"])
    assert all(c["y"] > lowest for c in shown["shared"]["cards"])


def test_a_long_lane_is_counted_not_crammed() -> None:
    eight = tuple(Card(f"Task {i}") for i in range(8))
    two = TaskCardData(
        "Everyone's tasks", DAY, (Lane("Erin", (Group("Any time", eight),)), Lane("Michael", ()))
    )
    erin, michael = view(two)["lanes"]
    assert len(erin["cards"]) == 7 and erin["more"] == "+1 more"
    assert michael["empty"]
    alone = TaskCardData("Erin's tasks", DAY, (Lane("Erin", (Group("Any time", eight * 2),)),))
    (lane,) = view(alone)["lanes"]
    assert len(lane["cards"]) == 14 and lane["more"] == "+2 more"
    shared = replace(FAMILY, shared=tuple(Card(f"Shared {i}") for i in range(6)))
    assert len(view(shared)["shared"]["cards"]) == 4 and view(shared)["shared"]["more"] == "+2 more"


def test_the_words_when_theres_no_picture() -> None:
    assert cards_text(FAMILY).splitlines() == [
        "Everyone's tasks, Wed 21 Oct:",
        "Erin:",
        "Any time:",
        "- Text Susan",
        "- 🧺 Towel + clothes",
        "Michael:",
        "Overdue:",
        "- 🐈 Split Merlin's cat box (was due Sat 17 Oct)",
        "Any time:",
        "- 🧹 Vacuum upstairs",
        "Either of you:",
        "- 🧹 Vacuum maintenance (was due Fri 16 Oct)",
        "- 🗑️ Bring bins in (Wed)",
    ]
    assert cards_text(MINE).splitlines()[:3] == [
        "Michael's tasks, Wed 21 Oct:",
        "Overdue:",
        "- 🦜 Clean the bird cage (was due Fri 16 Oct)",
    ]


# ----- the emoji ----------------------------------------------------------------------------


def test_a_family_chosen_wall_icon_wins() -> None:
    assert item_emoji("Clean the bird cage", "czl_chores_emoji#_#paw_prints#_#🐾") == "🐾"


def test_themis_default_gives_way_to_a_better_fit() -> None:
    assert item_emoji("Clean the bird cage", CHORE_ICON) == "🦜"  # idea #25's rule
    assert item_emoji("Do the thing", CHORE_ICON) == "🧹"  # nothing fits better: it stands


def test_with_no_icon_the_title_picks_one_or_none() -> None:
    assert item_emoji("Call the vet") == "📞"
    assert item_emoji("Text Susan") == ""
    assert item_emoji("Take meds", ROUTINE_ICON) == "💊"
    assert item_emoji("Something", ROUTINE_ICON) == ""  # a wall picture, not an emoji


def test_icon_emoji_reads_the_walls_format() -> None:
    assert icon_emoji("czl_routine_emoji#_#pill#_#💊") == "💊"
    assert icon_emoji("routine_property_bed") == ""
    assert icon_emoji("") == ""


def test_the_chore_chart_and_routines_draw_emoji() -> None:
    chart = ChartCardData(
        DAY,
        (
            Column("Erin", (Chore("Feed the cats", "since Tue", False, "🐈"), Chore("Dishes"))),
            Column("Husband", (Chore("Bring bins in", "", True, "🗑️"),)),
        ),
    )
    golden("chores_emoji", chart_svg(chart))
    assert "- Erin: 🐈 Feed the cats (since Tue); Dishes" in chart_text(chart)
    routines = replace(
        ROUTINES,
        sections=tuple(
            Section(s.heading, tuple(replace(r, emoji=item_emoji(r.text)) for r in s.rows), s.note)
            for s in ROUTINES.sections
        ),
    )
    golden("routines_emoji", list_svg(routines))
    assert "- ✓ 🍽️ Cycle dishwasher" in list_text(routines).splitlines()
    assert Row("x").emoji == ""
