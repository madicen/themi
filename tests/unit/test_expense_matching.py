"""EX2a: matching receipts to entries, the quote check and the confidence table."""

from __future__ import annotations

from datetime import date

import pytest

from themi_home import expense_matching as m

DAY = date(2026, 10, 21)


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("DoorDash - Merit", "Merit", True),
        ("Merit Kitchen, Inc.", "merit kitchen", True),
        ("Thai Place via DoorDash", "Thai Place", True),
        ("UberEats: Nopa", "NOPA", True),
        ("The Merit", "Merit Kitchen", True),  # one's words all in the other's
        ("Merit", "Nopa", False),
        ("DoorDash", "", False),
    ],
)
def test_vendor_names(a: str, b: str, same: bool) -> None:
    assert m.same_vendor(a, b) is same


def test_a_match_needs_the_date_and_what_the_entry_knows() -> None:
    receipt = m.Known(8420, DAY, "Merit")
    assert m.match(m.Known(None, DAY, "Merit"), receipt) == 2  # a lunch said with no amount
    assert m.match(m.Known(8420, date(2026, 10, 19), "DoorDash - Merit"), receipt) == 3
    assert m.match(m.Known(8420, date(2026, 10, 18), "Merit"), receipt) == 0  # three days off
    assert m.match(m.Known(8400, DAY, "Merit"), receipt) == 0  # another amount
    assert m.match(m.Known(8420, DAY, "Nopa"), receipt) == 0  # another place
    assert m.match(m.Known(None, DAY, None), receipt) == 0  # only the day: not enough
    # DoorDash's receipt names the restaurant in its text
    assert m.match(m.Known(2550, DAY, "Thai Place"), m.Known(2550, DAY, "DoorDash"),
                   "Your order from Thai Place") == 3  # fmt: skip


def test_the_best_match_is_the_closest() -> None:
    receipt = m.Known(2550, DAY, "Merit")
    entries = [
        ("far", m.Known(2550, date(2026, 10, 19), None)),
        ("near", m.Known(2550, date(2026, 10, 20), None)),
        ("more", m.Known(2550, date(2026, 10, 19), "Merit")),
        ("other", m.Known(9900, DAY, None)),
    ]
    assert m.best_match(receipt, entries) == "more"  # three agree
    assert m.best_match(receipt, entries[:2]) == "near"
    assert m.best_match(receipt, entries[3:]) is None


def test_a_value_must_be_quoted_from_its_text() -> None:
    text = "Merit\nBurrata $14.00\nTotal   $84.20\nThanks for dining"
    assert m.checked(8420, "total $84.20", text) == 8420
    assert m.checked("Henderson", "lunch with Henderson", text) is None  # made up: dropped
    assert m.amount_line(8420, text) == "Total $84.20"
    assert m.amount_line(8400, text) is None
    assert m.amount_line(123450, "Grand total: $1,234.50") == "Grand total: $1,234.50"
    assert m.amount_line(1400, "Burrata $114.00") is None  # not part of another number
    assert m.name_line("DoorDash - Merit", text) == "Merit"


def test_confidence_is_a_table_in_code() -> None:
    assert m.CONFIDENCE[("email_receipt", "amount date vendor")] == 0.95
    assert m.CONFIDENCE[("calendar_event", "vendor")] == 0.6
    assert m.CONFIDENCE[("chat_context", "said nearby")] == 0.7
    assert all(0 < c <= 1 for c in m.CONFIDENCE.values())


@pytest.mark.parametrize(
    ("title", "location", "vendor", "fits"),
    [
        ("Lunch with Henderson", "Merit, 123 Main St", "Merit", True),
        ("Dinner at Nopa", "", "Nopa", True),
        ("Acme check-in", "", None, True),  # a client by name
        ("Dentist", "45 Elm Street", None, False),
    ],
)
def test_calendar_events(title: str, location: str, vendor: str | None, fits: bool) -> None:
    assert m.event_vendor(title, location) == vendor
    assert m.event_fits(title, location, ["Acme"]) is fits
