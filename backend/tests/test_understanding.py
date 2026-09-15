from __future__ import annotations

import pytest

from app.domain.models import CalibrationDecision
from app.domain.understanding import (
    calibration_effect,
    effective_direction_decision,
    explain_next_action,
)


@pytest.mark.parametrize(
    ("decision", "status", "action", "influences_direction"),
    (
        (CalibrationDecision.LIKE_ME, "confirmed", "靠近", True),
        (CalibrationDecision.RECENT, "confirmed", "观察", True),
        (CalibrationDecision.OPPOSES, "confirmed", "回应", True),
        (CalibrationDecision.WRONG, "rejected", "观察", False),
    ),
)
def test_four_calibrations_have_deterministic_effects(
    decision: CalibrationDecision,
    status: str,
    action: str,
    influences_direction: bool,
):
    effect = calibration_effect(decision)

    assert effect.status == status
    assert effect.next_action == action
    assert effect.influences_direction is influences_direction


def test_wrong_understanding_cannot_keep_steering_island_selection():
    assert effective_direction_decision(CalibrationDecision.WRONG) is None
    assert (
        effective_direction_decision(CalibrationDecision.OPPOSES)
        is CalibrationDecision.OPPOSES
    )


def test_next_action_explanation_keeps_the_island_evidence():
    reason = explain_next_action(
        decision=CalibrationDecision.RECENT,
        island_reason="前往「亲密与自由」，议题来自真实提问：示例问题",
    )

    assert "只是近期关注" in reason
    assert "观察" in reason
    assert "真实提问：示例问题" in reason
