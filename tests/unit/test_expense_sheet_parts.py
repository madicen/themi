"""EX1b: the parts of making and filling in expense sheets that need no app."""

from __future__ import annotations

from datetime import date

import pytest

from themi.accounts import InvalidValue
from themi_home.expense_sheets import (
    calendar_link,
    describe_proposal,
    estimate_confidence,
    parse_value,
    proposed,
    show,
)
from themi_home.expenses import Field

TODAY = date(2026, 10, 21)


def f(key: str, kind: str = "text", choices: tuple[str, ...] = ()) -> Field:
    return Field(1, 1, key, key.title(), kind, choices, False, 0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("said", "sure"),
    [
        ("about $40 on paint, pretty sure", 0.8),
        ("maybe $25 for the parking", 0.5),
        ("$40 on paint, 90% sure", 0.9),
        ("roughly 30 bucks", 0.7),
        ("40ish at the hardware store", 0.7),
        ("i think it was $12", 0.7),
        ("$84 at Merit for the Henderson lunch", None),
        ("the tip was 20%", None),  # a % that isn't how sure they are
    ],
)
def test_how_sure_their_words_say_they_are(said: str, sure: float | None) -> None:
    assert estimate_confidence(said) == sure


def test_a_proposal_is_made_safe() -> None:
    data = proposed(
        {
            "book_title": "",
            "shared": True,
            "sheets": [
                {
                    "title": "  Client  travel ",
                    "mode": "business",
                    "counts_as_spending": True,
                    "keywords": ["Flight", "  "],
                    "fields": [
                        {"label": "Amount", "type": "money", "choices": [], "critical": True},
                        {"label": "amount", "type": "money", "choices": [], "critical": False},
                        {"label": "Who was there?", "type": "text", "choices": [],
                         "critical": False},
                        {"label": "Kind", "type": "choice", "choices": [], "critical": False},
                        {"label": "Odd", "type": "colour", "choices": [], "critical": False},
                    ],
                },
                {"title": "", "mode": "custom", "counts_as_spending": True, "keywords": [],
                 "fields": []},
            ],
        }
    )  # fmt: skip
    (sheet,) = data["sheets"]
    assert data["book_title"] == "Client travel"
    assert data["shared"] is False  # a business sheet is always their own
    assert sheet["keywords"] == ["flight"]
    assert [(x["key"], x["type"]) for x in sheet["fields"]] == [
        ("amount", "money"), ("who_was_there", "text"), ("kind", "text"), ("odd", "text"),
    ]  # fmt: skip


def test_a_sheet_with_no_money_isnt_spending() -> None:
    data = proposed(
        {"book_title": "Mileage", "shared": False, "sheets": [{
            "title": "Mileage", "mode": "custom", "counts_as_spending": True, "keywords": [],
            "fields": [{"label": "Miles", "type": "number", "choices": [], "critical": True}],
        }]}
    )  # fmt: skip
    assert data["sheets"][0]["counts_as_spending"] is False
    text = describe_proposal(data, None)
    assert text.splitlines()[:2] == [
        "Here's the sheet:",
        "Mileage, yours (not counted as spending)",
    ]


@pytest.mark.parametrize(
    ("kind", "said", "kept"),
    [
        ("money", "$84.20", 8420),
        ("money", "about 40 bucks", 4000),
        ("number", "32 miles", 32),
        ("number", "12.5", 12.5),
        ("date", "yesterday", "2026-10-20"),
        ("date", "2026-10-02", "2026-10-02"),
        ("text", "  Acme   pitch ", "Acme pitch"),
        ("text", "", None),
    ],
)
def test_values_are_read_as_their_field_keeps_them(kind: str, said: str, kept: object) -> None:
    assert parse_value(f("x", kind), said, TODAY) == kept


def test_a_choice_must_be_one_of_its_choices() -> None:
    room = f("room", "choice", ("kitchen", "eating_out"))
    assert parse_value(room, "Eating out", TODAY) == "eating_out"
    with pytest.raises(InvalidValue, match="one of kitchen"):
        parse_value(room, "garage", TODAY)
    with pytest.raises(InvalidValue, match="amount like"):
        parse_value(f("amount", "money"), "lots", TODAY)


def test_values_are_shown_in_words() -> None:
    assert show(f("amount", "money"), 8420) == "$84.20"
    assert show(f("date", "date"), "2026-10-21") == "Wed 21 Oct"
    assert show(f("miles", "number"), 32) == "32 miles"


def test_a_calendar_event_links_to_google_calendar() -> None:
    assert calendar_link("erin@example.com|ev1") == (
        "https://calendar.google.com/calendar/event?eid=ZXYxIGVyaW5AZXhhbXBsZS5jb20"
    )
