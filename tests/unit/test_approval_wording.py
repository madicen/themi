"""Approval summaries Themi writes itself are already PDA-safe, so they never need an
AI rewrite (which costs a model call per approval, and quota)."""

from datetime import date

from themi.channels.pda import find_demands
from themi.core.calendar import approval_summary
from themi.core.groceries import proposal
from themi.core.tasks import Task


def test_grocery_approvals_read_as_offers_not_orders() -> None:
    for items in (["olive oil"], ["eggs", "rice"], ["eggs", "rice", "coffee"]):
        summary = proposal(items).summary
        assert find_demands(summary, 3) == [], summary
    assert proposal(["olive oil"]).summary == "Olive oil for the grocery list"
    assert proposal(["eggs", "rice"]).summary == "Eggs and rice for the grocery list"


def test_calendar_approvals_read_as_offers_not_orders() -> None:
    task = Task(1, "Call the plumber", "call", 2, 1, 1, "", "open", date(2026, 10, 30))
    summary = approval_summary(task)
    assert summary == "For the family calendar: Call the plumber, Fri Oct 30"
    assert find_demands(summary, 3) == [], summary
