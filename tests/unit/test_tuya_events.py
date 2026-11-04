"""32: Tuya's request signing, and a feeder's data points read from recorded payloads."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.tuya import payload
from themi.connectors.tuya import FAULT, FOOD, JAMMED, LOW, OUT
from themi.connectors.tuya import events as tuya_events
from themi.connectors.tuya.client import sign, string_to_sign, url_for
from themi.connectors.tuya.events import read_status, state_word, words

# Tuya's worked examples (developer.tuya.com, "Signature algorithm", read 2026-11-04).
ACCESS_ID = "1KAD46OrT9HafiKdsXeg"
SECRET = "4OHBOnWOqaEC1mWXOpVL3yV50s0qGSRC"
T = "1588925778000"
NONCE = "5138cc3a9033d69856923fd07b491173"
SIGNED_HEADERS = {"area_id": "29a33e8796834b1efa6", "call_id": "8afdb70ab2ed11eb85290242ac130003"}


def test_signing_a_token_request_matches_tuyas_example() -> None:
    to_sign = string_to_sign("GET", "/v1.0/token?grant_type=1", headers=SIGNED_HEADERS)
    assert to_sign == (
        "GET\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
        "area_id:29a33e8796834b1efa6\ncall_id:8afdb70ab2ed11eb85290242ac130003\n\n"
        "/v1.0/token?grant_type=1"
    )
    assert (
        sign(ACCESS_ID, SECRET, T, NONCE, to_sign)
        == "9E48A3E93B302EEECC803C7241985D0A34EB944F40FB573C7B5C2A82158AF13E"
    )


def test_signing_a_business_request_matches_tuyas_example() -> None:
    url = url_for("/v2.0/apps/schema/users", {"page_size": 50, "page_no": 1})
    assert url == "/v2.0/apps/schema/users?page_no=1&page_size=50"  # sorted by key
    to_sign = string_to_sign("GET", url, headers=SIGNED_HEADERS)
    token = "3f4eda2bdec17232f67c0b188af3eec1"
    assert (
        sign(ACCESS_ID, SECRET, T, NONCE, to_sign, token)
        == "AE4481C692AA80B25F3A7E12C3A5FD9BBF6251539DD78E565A1A72A508A88784"
    )


def test_a_body_and_no_signed_headers() -> None:
    assert string_to_sign("post", "/v1.0/x", b"{}").split("\n") == [
        "POST",
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "",
        "/v1.0/x",
    ]
    assert url_for("/v1.0/x") == "/v1.0/x"
    assert url_for("/v1.0/x", {"codes": "a,b"}) == "/v1.0/x?codes=a,b"  # signed as it is


# ----- the standard feeder ---------------------------------------------------------------


def standard(name: str) -> Any:
    return read_status(payload(name), payload("standard_spec"), "pqxstdfeeder01")


def test_the_standard_feeder_full_low_and_empty() -> None:
    plenty = standard("standard_plenty")
    assert plenty.problems == {}
    assert (plenty.level, plenty.battery) == (64, 100)
    assert plenty.feed_codes == ("feed_report",)
    assert state_word(plenty) == "plenty of food (64% left)"

    low = standard("standard_low")
    assert low.problems == {FOOD: LOW}
    assert state_word(low) == "running low on food (15% left)"

    empty = standard("standard_empty")
    assert empty.problems == {FOOD: OUT}
    assert state_word(empty) == "out of food (0% left)"


def test_low_is_twenty_percent_or_under() -> None:
    def at(level: int) -> dict[str, str]:
        return read_status([{"code": "surplus_grain", "value": level}]).problems

    assert at(21) == {}
    assert at(20) == {FOOD: LOW}
    assert at(1) == {FOOD: LOW}


# ----- a feeder with its own fault bitmap ----------------------------------------------------


def faulty(name: str) -> Any:
    return read_status(payload(name), payload("fault_spec"), "pqxfaultfeed02")


def test_a_fault_bitmap_read_by_its_labels() -> None:
    assert faulty("fault_none").problems == {}
    assert state_word(faulty("fault_none")) == "fine"
    assert faulty("fault_shortage").problems == {FOOD: LOW}
    assert faulty("fault_motor").problems == {JAMMED: "the food's stuck (motor fault)"}
    both = faulty("fault_battery_and_empty")  # bits 0 and 2
    assert both.problems == {FOOD: OUT, FAULT: "the battery's low"}
    assert state_word(both) == "out of food; the battery's low"


def test_a_bit_with_no_label_is_still_a_fault() -> None:
    reading = faulty("fault_unknown_bit")  # bit 5: past the five labels
    assert reading.problems == {FAULT: "fault 5"}
    assert reading.unknown == ("fault 5",)


def test_without_its_specification_a_fault_is_its_number() -> None:
    reading = read_status([{"code": "fault", "value": 8}])
    assert reading.problems == {FAULT: "fault 8"}


@pytest.mark.parametrize(
    ("points", "spec", "problems"),
    [
        ([{"code": "food_shortage", "value": True}], {}, {FOOD: LOW}),
        ([{"code": "food_shortage", "value": False}], {}, {}),
        ([{"code": "food_level", "value": "low"}], {"food_level": "Enum"}, {FOOD: LOW}),
        ([{"code": "food_level", "value": "middle"}], {"food_level": "Enum"}, {}),
        ([{"code": "food_level", "value": "empty"}], {"food_level": "Enum"}, {FOOD: OUT}),
        (
            [{"code": "error_code", "value": "outlet_blocked"}],
            {},
            {JAMMED: "the food's stuck (outlet blocked)"},
        ),
        ([{"code": "error_code", "value": "normal"}], {}, {}),
        ([{"code": "alarm", "value": True}], {"alarm": "Boolean"}, {FAULT: "alarm"}),
        ([{"code": "desiccant_alarm", "value": True}], {}, {FAULT: "the desiccant needs changing"}),
        ([{"code": "feed_state", "value": "feeding"}], {}, {}),  # not a food level
    ],
)
def test_other_models_by_name(
    points: list[dict[str, Any]], spec: dict[str, str], problems: dict[str, str]
) -> None:
    specification = {"status": [{"code": c, "type": t, "values": "{}"} for c, t in spec.items()]}
    assert read_status(points, specification).problems == problems


def test_a_models_own_mapping_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    points = [{"code": "remain", "value": 10}, {"code": "dp_15", "value": 2}]
    assert read_status(points, None, "pqxodd").problems == {}
    monkeypatch.setitem(tuya_events.MODELS, "pqxodd", {"remain": "level", "dp_15": "fed"})
    reading = read_status(points, None, "pqxodd")
    assert reading.problems == {FOOD: LOW}
    assert reading.feed_codes == ("dp_15",)


def test_words() -> None:
    assert words("motor_fault") == "motor fault"
    assert words("FoodShortage") == "food shortage"
