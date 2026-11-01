"""30: LG's washer and dryer states, normalised from recorded payloads (tests/fixtures/thinq)."""

from __future__ import annotations

import pytest

from tests.fakes.thinq import payload
from themi.connectors.thinq import FINISHED, IDLE, RUNNING, ThinqDevice
from themi.connectors.thinq.client import region_url
from themi.connectors.thinq.events import minutes_left, parts, read_push, read_report, state_word

WASHER, DRYER, TOWER = "DEVICE_WASHER", "DEVICE_DRYER", "DEVICE_WASHTOWER"


@pytest.mark.parametrize(
    ("name", "kind", "expected"),
    [
        ("washer_running", WASHER, RUNNING),
        ("washer_end", WASHER, FINISHED),
        ("washer_power_off", WASHER, IDLE),
        ("washer_twin_mini_running", WASHER, FINISHED),  # the main drum counts
        ("dryer_running", DRYER, RUNNING),
        ("dryer_initial", DRYER, IDLE),
    ],
)
def test_state_reports(name: str, kind: str, expected: str) -> None:
    assert read_report("lg-1", kind, payload(name)) == {"lg-1": expected}


def test_a_washtower_is_a_washer_and_a_dryer() -> None:
    assert read_report("lg-tower-1", TOWER, payload("washtower")) == {
        "lg-tower-1:washer": FINISHED,
        "lg-tower-1:dryer": RUNNING,
    }
    tower = ThinqDevice("lg-tower-1", "Laundry", TOWER, "WKEX200HBA")
    assert [(p.external_id, p.name, p.appliance) for p in parts(tower)] == [
        ("lg-tower-1:washer", "Laundry (washer)", "washer"),
        ("lg-tower-1:dryer", "Laundry (dryer)", "dryer"),
    ]


def test_appliances_map_by_kind_and_others_wait_to_be_mapped() -> None:
    def appliance(kind: str) -> str | None:
        (part,) = parts(ThinqDevice("lg-1", "Thing", kind, "M"))
        return part.appliance

    assert appliance(WASHER) == "washer"
    assert appliance(DRYER) == "dryer"
    assert appliance("DEVICE_WASHCOMBO_MAIN") is None  # washes and dries: the family says
    assert appliance("DEVICE_REFRIGERATOR") is None


def test_pushes() -> None:
    assert read_push(payload("push_status_washer_end")) == {"lg-washer-1": FINISHED}
    assert read_push(payload("push_washing_complete")) == {"lg-washer-1": FINISHED}
    assert read_push(payload("push_washtower_dryer_running")) == {"lg-tower-1:dryer": RUNNING}
    # A push that only moves the timer says nothing about running or not.
    assert read_push(payload("push_timer_only")) == {}
    assert read_push({"pushType": "DEVICE_PUSH", "deviceId": "x", "pushCode": "DOOR_OPEN"}) == {}
    assert read_push({"pushType": "DEVICE_STATUS", "report": {}}) == {}


def test_words() -> None:
    assert state_word("pause") == RUNNING  # a paused cycle still has a load in it
    assert state_word("WRINKLE_CARE") == FINISHED
    assert state_word("RESERVED") == IDLE  # a delayed start hasn't started
    assert state_word("SOMETHING_NEW") is None


def test_the_country_picks_the_server() -> None:
    assert region_url("US") == "https://api-aic.lgthinq.com"
    assert region_url("GB") == "https://api-eic.lgthinq.com"
    assert region_url("KR") == "https://api-kic.lgthinq.com"


def test_minutes_left_from_the_timer() -> None:
    # F20b (bug #109): asked how long is left, Themi reads LG's timer.
    assert minutes_left("w", "DEVICE_WASHER", payload("washer_running")) == {"w": 24}
    assert minutes_left("d", "DEVICE_DRYER", payload("dryer_running")) == {"d": 48}
    assert minutes_left("t", "DEVICE_WASHTOWER", payload("washtower")) == {
        "t:washer": 0,
        "t:dryer": 40,
    }
    assert minutes_left("w", "DEVICE_WASHER", payload("washer_power_off")) == {}
    long = {"runState": {"currentState": "DRYING"}, "timer": {"remainHour": 1, "remainMinute": 5}}
    assert minutes_left("d", "DEVICE_DRYER", long) == {"d": 65}
