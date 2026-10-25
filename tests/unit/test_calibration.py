import pytest

from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM
from themi.channels.calibration import PdaCalibrator, feedback_direction


@pytest.mark.parametrize(
    ("text", "direction"),
    [
        ("that was too pushy", 1),
        ("ugh, felt like pressure", 1),
        ("stop telling me what to do", 1),
        ("Don't boss me around", 1),
        ("just tell me", -1),
        ("you can be blunt with me", -1),
        ("that was fine honestly", -1),
        ("be more direct please", -1),
        ("used the last olive oil", 0),
        ("the laundry is fine", 0),
    ],
)
def test_feedback_direction(text: str, direction: int) -> None:
    assert feedback_direction(text) == direction


def test_feedback_moves_strength_one_step_and_logs_it(family: SeededFamily) -> None:
    calibrator = PdaCalibrator(family.store)
    change = calibrator.observe_text(family.erin, "that was too pushy")
    assert change is not None and (change.old, change.new) == (2, 3)
    assert family.store.get_member(family.erin.id).pda_strength == 3
    calibrator.observe_text(family.erin, "just tell me")
    assert family.store.get_member(family.erin.id).pda_strength == 2
    reasons = [c.reason for c in calibrator.history(family.erin.id)]
    assert reasons == ["said: that was too pushy", "said: just tell me"]


def test_strength_stays_within_bounds(family: SeededFamily) -> None:
    calibrator = PdaCalibrator(family.store)
    family.store.update_settings(SYSTEM, family.erin.id, pda_strength=3)
    assert calibrator.observe_text(family.erin, "too pushy") is None
    family.store.update_settings(SYSTEM, family.erin.id, pda_strength=0)
    assert calibrator.observe_text(family.erin, "just tell me") is None
    assert calibrator.history(family.erin.id) == []


def test_thumbs_down_reactions_raise_strictness(family: SeededFamily) -> None:
    calibrator = PdaCalibrator(family.store)
    assert calibrator.observe_reaction(family.husband, ["👍"]) is None
    change = calibrator.observe_reaction(family.husband, ["👎"])
    assert change is not None and (change.old, change.new) == (1, 2)
    assert change.reason == "reacted 👎 to a message"


def test_calibration_never_touches_the_other_member(family: SeededFamily) -> None:
    PdaCalibrator(family.store).observe_text(family.erin, "too pushy")
    assert family.store.get_member(family.husband.id).pda_strength == family.husband.pda_strength
