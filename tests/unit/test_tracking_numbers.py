"""PT1: tracking numbers found in shipping emails (`themi_google.tracking`)."""

from __future__ import annotations

import json
from importlib import resources

import pytest

from themi_google import tracking
from themi_google.tracking import Found, candidates, find, from_json, kinds

UPS = "1Z5R89390357567127"
UPS_2 = "1Z879E930346834440"
USPS = "9400111206206406260787"
FEDEX_12 = "986578788855"
FEDEX_15 = "568283610012000"
AMAZON = "TBA502887274000"


def _vendored() -> list[tuple[str, dict]]:
    root = resources.files("themi_google") / "tracking_data"
    out = []
    for carrier in tracking.CARRIERS:
        data = json.loads((root / f"{carrier}.json").read_text(encoding="utf-8"))
        out += [
            (carrier, raw)
            for raw in data["tracking_numbers"]
            if raw["name"] not in tracking.LEFT_OUT
        ]
    return out


# ----- the vendored data (its vetting) ------------------------------------------------------


def test_every_kind_in_the_four_files_is_used() -> None:
    """A kind whose check digit this module doesn't know would be dropped silently."""
    assert {k.id for k in kinds()} == {raw.get("id") or raw["name"] for _, raw in _vendored()}


@pytest.mark.parametrize(("carrier", "raw"), _vendored(), ids=lambda v: str(v)[:20])
def test_the_data_sets_own_test_numbers(carrier: str, raw: dict) -> None:
    ident = raw.get("id") or raw["name"]
    for number in raw["test_numbers"]["valid"]:
        assert any(c.kind.id == ident for c in candidates(number)), number
    for number in raw["test_numbers"]["invalid"]:
        assert not any(c.kind.id == ident for c in candidates(number)), number


def test_the_licence_and_its_source_are_kept() -> None:
    root = resources.files("themi_google") / "tracking_data"
    assert "MIT License" in (root / "LICENSE").read_text(encoding="utf-8")
    source = (root / "SOURCE.md").read_text(encoding="utf-8")
    assert "v2.0.0" in source and "fec2d02d2d2d410fdccc077edf155885649a9b6c" in source


# ----- finding them in text -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "found"),
    [
        (f"Tracking number: {UPS}", Found("ups", UPS)),
        (f"Your parcel {USPS} is on its way", Found("usps", USPS)),
        (f"Shipped! {AMAZON}", Found("amazon", AMAZON)),
        (f"FedEx tracking: {FEDEX_12}", Found("fedex", FEDEX_12)),
        ("Track it: 5682 8361 0012 000", Found("fedex", FEDEX_15)),
        ("Tracking: 9400 1112 0620 6406 2607 87", Found("usps", USPS)),
        (f"tracking {UPS.lower()}", Found("ups", UPS)),
    ],
)
def test_each_carriers_numbers(text: str, found: Found) -> None:
    assert find(text) == [found]


def test_the_usps_routing_prefix_is_left_off() -> None:
    assert find("Tracking: 4201028200009261290113185417468510") == [
        Found("usps", "9261290113185417468510")
    ]


def test_a_bad_check_digit_is_dropped() -> None:
    assert find("Tracking number: 1Z5R89390357567128") == []
    assert find("FedEx tracking: 996578788855") == []


@pytest.mark.parametrize(
    "text",
    [
        "Order #112-3456789-1234567 placed",
        "Questions? Call 1-800-555-0199 or (415) 555-0123",
        "Delivered 2026-11-21 at 14:05",
        "Card ending 4242, ref 20261121140512345678",
        "Your order number is 986578788855",  # a valid FedEx 12 with no tracking word near
    ],
)
def test_ordinary_numbers_are_not_tracking_numbers(text: str) -> None:
    assert find(text) == []


def test_a_bare_number_counts_with_a_tracking_word_on_the_line_before() -> None:
    assert find(f"Tracking number\n{FEDEX_12}\nThanks") == [Found("fedex", FEDEX_12)]


def test_a_number_inside_a_longer_one_is_not_found_twice() -> None:
    # the 22-digit USPS number holds a run that's a valid FedEx 12 with its spaces
    found = find("Tracking: 9400 1112 0108 0805 4830 16")
    assert [f.carrier for f in found] == ["usps"]


def test_each_number_once_in_the_order_found() -> None:
    text = f"Tracking: {UPS}\nAlso tracking: {UPS_2}\nAgain: tracking {UPS}"
    assert find(text) == [Found("ups", UPS), Found("ups", UPS_2)]


def test_an_email_with_none() -> None:
    assert find("Thanks for your order! It ships soon.") == []


# ----- links ----------------------------------------------------------------------------------


def test_a_number_only_in_a_link() -> None:
    link = f"https://www.ups.com/track?loc=en_US&tracknum={UPS}"
    assert find("Track your package", [link]) == [Found("ups", UPS)]


def test_a_number_inside_a_redirect_link() -> None:
    link = (
        "https://click.shop.example/ls/click?upn=abc&u=https%3A%2F%2Ftools.usps.com%2Fgo%2F"
        f"TrackConfirmAction%3FtLabels%3D{USPS}"
    )
    assert find("Track your package", [link]) == [Found("usps", USPS)]


def test_a_link_written_in_the_text() -> None:
    text = f"Track it here: https://www.fedex.com/fedextrack/?trknbr={FEDEX_12}"
    assert find(text) == [Found("fedex", FEDEX_12)]


def test_a_bare_number_in_a_link_with_nothing_about_tracking_is_ignored() -> None:
    assert find("Hi", [f"https://shop.example/account/orders/{FEDEX_12}"]) == []


# ----- two carriers on the same digits --------------------------------------------------------


def test_a_clash_is_settled_by_the_sender_or_a_carrier_named_nearby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fake a clash: one kind of each carrier accepting the same digits."""
    fedex = next(k for k in kinds() if k.id == "fedex_12")
    twin = tracking.Kind("usps", "usps_twin", fedex.pattern, fedex.check, None, False)
    base = kinds()
    monkeypatch.setattr(tracking, "kinds", lambda: (*base, twin))
    both = {Found("fedex", FEDEX_12), Found("usps", FEDEX_12)}
    assert set(find(f"Tracking: {FEDEX_12}")) == both
    assert find(f"Tracking: {FEDEX_12}", sender="track@usps.com") == [Found("usps", FEDEX_12)]
    assert find(f"FedEx tracking: {FEDEX_12}") == [Found("fedex", FEDEX_12)]


# ----- the stored form ------------------------------------------------------------------------


def test_stored_and_read_back() -> None:
    found = [Found("ups", UPS), Found("amazon", AMAZON)]
    assert from_json(tracking.as_json(found)) == found
    assert from_json(None) == [] and from_json("not json") == []
    assert from_json('[{"carrier": "dhl", "number": "1"}, {"carrier": "ups"}]') == []
