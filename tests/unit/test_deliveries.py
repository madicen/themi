"""WL8: reading the model's `delivery` for an email."""

from __future__ import annotations

from themi_google.deliveries import parse
from themi_google.triage import SCHEMA, SYSTEM


def test_a_delivery_needs_a_shop_and_a_known_status() -> None:
    assert parse({"shop": " Chewy ", "date": "2026-10-21", "status": "delivered"}) == {
        "shop": "Chewy",
        "date": "2026-10-21",
        "status": "delivered",
    }
    assert parse({"shop": "", "date": "2026-10-21", "status": "delivered"}) is None
    assert parse({"shop": "Chewy", "date": "", "status": ""}) is None
    assert parse({"shop": "Chewy", "date": "", "status": "lost"}) is None
    assert parse(None) is None and parse("Chewy") is None


def test_a_bad_date_is_no_date_and_a_long_shop_is_cut() -> None:
    found = parse({"shop": "A" * 90, "date": "next Tuesday", "status": "on_the_way"})
    assert found == {"shop": "A" * 40, "date": "", "status": "on_the_way"}


def test_triage_asks_for_the_shop_never_whats_inside() -> None:
    item = SCHEMA["properties"]["results"]["items"]
    assert "delivery" in item["required"]
    assert "never what's in it" in SYSTEM
