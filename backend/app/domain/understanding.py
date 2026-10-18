"""Deterministic semantics for calibrating a candidate understanding.

The product calls these records "candidate understandings" while the existing
persistence model keeps the historical ``memories`` table name.  This module is
the single place that translates the four user-facing calibration choices into
state, a lifeform focus, and an observable next action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .evidence_policy import MemoryStatus
from .models import CalibrationDecision


LifeformAction = Literal["靠近", "观察", "回应"]


@dataclass(frozen=True)
class CalibrationEffect:
    status: MemoryStatus
    focus: str
    next_action: LifeformAction
    explanation: str
    influences_direction: bool


_EFFECTS: dict[CalibrationDecision, CalibrationEffect] = {
    CalibrationDecision.LIKE_ME: CalibrationEffect(
        status=MemoryStatus.CONFIRMED,
        focus="带着已确认的关注继续探索",
        next_action="靠近",
        explanation="用户确认了这条候选理解，生命体会带着它继续靠近相关问题",
        influences_direction=True,
    ),
    CalibrationDecision.RECENT: CalibrationEffect(
        status=MemoryStatus.CONFIRMED,
        focus="把这条理解只作为近期关注",
        next_action="观察",
        explanation="用户说明这只是近期关注，生命体会继续观察但不把它固化为长期特质",
        influences_direction=True,
    ),
    CalibrationDecision.OPPOSES: CalibrationEffect(
        status=MemoryStatus.CONFIRMED,
        focus="区分关注议题与赞同观点",
        next_action="回应",
        explanation="用户正在反对这个观点，生命体只保留议题关注并转向回应不同答案",
        influences_direction=True,
    ),
    CalibrationDecision.WRONG: CalibrationEffect(
        status=MemoryStatus.REJECTED,
        focus="重新观察，而不是替主人下结论",
        next_action="观察",
        explanation="用户否定了这条候选理解，生命体停止使用它并重新观察",
        influences_direction=False,
    ),
}


def calibration_effect(decision: CalibrationDecision) -> CalibrationEffect:
    return _EFFECTS[decision]


def effective_direction_decision(
    decision: CalibrationDecision | None,
) -> CalibrationDecision | None:
    """Return the decision that may influence island selection.

    ``wrong`` rejects the candidate understanding.  Keeping it as a negative
    island-selection signal would still let the rejected understanding steer
    the lifeform, which contradicts the user correction.
    """

    if decision is None:
        return None
    return decision if calibration_effect(decision).influences_direction else None


def explain_next_action(
    *, decision: CalibrationDecision | None, island_reason: str
) -> str:
    if decision is None:
        prefix = "候选理解尚未校准，生命体先选择观察"
    else:
        prefix = calibration_effect(decision).explanation
    return f"{prefix}；{island_reason}"


def next_action(decision: CalibrationDecision | None) -> LifeformAction:
    return "观察" if decision is None else calibration_effect(decision).next_action
