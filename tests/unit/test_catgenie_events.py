"""CG1a: a litter box's report read into words and problems, its alerts, and the app's
encodings that PetNovations checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from tests.fakes.catgenie import payload
from themi_home.connectors.catgenie.client import (
    phone_field,
    render_path,
    time_field,
    unaes,
)
from themi_home.connectors.catgenie.events import (
    ERROR,
    LOW,
    OUT,
    SOLUTION,
    error_words,
    read_alert,
    read_device,
    state_word,
)


def box(**changes: object) -> dict[str, object]:
    raw = payload("device")
    raw.update(changes)
    return raw


def test_the_documented_report_reads_as_ready_with_its_solution_and_cycles() -> None:
    reading = read_device(payload("device"))
    assert reading.online and not reading.cleaning
    assert (reading.sani_left, reading.cycles, reading.errors) == (39, 600, ())
    assert reading.last_clean == datetime(2026, 10, 21, 15, 30, tzinfo=UTC)  # no zone: UTC
    assert reading.problems == {}
    assert state_word(reading) == "ready, 39% sani-solution left"


def test_cleaning_offline_and_progress() -> None:
    cleaning = read_device(box(operationStatus={"state": 1, "progress": 40}))
    assert state_word(cleaning) == "cleaning (40% done), 39% sani-solution left"
    idle = read_device(box(operationStatus={"state": 0, "progress": 255}))
    assert idle.progress is None
    assert state_word(read_device(box(reportedStatus="disconnected"))) == "offline"


def test_sani_solution_low_at_twenty_and_out_at_none() -> None:
    assert read_device(box(remainingSaniSolution=21)).problems == {}
    assert read_device(box(remainingSaniSolution=20)).problems == {SOLUTION: LOW}
    assert read_device(box(remainingSaniSolution=0)).problems == {SOLUTION: OUT}
    assert read_device(box(remainingSaniSolution=None)).problems == {}  # not reported


def test_errors_from_the_status_and_the_list_once_each_in_plain_words() -> None:
    reading = read_device(
        box(
            operationStatus={"state": 0, "progress": 255, "error": "HEATER_FAULT"},
            activeErrors=["HEATER_FAULT", {"code": "waterLevelLow"}, "none", ""],
        )
    )
    assert reading.errors == ("HEATER_FAULT", "waterLevelLow")
    assert reading.unknown == reading.errors  # no words of Themi's own yet
    assert reading.problems == {
        ERROR: "it shows an error (heater fault); it shows an error (water level low)"
    }
    assert error_words("DOME_OPEN") == "it shows an error (dome open)"


def test_odd_shapes_dont_break_the_reading() -> None:
    reading = read_device({"manufacturerId": "x", "operationStatus": "?", "configuration": []})
    assert not reading.online and reading.cycles is None and reading.problems == {}


def test_an_alert_names_its_box_its_error_and_its_time() -> None:
    alert = read_alert(payload("notification"))
    assert (alert.manufacturer_id, alert.kind, alert.error) == ("CGR0000001", 24, "")
    assert alert.at == datetime(2026, 10, 20, 8, tzinfo=UTC)
    named = read_alert({"id": "a", "data": json.dumps({"errorType": "DOME_OPEN", "type": 3})})
    assert named.error == "DOME_OPEN"
    assert read_alert({"id": "b", "data": "not json"}).error == ""


def test_the_app_encodings_round_trip() -> None:
    hidden = unaes(phone_field("+15550100123"))
    phone, _, rest = hidden.rpartition("-")
    assert phone == "+15550100123" and len(rest) == 8 and "X" in rest
    ms, _, rest = unaes(time_field(1_761_062_400_100)).partition("-")
    assert ms == "1761062400200"  # an odd hundred moves on one
    assert len(rest) == 8 and "Z" in rest
    assert unaes(time_field(1_761_062_400_000)).startswith("1761062400000-")
    assert render_path("facade/v1/mobile-user/refreshToken/v2") == "mobile-user/refreshToken/v2"
    assert render_path("/device/device/v2") == "device/device/v2"
