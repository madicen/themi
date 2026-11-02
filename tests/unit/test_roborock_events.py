"""V1: what the robot vacuum's status means, from status payloads in python-roborock's shape
(`tests/fixtures/roborock/`)."""

from __future__ import annotations

import pytest

from tests.fakes.roborock import payload
from themi.connectors.roborock.events import (
    BIN,
    FAULT,
    JAMMED,
    NOT_DOCKED,
    STUCK,
    WATER_EMPTY,
    WATER_FULL,
    low_parts,
    problems,
    read_status,
    state_word,
    unknown_codes,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("docked", {}),
        ("cleaning", {}),
        ("returning", {}),
        ("trapped", {STUCK: "it's trapped"}),
        ("wheels_jammed", {STUCK: "the wheels are caught"}),
        ("main_brush_jammed", {JAMMED: "the main brush is jammed"}),
        ("clean_water_empty", {WATER_EMPTY: "the clean-water tank is empty"}),
        ("dirty_water_full", {WATER_FULL: "the dirty-water tank is full"}),
        ("idle_away", {NOT_DOCKED: "it stopped away from the dock"}),
        ("battery_flat_away", {NOT_DOCKED: "its battery ran low"}),
        ("unknown_error", {FAULT: "it's showing error 250"}),
    ],
)
def test_each_status_reads_as_its_problems(name: str, expected: dict[str, str]) -> None:
    assert problems(read_status(payload(name))) == expected


def test_the_docks_tank_bits_count_without_an_alert() -> None:
    """The dock can say a tank's empty in its status bits before (or without) an alert."""
    raw = {**payload("docked"), "dss": 165}  # clean water: 1
    assert problems(read_status(raw)) == {WATER_EMPTY: "the clean-water tank is empty"}
    raw = {**payload("docked"), "dss": 153}  # dirty water: 1
    assert problems(read_status(raw)) == {WATER_FULL: "the dirty-water tank is full"}


def test_a_dock_alert_and_a_robot_alert_are_two_problems() -> None:
    raw = {**payload("trapped"), "dock_error_status": 46}
    assert problems(read_status(raw)) == {STUCK: "it's trapped", BIN: "the dock's dustbin isn't in"}


def test_low_battery_on_the_dock_is_just_charging() -> None:
    raw = {**payload("docked"), "error_code": 12, "battery": 4}
    assert problems(read_status(raw)) == {}


def test_codes_without_words_are_reported_for_the_log() -> None:
    raw = {**payload("unknown_error"), "dock_error_status": 99}
    status = read_status(raw)
    assert unknown_codes(status) == ["robot error 250", "dock error 99"]
    assert unknown_codes(read_status(payload("trapped"))) == []


def test_the_alert_resolved_is_the_docks_first() -> None:
    assert read_status(payload("clean_water_empty")).alert == 38
    assert read_status(payload("trapped")).alert == 8
    assert read_status(payload("docked")).alert is None


@pytest.mark.parametrize(
    ("name", "word"),
    [
        ("docked", "charging on its dock"),
        ("cleaning", "cleaning"),
        ("returning", "returning to its dock"),
        ("trapped", "stopped with a problem"),
        ("idle_away", "away from its dock"),
        ("clean_water_empty", "charging on its dock"),  # a dock alert: still on its dock
    ],
)
def test_state_words(name: str, word: str) -> None:
    assert state_word(read_status(payload(name))) == word


def test_parts_under_five_percent_left_are_due() -> None:
    counters = payload("consumables")
    assert low_parts(counters) == {}
    counters |= {"filter_work_time": 520_000, "strainer_work_times": 149, "sensor_dirty_time": 1}
    assert low_parts(counters) == {
        "filter_work_time": "filter",
        "strainer_work_times": "dock's water filter",
    }


def test_garbage_reads_as_nothing_wrong() -> None:
    status = read_status({"state": "?", "error_code": None, "dss": "x"})
    assert problems(status) == {}
    assert status.battery is None
