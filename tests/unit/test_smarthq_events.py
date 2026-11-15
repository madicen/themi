"""OV2: the range's raw ERDs, decoded and encoded as OV1 saw the real range send them."""

from __future__ import annotations

from tests.fakes.smarthq import range_off
from themi_home.connectors.smarthq import events as ov
from themi_home.connectors.smarthq.events import LOWER, UPPER


def test_both_ovens_off_as_ov1_read_them() -> None:
    raw = range_off()
    for cavity in (UPPER, LOWER):
        reading = ov.read(cavity, raw)
        assert not reading.on and reading.mode == ov.OFF and reading.set_f == 0
        assert ov.state_words(reading) == "off"
        assert reading.remote is False
    assert ov.read(UPPER, raw).timer_minutes == 0  # the upper oven has a kitchen timer
    assert ov.read(LOWER, raw).timer_minutes is None  # the lower has none
    assert ov.read(LOWER, raw).probe_f is None  # no probe in


def test_a_preheat_and_proof_as_the_range_sent_them() -> None:
    raw = range_off() | {
        "0x5200": "01015E00000000000000000000",  # Bake 350°F
        "0x5201": "01",  # preheating
        "0x520d": "011D",  # 285°F
        "0x520a": "01",
        "0x5100": "0D005500000000000000000000",  # Proof, as the range itself sent it
        "0x5101": "13",
    }
    lower, upper = ov.read(LOWER, raw), ov.read(UPPER, raw)
    assert lower.preheating and lower.mode == ov.BAKE and lower.set_f == 350
    assert ov.state_words(lower) == "preheating to 350°F for Bake (285°F now)"
    assert upper.state == ov.STATE_PROOF and upper.heated and upper.set_f == 85
    assert ov.state_words(upper) == "proofing (85°F)"


def test_writes_are_the_bytes_the_range_takes() -> None:
    assert ov.cook_value(ov.PROOF, 85) == "0D005500000000000000000000"  # what the range sent
    assert ov.cook_value(ov.BAKE, 350) == "01015E00000000000000000000"
    assert ov.OFF_VALUE == "00000000000000000000000000"  # what an off read back as
    assert ov.timer_value(5) == "0005"
    assert ov.code(UPPER, ov.KITCHEN_TIMER) == "0x5105"
    assert ov.code(LOWER, ov.CURRENT_STATE) == "0x5201"


def test_cooking_after_preheat_and_the_probe() -> None:
    raw = range_off() | {
        "0x5200": "1B019000000000000000000000",  # Convection Multi Bake 400°F
        "0x5201": "09",
        "0x520d": "0190",
        "0x5207": "01",
        "0x5203": "0098",  # the probe at 152°F
    }
    lower = ov.read(LOWER, raw)
    assert lower.heated and not lower.preheating
    assert ov.state_words(lower) == "on Convection Multi Bake at 400°F, preheated"
    assert lower.probe_f == 152
