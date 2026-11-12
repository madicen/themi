"""EX2b: the words of Themi's questions about expense sheets, and when they're due."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from themi.accounts import InvalidValue
from themi.accounts.store import SYSTEM
from themi.channels.pda import find_demands
from themi_home.expense_asks import (
    BARE_AMOUNT,
    GOT_TEXT,
    LATER_TEXT,
    REVIEW_TEXT,
    SKIPPED_TEXT,
    SpendingPreferences,
    question,
    thing,
)
from themi_home.expense_sheets import CHANGE_TEXT, PROPOSE_TEXT
from themi_home.expenses import TAKEOUT_FIELDS, Entry, Field, Sheet, Value

NOW = datetime(2026, 10, 21, 16, tzinfo=ZoneInfo("UTC"))


def sheet(mode: str = "personal") -> Sheet:
    return Sheet(1, 1, "Kitchen project", mode, None, True, True, (), None, 0, True, None,  # type: ignore[arg-type]
                 NOW, None)  # fmt: skip


def fields() -> list[Field]:
    return [Field(i, 1, f.key, f.label, f.type, f.choices, f.critical, i)
            for i, f in enumerate(TAKEOUT_FIELDS)]  # fmt: skip


def entry(**values: object) -> Entry:
    return Entry(1, 1, 1, "chat", None, NOW, None, {k: Value.said(v) for k, v in values.items()})


def test_the_question_names_the_spend() -> None:
    amount, vendor = fields()[0], fields()[2]
    dinner = entry(date="2026-10-20", vendor="Merit", category="eating_out")
    assert question(dinner, sheet(), fields(), amount) == (
        "What did eating out at Merit on Tue 20 Oct come to?"
    )
    paint = entry(date="2026-10-20", amount=4000)
    assert thing(paint, sheet(), fields()) == "the $40.00 one on Kitchen project on Tue 20 Oct"
    assert question(paint, sheet(), fields(), vendor) == (
        "For the $40.00 one on Kitchen project on Tue 20 Oct: what was the vendor?"
    )


@pytest.mark.parametrize(
    "text",
    [
        "What did eating out at Merit on Tue 20 Oct come to?",
        "For the $40.00 one on Kitchen project on Tue 20 Oct: what was the vendor?",
        REVIEW_TEXT, SKIPPED_TEXT, LATER_TEXT, GOT_TEXT, PROPOSE_TEXT, CHANGE_TEXT,
    ],
)  # fmt: skip
def test_the_questions_read_as_offers(text: str) -> None:
    """Never "you need to": they pass the PDA checker at its strictest."""
    assert find_demands(text, 3) == []


@pytest.mark.parametrize(
    ("said", "bare"),
    [
        ("$84.20", True), ("84", True), ("it was 84 with the tip", True), ("about 40 bucks", True),
        ("Just spent $20 on lunch", False), ("84 for the Henderson lunch", False),
        ("remind me at 5", False),
    ],
)  # fmt: skip
def test_an_answer_on_its_own(said: str, bare: bool) -> None:
    assert bool(BARE_AMOUNT.match(said)) is bare


def test_the_settings_are_checked(family) -> None:  # type: ignore[no-untyped-def]
    prefs = family.store.preferences(family.erin.id, SpendingPreferences)
    assert (prefs.expense_ask_after_hours, prefs.expense_review_day, prefs.expense_review_time) == (
        24,
        "friday",
        time(15, 0),
    )
    saved = family.store.save_preferences(
        SYSTEM, family.erin.id, SpendingPreferences,
        expense_ask_after_hours=6, expense_review_day="Monday", expense_review_time="09:30",
    )  # fmt: skip
    assert (saved.expense_review_day, saved.expense_review_time) == ("monday", time(9, 30))
    with pytest.raises(InvalidValue, match="between 1 hour and a week"):
        family.store.save_preferences(
            SYSTEM, family.erin.id, SpendingPreferences, expense_ask_after_hours=0
        )
    with pytest.raises(InvalidValue, match="day of the week"):
        family.store.save_preferences(
            SYSTEM, family.erin.id, SpendingPreferences, expense_review_day="someday"
        )
