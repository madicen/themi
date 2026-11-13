"""DC9: the chore chart, drawn from its data. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from datetime import date

from tests.unit.test_day_card import golden
from themi.drawing.render import to_png
from themi_home.chore_card import (
    EMPTY_TEXT,
    ChartCardData,
    Chore,
    Column,
    chart_svg,
    chart_text,
    view,
)

CHART = ChartCardData(
    date(2026, 10, 22),
    (
        Column("Erin", (Chore("Take the medicine", "", True), Chore("Dishes", "since Tue"))),
        Column(
            "Husband",
            tuple(Chore(f"Chore number {i} with a long name to wrap") for i in range(9)),
        ),
    ),
)


def test_the_chart_matches_its_golden_files() -> None:
    golden("chores", chart_svg(CHART))
    golden("chores_dark", chart_svg(CHART, "dark"))
    assert to_png(chart_svg(CHART), 1080)[:4] == b"\x89PNG"


def test_a_long_column_is_counted_not_crammed() -> None:
    erin, husband = view(CHART)["columns"]
    assert len(husband["cards"]) == 7 and husband["more"] == "+2 more"
    assert erin["more"] == "" and erin["cards"][0]["important"]


def test_the_chart_in_words() -> None:
    assert chart_text(CHART).splitlines()[:2] == [
        "On the chore chart:",
        "- Erin: Take the medicine; Dishes (since Tue)",
    ]
    assert chart_text(ChartCardData(date(2026, 10, 22), (Column("Erin", ()),))) == EMPTY_TEXT
