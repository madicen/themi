from datetime import UTC, date, datetime, timedelta

from themi.core.priority import rank, words
from themi.core.tasks import Task

TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)


def task(due: date | None, importance: str = "normal") -> Task:
    return Task(1, "x", "errand", 1, 1, 1, "", "open", due, importance=importance)


def test_two_scales_in_words() -> None:
    assert words(task(TODAY, "high"), TODAY) == "urgent and important"
    assert words(task(TODAY + timedelta(days=1)), TODAY) == "urgent"
    assert words(task(TODAY - timedelta(days=3)), TODAY) == "urgent"  # overdue
    assert words(task(TODAY + timedelta(days=2), "high"), TODAY) == "important"
    assert words(task(None, "low"), TODAY) == ""


def test_the_order() -> None:
    fresh = NOW - timedelta(days=1)
    order = sorted(
        [
            ("neither", task(None, "low")),
            ("important", task(None, "high")),
            ("urgent", task(TODAY)),
            ("both", task(TODAY, "high")),
            ("sooner", task(TODAY - timedelta(days=1))),
        ],
        key=lambda pair: rank(pair[1], TODAY, fresh, NOW),
    )
    assert [name for name, _ in order] == ["both", "sooner", "urgent", "important", "neither"]
    left = rank(task(None, "high"), TODAY, NOW - timedelta(days=8), NOW)
    assert left < rank(task(TODAY), TODAY, fresh, NOW)  # left a week: before urgent-only
