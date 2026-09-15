"""岛屿选择策略。

这是岛屿决策的**单一事实源**。此前 `domain/experience.py` 与
`storage/mysql.py` 各自硬编码了一份相同的 if/else 和两个岛屿 ID 字符串，
两份实现会各自漂移；现在两个 Adapter 都调用本模块。

设计原则（与 PRD 一致）：

- 岛屿只能来自 fixture。fixture 里的议题绑定真实知乎问题，因此
  `decision_reason` 可以引用真实问题标题，而不是自造世界观文案。
- 选择是纯函数且确定性：同样的输入必然得到同样的岛屿与理由，
  满足 PRD 19.2「固定场景回归结果可复现」。
- 决策结果携带 `fixture_version`，让每次 tick 都能回溯到当时用的哪版快照。
- 本模块不调用 LLM。未来引入模型时，模型只能**提议**候选岛屿，
  仍由这里校验 ID 是否存在于 fixture 并给出最终结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.islands import Island, IslandSet, get_islands

from .models import CalibrationDecision

# 岛屿 ID 采用当前活动 fixture 的取值（backend/fixtures/islands.v2.json）。
# 这些稳定 ID 同时用于 fixture、数据库外键与前端读取契约。
ISLAND_STABILITY = "stability"
ISLAND_INTIMACY = "intimacy"
ISLAND_AI_LONELINESS = "ai_loneliness"

# 用户校准否定了单一偏好时，生命体转向探索差异与边界。
_DIVERGENT_DECISIONS = frozenset(
    {CalibrationDecision.OPPOSES, CalibrationDecision.WRONG}
)


@dataclass(frozen=True)
class IslandChoice:
    """一次岛屿决策的完整结果，可直接写入 world_ticks 并用于解释。"""

    island_id: str
    reason: str
    fixture_version: str
    question_title: str
    question_url: str
    # 产品自撰的场景与事件是否就绪。为 False 时可以前往岛屿，
    # 但不能进入双 Agent 相遇（PRD 8.5 要求每岛 2-3 个事件）。
    design_ready: bool
    score_breakdown: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class IslandSignal:
    island_id: str
    recent_attention: float = 0.0
    long_term_interest: float = 0.0
    candidate_compatibility: float = 0.0
    repeat_count: int = 0


@dataclass(frozen=True)
class IslandDecisionContext:
    """一次岛屿选择所需的物化信号，不包含原始用户文本。"""

    calibration: CalibrationDecision | None
    signals: tuple[IslandSignal, ...]
    curiosity: float
    social_willingness: float


def _describe(island: Island, *, lead: str, score: float) -> str:
    """生成引用真实问题的决策理由。

    理由必须落到具体议题上，而不是只说「转向探索差异」——
    这是 PRD 8.3「为什么发生这种变化」可解释性的基础。
    """
    return (
        f"{lead}；综合信号得分 {score:.2f}，前往「{island.island_name}」，"
        f"议题来自真实提问：{island.source.question_title}"
    )


def _unit_interval(name: str, value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} 必须位于 0 到 1 之间")
    return value


def _score(
    island: Island,
    signal: IslandSignal,
    context: IslandDecisionContext,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    if signal.repeat_count < 0:
        raise ValueError("repeat_count 不得为负数")
    recent = 0.34 * _unit_interval("recent_attention", signal.recent_attention)
    long_term = 0.22 * _unit_interval("long_term_interest", signal.long_term_interest)
    compatibility = 0.18 * _unit_interval(
        "candidate_compatibility", signal.candidate_compatibility
    )
    curiosity = 0.14 * _unit_interval("curiosity", context.curiosity) / (
        1 + signal.repeat_count
    )
    social = (
        0.12
        * _unit_interval("social_willingness", context.social_willingness)
        * signal.candidate_compatibility
    )
    calibration = 0.0
    if context.calibration in _DIVERGENT_DECISIONS and island.island_id == ISLAND_INTIMACY:
        calibration = 0.42
    elif context.calibration not in _DIVERGENT_DECISIONS and island.island_id == ISLAND_STABILITY:
        calibration = 0.20
    repetition = -0.10 * min(signal.repeat_count, 3)
    breakdown = (
        ("recent_attention", recent),
        ("long_term_interest", long_term),
        ("candidate_compatibility", compatibility),
        ("curiosity", curiosity),
        ("social_willingness", social),
        ("calibration", calibration),
        ("repetition", repetition),
    )
    return sum(value for _, value in breakdown), breakdown


def demo_decision_context(
    calibration: CalibrationDecision | None,
) -> IslandDecisionContext:
    """当前演示数据的确定性物化上下文，后续由记忆聚合读模型替换。"""
    return IslandDecisionContext(
        calibration=calibration,
        signals=(
            IslandSignal(ISLAND_STABILITY, 0.72, 0.62, 0.60, 0),
            IslandSignal(ISLAND_INTIMACY, 0.30, 0.32, 0.62, 0),
            IslandSignal(ISLAND_AI_LONELINESS, 0.12, 0.18, 0.48, 0),
        ),
        curiosity=0.64,
        social_willingness=0.58,
    )


def materialized_decision_context(
    *,
    calibration: CalibrationDecision | None,
    recent_topic_weights: Mapping[str, float],
    long_term_topic_weights: Mapping[str, float],
    repeat_counts: Mapping[str, int],
    curiosity: float,
    social_willingness: float,
    compatibility_by_island: Mapping[str, float] | None = None,
    islands: IslandSet | None = None,
) -> IslandDecisionContext:
    """把聚合读模型转换为策略输入；原始文本不会越过此 seam。"""
    resolved = islands or get_islands()
    compatibility = compatibility_by_island or {}
    return IslandDecisionContext(
        calibration=calibration,
        signals=tuple(
            IslandSignal(
                island_id=island.island_id,
                recent_attention=recent_topic_weights.get(island.topic_code, 0.0),
                long_term_interest=long_term_topic_weights.get(island.topic_code, 0.0),
                candidate_compatibility=compatibility.get(island.island_id, 0.5),
                repeat_count=repeat_counts.get(island.island_id, 0),
            )
            for island in resolved.islands
        ),
        curiosity=curiosity,
        social_willingness=social_willingness,
    )


def select_island(
    *,
    context: IslandDecisionContext,
    islands: IslandSet | None = None,
) -> IslandChoice:
    """根据最近一次理解校准选择岛屿。

    当前为确定性规则，对应 PRD 8.5「进入岛屿条件」的最小可用子集。
    引入模型提议后，本函数仍是最终校验与提交点。
    """
    resolved = islands or get_islands()

    signals_by_id: dict[str, IslandSignal] = {}
    for signal in context.signals:
        resolved.by_id(signal.island_id)
        if signal.island_id in signals_by_id:
            raise ValueError(f"岛屿信号重复: {signal.island_id}")
        signals_by_id[signal.island_id] = signal

    scored: list[tuple[float, int, Island, tuple[tuple[str, float], ...]]] = []
    for island in resolved.islands:
        signal = signals_by_id.get(island.island_id, IslandSignal(island.island_id))
        score, breakdown = _score(island, signal, context)
        scored.append((score, -island.display_order, island, breakdown))
    score, _, island, breakdown = max(scored, key=lambda item: (item[0], item[1]))

    if island.island_id == ISLAND_INTIMACY and context.calibration in _DIVERGENT_DECISIONS:
        lead = "用户校准否定了单一偏好，生命体转向探索边界与差异"
    elif island.island_id == ISLAND_AI_LONELINESS:
        lead = "近期关注更集中在 AI、陪伴与真实关系的张力"
    else:
        lead = "近期理解仍围绕选择、不确定性与自主决定"

    return IslandChoice(
        island_id=island.island_id,
        reason=_describe(island, lead=lead, score=score),
        fixture_version=resolved.fixture_version,
        question_title=island.source.question_title,
        question_url=island.source.question_url,
        design_ready=island.design_ready,
        score_breakdown=breakdown,
    )


def initial_island(islands: IslandSet | None = None) -> IslandChoice:
    """新生命体的起始岛屿，用于演示种子与 onboarding。"""
    return select_island(context=demo_decision_context(None), islands=islands)


def topic_code_for(island_id: str) -> str:
    """岛屿对应的主题编码，供证据与记忆关联使用。"""
    return get_islands().by_id(island_id).topic_code
