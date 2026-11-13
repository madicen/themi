"""F42g: a list card (tasks, routines), drawn from its data. Golden SVGs in
`tests/golden/pictures/`."""

from __future__ import annotations

from datetime import date

from tests.unit.test_day_card import golden
from themi.drawing.render import to_png
from themi.standard.list_card import ListCardData, Row, Section, list_svg, list_text, view

TASKS = ListCardData(
    "Michael's tasks",
    date(2026, 10, 21),
    (
        Section("Overdue", (Row("Vacuum maintenance", "was due Fri 16 Oct"),)),
        Section("Today", (Row("Bring bins in", "shared"),)),
        Section("Any time", (Row("Add air to the Prius tires"),)),
    ),
)
ROUTINES = ListCardData(
    "Erin's routines",
    date(2026, 10, 21),
    (
        Section(
            "Evening",
            (
                Row("Cycle dishwasher", done=True),
                Row("Take meds", done=True),
                Row("Cover the birdcage", done=False),
            ),
            "5-8:30 pm",
        ),
    ),
)


def test_the_cards_match_their_golden_files() -> None:
    golden("tasks", list_svg(TASKS))
    golden("routines", list_svg(ROUTINES))
    golden("routines_dark", list_svg(ROUTINES, "dark"))
    assert to_png(list_svg(TASKS), 1080)[:4] == b"\x89PNG"


def test_a_long_list_is_counted_not_crammed() -> None:
    long = ListCardData(
        "Michael's tasks",
        date(2026, 10, 21),
        (Section("Any time", tuple(Row(f"Task {i}") for i in range(20))),),
    )
    shown = view(long)
    assert sum(len(s["rows"]) for s in shown["sections"]) == 14
    assert shown["more"] == "and 6 more"


def test_ticks_only_where_there_are_boxes() -> None:
    (section,) = view(ROUTINES)["sections"]
    assert [(r["box"], r["done"]) for r in section["rows"]] == [
        (True, True),
        (True, True),
        (True, False),
    ]
    assert not any(r["box"] for s in view(TASKS)["sections"] for r in s["rows"])


def test_the_words_when_theres_no_picture() -> None:
    assert list_text(ROUTINES).splitlines() == [
        "Erin's routines, Wed 21 Oct:",
        "Evening (5-8:30 pm):",
        "- ✓ Cycle dishwasher",
        "- ✓ Take meds",
        "- ☐ Cover the birdcage",
    ]
