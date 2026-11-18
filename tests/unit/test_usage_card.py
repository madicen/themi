"""UC4: the usage card, drawn from its data. Golden SVGs in `tests/golden/pictures/`."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tests.fixtures.family import SeededFamily
from tests.unit.test_day_card import golden
from themi import clock
from themi.core.tools import ToolRegistry
from themi.standard.drawings import show_usage, show_week
from themi.standard.usage_card import (
    NOTHING,
    UsageData,
    UsageGroup,
    UsageRow,
    collect,
    usage_svg,
    usage_text,
    view,
)
from themi.usage import Limits, Meter, Price, UsageBook

DAY = date(2026, 11, 18)


def row(label: str, **kw: object) -> UsageRow:
    base: dict[str, object] = {"unit": "calls", "today": 0, "month": 0, "day_of_month": 18,
                               "days_in_month": 30}  # fmt: skip
    base.update(kw)
    return UsageRow(label, **base)  # type: ignore[arg-type]


BUSY = UsageData(
    DAY,
    (
        UsageGroup(
            "AI",
            (
                row("Gemini (free tier)", unit="requests", today=212, month=3950, per_day=500),
                row(
                    "Cloudflare pictures", unit="neurons", today=8200, month=61_000, per_day=10_000
                ),
                row("Claude", unit="requests", today=40, month=820, estimate=4.1),
            ),
        ),
        UsageGroup(
            "Devices",
            (
                row("Home Connect", today=288, month=5140, per_day=1000),
                row("Tuya feeders", today=170, month=3020, refused=3),
                row("LG ThinQ", today=575, month=10_300),
            ),
        ),
        UsageGroup(
            "Web", (row("Tavily search", unit="credits", today=20, month=610, per_month=1000),)
        ),
    ),
    ai_days=tuple(100 + (i * 37) % 90 for i in range(30)),
)
OVER = UsageData(
    DAY, (UsageGroup("AI", (row("Gemini", unit="requests", today=530, month=900, per_day=500),)),)
)
EMPTY = UsageData(DAY, ())


@pytest.mark.parametrize(
    ("name", "data", "theme"),
    [("busy", BUSY, "light"), ("busy_dark", BUSY, "dark"), ("over", OVER, "light"),
     ("empty", EMPTY, "light")],
)  # fmt: skip
def test_the_card_matches_its_golden_files(name: str, data: UsageData, theme: str) -> None:
    golden(f"usage_{name}", usage_svg(data, theme))


def test_bars_are_coloured_by_how_close_they_are() -> None:
    assert row("a", today=100, per_day=500).state == "good"
    assert row("a", today=400, per_day=500).state == "near"
    assert row("a", today=500, per_day=500).state == "over"
    assert row("a", today=1, per_day=500, refused=1).state == "over"
    assert row("a", today=999).state == "good"  # no limit known


def test_a_bar_never_runs_past_its_track() -> None:
    (r,) = view(OVER)["groups"][0]["rows"]
    assert r["bar"]["width"] == 220


def test_a_monthly_meter_shows_the_pace_and_where_the_month_is_heading() -> None:
    tavily = row("Tavily", today=20, month=610, per_month=1000)
    assert tavily.monthly and tavily.pace == pytest.approx(18 / 30)
    assert tavily.projected == pytest.approx(610 / 18 * 30)
    (r,) = view(BUSY)["groups"][2]["rows"]
    assert r["bar"]["pace"] is not None and r["bar"]["heading"] is not None
    assert r["month"] == "about 1,017 by the 30th"


def test_the_card_in_words() -> None:
    text = usage_text(BUSY)
    assert "- Gemini (free tier): 212 of 500 today" in text
    assert "- Tuya feeders: 170 calls today (no limit known), refused 3 times" in text
    assert "- Tavily search: 610 of 1,000 this month" in text
    assert "- Claude: 40 requests today (no limit known); about $4.10 this month" in text
    assert usage_text(EMPTY) == NOTHING


def test_collect_reads_the_book(family: SeededFamily) -> None:
    clock.freeze(datetime(2026, 11, 18, 17, 0, tzinfo=UTC))
    usage = UsageBook(family.db)
    usage.add(Meter("gemini.requests", "Gemini", "requests", group="AI",
                    limits=Limits(per_day=500, resets="America/Los_Angeles")))  # fmt: skip
    usage.add(Meter("cloudflare.pictures", "Cloudflare", "neurons", group="AI",
                    measure="amount", limits=Limits(per_day=10_000)))  # fmt: skip
    usage.add(Meter("anthropic.requests", "Claude", "requests", group="AI",
                    prices={"opus": Price(input_per_mtok=4, output_per_mtok=20)}))  # fmt: skip
    usage.add(Meter("keep.calls", "Keep", "calls", group="Devices"))  # unused: no row
    usage.count("gemini.requests", 3, scope="7")
    usage.count("gemini.requests", 2, scope="9")
    usage.count("gemini.requests.refused", scope="9")
    usage.count("cloudflare.pictures", scope="2", amount=104)
    usage.count("anthropic.requests", scope="5", model="opus", input_tokens=10**6)
    data = collect(usage, {"7": "Gemini (free tier)", "9": "Gemini (free tier) 2"})
    (ai,) = data.groups
    rows = {r.label: r for r in ai.rows}
    assert set(rows) == {"Gemini (free tier)", "Gemini (free tier) 2", "Cloudflare", "Claude"}
    assert rows["Gemini (free tier) 2"].refused == 1
    assert rows["Cloudflare"].today == 104
    assert rows["Claude"].estimate == pytest.approx(4.0)
    assert data.ai_days[-1] == 6  # Gemini's and Claude's requests today


def test_show_usage_is_offered_to_admins_only() -> None:
    tools = ToolRegistry()
    tools.register(show_week)
    tools.register(show_usage)
    tools.admin_only.add("show_usage")
    names = {s.name for s in tools.specs_for(set(), "all", admin=False)}
    assert "show_usage" not in names and "show_week" in names
    assert "show_usage" in {s.name for s in tools.specs_for(set(), "all")}
