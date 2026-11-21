"""WL8, PT2: reading the model's `parcels` for an email."""

from __future__ import annotations

from themi_google.deliveries import is_carrier_name, parse, parse_all
from themi_google.triage import SCHEMA, SYSTEM

UPS = "1Z5R89390357567127"


def test_a_parcel_needs_a_shop_and_a_known_status() -> None:
    assert parse({"shop": " Chewy ", "date": "2026-10-21", "status": "delivered"}) == {
        "shop": "Chewy",
        "tracking": "",
        "date": "2026-10-21",
        "status": "delivered",
        "problem": "",
        "window_start": "",
        "window_end": "",
    }
    assert parse({"shop": "", "date": "2026-10-21", "status": "delivered"}) is None
    assert parse({"shop": "Chewy", "date": "", "status": ""}) is None
    assert parse({"shop": "Chewy", "date": "", "status": "lost"}) is None
    assert parse(None) is None and parse("Chewy") is None


def test_a_bad_date_is_no_date_and_a_long_shop_is_cut() -> None:
    found = parse({"shop": "A" * 90, "date": "next Tuesday", "status": "on_the_way"})
    assert found is not None
    assert (found["shop"], found["date"]) == ("A" * 40, "")


def test_only_a_tracking_number_code_found_is_kept() -> None:
    raw = {"shop": "Chewy", "tracking": UPS.lower(), "date": "", "status": "on_the_way"}
    assert parse(raw, {UPS}) == {**parse(raw), "tracking": UPS}  # type: ignore[dict-item]
    invented = {**raw, "tracking": "1Z999AA10123456784"}
    assert parse(invented, {UPS})["tracking"] == ""  # type: ignore[index]


def test_a_problem_keeps_a_short_line_and_other_statuses_none() -> None:
    raw = {"shop": "UPS", "date": "", "status": "problem", "problem": "Delivery  attempted"}
    assert parse(raw)["problem"] == "Delivery attempted"  # type: ignore[index]
    assert len(parse({**raw, "problem": "x" * 200})["problem"]) == 80  # type: ignore[index]
    assert parse({**raw, "status": "on_the_way"})["problem"] == ""  # type: ignore[index]


def test_an_emails_parcels_are_the_well_formed_ones() -> None:
    good = {"shop": "USPS", "date": "2026-10-22", "status": "on_the_way"}
    assert len(parse_all([good, {"shop": ""}, "x", good])) == 2
    assert parse_all(None) == () and parse_all({"shop": "x"}) == ()
    assert len(parse_all([good] * 30)) == 12


def test_carrier_names() -> None:
    assert is_carrier_name("UPS") and is_carrier_name(" usps  informed delivery")
    assert is_carrier_name("FedEx") and not is_carrier_name("Chewy")
    assert not is_carrier_name("Amazon")  # Amazon is a shop as well as a carrier


def test_triage_asks_for_the_shop_never_whats_inside() -> None:
    item = SCHEMA["properties"]["results"]["items"]
    assert "parcels" in item["required"]
    assert set(item["properties"]["parcels"]["items"]["required"]) == {
        "shop",
        "tracking",
        "date",
        "status",
        "problem",
        "window",
    }
    words = " ".join(SYSTEM.split())
    assert "never what's in it" in words and "tracking numbers block" in words


def test_a_delivery_window_is_two_times_or_none() -> None:
    raw = {"shop": "UPS", "date": "", "status": "out_for_delivery"}
    window = lambda w: [parse({**raw, "window": w})[k] for k in ("window_start", "window_end")]  # type: ignore[index]  # noqa: E731
    assert window("14:15-16:15") == ["14:15", "16:15"]
    assert window(" 9:00 - 13:00 ") == ["09:00", "13:00"]
    for bad in ("", "2-4 pm", "16:15-14:15", "25:00-26:00", None):
        assert window(bad) == ["", ""]
