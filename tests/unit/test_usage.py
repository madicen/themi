"""UC1: meters, the daily table, limits and their overrides (the Themi Usage Plan)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from tests.fakes.modules import module_context
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.modules import Module, ModuleContext, ModuleError
from themi.usage import Limits, Meter, Price, Totals, UsageBook

GEMINI = Meter(
    "gemini.requests",
    "Gemini",
    "requests",
    group="AI",
    limits=Limits(per_day=1000, resets="America/Los_Angeles", source="Google", checked="2026-11"),
)
CALLS = Meter(
    "homeconnect.calls", "Home Connect", "calls", limits=Limits(per_day=1000, resets="UTC")
)


@pytest.fixture
def book(family: SeededFamily) -> UsageBook:
    book = UsageBook(family.db)
    book.add(GEMINI)
    book.add(CALLS)
    return book


def test_counting_adds_to_todays_row(book: UsageBook, frozen_clock: datetime) -> None:
    book.count("gemini.requests", scope="3", model="flash", input_tokens=10, output_tokens=4)
    book.count("gemini.requests", scope="3", model="flash", input_tokens=5, output_tokens=1)
    book.count("gemini.requests", scope="4", model="flash")
    assert book.today("gemini.requests") == Totals(3, 15, 5, 0.0)
    assert book.today("gemini.requests", scope="3") == Totals(2, 15, 5, 0.0)
    rows = book.db.query("SELECT * FROM usage_daily")
    assert len(rows) == 2


def test_the_day_turns_at_the_meters_own_midnight(book: UsageBook) -> None:
    # 23:30 in Los Angeles is 07:30 UTC the next day: Gemini's day hasn't turned yet,
    # Home Connect's (UTC) has.
    clock.freeze(datetime(2026, 11, 18, 7, 30, tzinfo=UTC))
    assert book.day("gemini.requests") == date(2026, 11, 17)
    assert book.day("homeconnect.calls") == date(2026, 11, 18)
    book.count("gemini.requests")
    clock.advance(timedelta(hours=1))  # 00:30 Pacific
    book.count("gemini.requests")
    assert book.today("gemini.requests").count == 1
    assert book.month("gemini.requests").count == 2


def test_a_meter_without_a_zone_uses_the_familys(book: UsageBook) -> None:
    book.add(Meter("tavily.credits", "Tavily", "credits"))
    clock.freeze(datetime(2026, 11, 18, 7, 30, tzinfo=UTC))  # the family is in Los Angeles
    assert book.day("tavily.credits") == date(2026, 11, 17)


def test_a_month_starts_on_the_first(book: UsageBook) -> None:
    clock.freeze(datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
    book.count("homeconnect.calls", 5)
    clock.freeze(datetime(2026, 11, 2, 12, 0, tzinfo=UTC))
    book.count("homeconnect.calls", 2)
    assert book.month("homeconnect.calls").count == 2
    last = book.days("homeconnect.calls", 3)
    assert [d.isoformat() for d, _ in last] == ["2026-10-31", "2026-11-01", "2026-11-02"]
    assert [t.count for _, t in last] == [5, 0, 2]


def test_a_database_error_is_logged_and_doesnt_raise(
    book: UsageBook, frozen_clock: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    book.db.execute("DROP TABLE usage_daily")
    with caplog.at_level(logging.WARNING):
        book.count("gemini.requests")
    assert "Couldn't count usage of gemini.requests" in caplog.text


def test_an_override_wins_for_its_scope_then_for_all(
    book: UsageBook, frozen_clock: datetime
) -> None:
    default = book.limit_for("gemini.requests", "3")
    assert default is not None
    assert (default.per_day, default.source, default.overridden) == (1000, "Google", False)
    book.set_limit("gemini.requests", per_day=500, per_month=None, set_by="Erin")
    assert book.limit_for("gemini.requests", "3").per_day == 500  # type: ignore[union-attr]
    book.set_limit("gemini.requests", per_day=20, per_month=None, set_by="Erin", scope="3")
    assert book.limit_for("gemini.requests", "3").per_day == 20  # type: ignore[union-attr]
    assert book.limit_for("gemini.requests", "4").per_day == 500  # type: ignore[union-attr]
    book.clear_limit("gemini.requests", "3")
    book.clear_limit("gemini.requests")
    assert book.limit_for("gemini.requests", "3").per_day == 1000  # type: ignore[union-attr]


def test_a_meter_with_no_numbers_has_no_limit(book: UsageBook) -> None:
    book.add(Meter("keep.calls", "Keep", "calls"))
    assert book.limit_for("keep.calls") is None


def test_an_estimate_needs_a_price_for_a_model_used(
    book: UsageBook, frozen_clock: datetime
) -> None:
    assert book.estimate("gemini.requests") is None
    book.add(
        Meter("anthropic.requests", "Claude", "requests",
              prices={"opus": Price(input_per_mtok=5.0, output_per_mtok=25.0)})
    )  # fmt: skip
    book.count("anthropic.requests", model="other")
    assert book.estimate("anthropic.requests") is None
    book.count("anthropic.requests", model="opus", input_tokens=1_000_000, output_tokens=100_000)
    assert book.estimate("anthropic.requests") == pytest.approx(7.5)


def test_prune_keeps_400_days(book: UsageBook) -> None:
    clock.freeze(datetime(2025, 9, 1, 12, 0, tzinfo=UTC))
    book.count("homeconnect.calls")
    clock.freeze(datetime(2026, 11, 18, 12, 0, tzinfo=UTC))
    book.count("homeconnect.calls")
    assert book.prune() == 1
    assert book.db.scalar("SELECT COUNT(*) FROM usage_daily") == 1


class Metered(Module):
    name = "metered"

    def install(self, ctx: ModuleContext) -> None:
        ctx.usage_meter(CALLS)


class MeteredToo(Module):
    name = "metered_too"

    def install(self, ctx: ModuleContext) -> None:
        ctx.usage_meter(CALLS)


class MeteredThenFails(Module):
    name = "metered_fails"

    def install(self, ctx: ModuleContext) -> None:
        ctx.usage_meter(GEMINI)
        raise RuntimeError("no key")


def test_a_module_registers_its_meter(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    ctx.load(Metered())
    assert ctx.services.usage.meters["homeconnect.calls"].module == "metered"


def test_a_meter_registered_twice_is_refused(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    with pytest.raises(ModuleError, match=r"registered twice.*module metered_too"):
        ctx.load(Metered(), MeteredToo())


def test_a_failed_install_leaves_no_meter(family: SeededFamily) -> None:
    ctx = module_context(family.store)
    ctx.load(MeteredThenFails(), tolerant=True)
    assert "metered_fails" in ctx.failed
    assert "gemini.requests" not in ctx.services.usage.meters


def test_the_tables_exist(family: SeededFamily) -> None:
    for table in ("usage_daily", "usage_limits"):
        try:
            family.db.scalar(f"SELECT COUNT(*) FROM {table}")
        except sqlite3.Error as exc:  # pragma: no cover
            pytest.fail(str(exc))
