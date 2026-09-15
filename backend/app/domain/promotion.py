"""从平台导入证据到候选理解的确定性晋升规则。

## 这一层为什么存在

`app/zhihu/importer.py` 只负责授权、额度、协议校验与快照落地，它的模块
文档明确写着「不做记忆判断」。而在此之前，`EvidenceSignal` 没有任何下游
消费者：导入拿到的信号无处可去，"真实行为 → 候选理解"这条链是断的。
本模块补上中间那一段，并且刻意保持**纯函数**——不碰数据库、不发网络请求、
不引入 `app.zhihu`，因此两个持久化适配器与测试共用完全相同的判定。

## 依赖方向

领域层不认识平台信号类型。适配层负责把 `EvidenceSignal` 翻译成这里的
`ImportedSignal`（见 `app/zhihu/bridge.py`），领域层只认 `EvidenceSource`
词表。这样 `SignalKind` 增减不会波及晋升规则。

## 判定规则（PRD 8.4）

1. **按议题分组**：信号文本经关键词归类到三个议题之一，无法归类的信号
   仍然落成证据行，但不参与候选理解——宁可少生成，也不要生成一条用户
   无法解释来源的理解。
2. **加权门槛**：一条候选理解需要该议题证据权重合计 ≥ `CANDIDATE_WEIGHT_FLOOR`。
   单条本人创作（100）足以开启候选；单条收藏（40）或单个关注对象（20）
   不足以——收藏一次不代表在意，可能只是顺手。
3. **只生成候选，绝不自动确认**：确认需要用户校准或应用内主动输入参与
   （见 `evidence_policy.validate_memory_evidence`）。跨 ≥2 信号类型、
   跨 ≥2 自然日、含本人创作这一组"长期记忆晋升合取条件"在这里只作为
   `meets_long_term_conjunction` 记录进审计与响应，供后续晋升层使用，
   不在导入时越权把状态写成 confirmed。
4. **类型恒为关注（topic）**：导入只能说明用户在关注什么。平台摘要不等同
   于用户逐字原话，因此立场（stance）不由导入路径生成。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .evidence_policy import (
    EVIDENCE_WEIGHT,
    STANCE_ELIGIBLE_SOURCES,
    EvidenceSource,
    coerce_source,
)
from .island_policy import topic_code_for
from .models import StrictModel
from .onboarding import TOPIC_ISLANDS, TOPIC_LABELS, topic_for_text

# 一条候选理解所需的最低证据权重。
# 取 100（= 一条本人创作）是为了让"收藏夹自命名 + 一条收藏"（80+40）
# 也能达标，而单条弱信号不能。
CANDIDATE_WEIGHT_FLOOR = 100

# 候选理解置信度上下限。导入证据永远只是候选，因此上限刻意低于
# 应用内主动输入形成的候选（0.82）。
_CONFIDENCE_BASE = 0.35
_CONFIDENCE_CEILING = 0.75
_CONFIDENCE_SCALE = 400.0

# evidence.source_ref 列宽（VARCHAR(500)），超长即截断而不是写失败。
_SOURCE_REF_LIMIT = 500
# 摘录进 statement 的证据文本长度。statement 是给用户看的解释，
# 不是原文存档——原文在快照里。
_EXCERPT_LIMIT = 40


@dataclass(frozen=True)
class ImportedSignal:
    """一条已翻译为领域词表的导入证据。

    `occurred_at` 是平台内容自身的时间（epoch 秒），不是导入时刻；
    跨自然日判定必须用前者，否则一次导入的所有证据都会落在同一天。
    """

    source: EvidenceSource
    text: str
    source_ref: str
    occurred_at: int

    @property
    def occurred_on(self) -> str:
        """证据所属自然日（UTC），用于跨日判定。无时间戳返回空串。"""
        if self.occurred_at <= 0:
            return ""
        return datetime.fromtimestamp(self.occurred_at, timezone.utc).strftime(
            "%Y-%m-%d"
        )

    @property
    def occurred_datetime(self) -> datetime | None:
        if self.occurred_at <= 0:
            return None
        return datetime.fromtimestamp(self.occurred_at, timezone.utc)

    @property
    def weight(self) -> int:
        return EVIDENCE_WEIGHT.get(self.source, 0)

    @property
    def truncated_ref(self) -> str:
        return self.source_ref[:_SOURCE_REF_LIMIT]


@dataclass(frozen=True)
class TopicPromotion:
    """某一议题下的晋升判定结果。"""

    topic_code: str
    island_id: str
    label: str
    signals: tuple[ImportedSignal, ...]
    weight: int
    statement: str
    confidence: float
    promoted: bool
    reason: str
    meets_long_term_conjunction: bool

    @property
    def source_kinds(self) -> tuple[EvidenceSource, ...]:
        return tuple(sorted({s.source for s in self.signals}))

    @property
    def distinct_days(self) -> tuple[str, ...]:
        return tuple(sorted({s.occurred_on for s in self.signals if s.occurred_on}))

    @property
    def has_authored_evidence(self) -> bool:
        return any(s.source in STANCE_ELIGIBLE_SOURCES for s in self.signals)


class PromotedUnderstanding(StrictModel):
    """响应中可见的一条候选理解摘要。

    带上证据构成，让"为什么系统这样理解我"在演示里可当场解释。
    """

    understanding_id: str
    topic_code: str
    statement: str
    confidence: float
    evidence_ids: tuple[str, ...]
    evidence_weight: int
    source_kinds: tuple[str, ...]
    distinct_days: tuple[str, ...]
    meets_long_term_conjunction: bool


class ImportReceipt(StrictModel):
    """一次导入的结果回执。

    `skipped` 记录未达门槛的议题及原因——证据已落库但没有生成理解，
    这件事必须可见，否则用户会以为导入失败了。
    """

    job_id: str
    user_id: str
    status: str
    snapshot_count: int
    evidence_count: int
    calls_used: int
    stop_reason: str | None
    understandings: tuple[PromotedUnderstanding, ...]
    skipped: tuple[str, ...]


def _confidence_for(weight: int) -> float:
    """权重越高置信度越高，但恒低于应用内主动输入形成的候选。"""
    raw = _CONFIDENCE_BASE + weight / _CONFIDENCE_SCALE
    return round(min(raw, _CONFIDENCE_CEILING), 4)


def _statement_for(label: str, signals: tuple[ImportedSignal, ...]) -> str:
    """用最高权重的一条证据做摘录，让理解可追溯到具体行为。"""
    strongest = max(signals, key=lambda s: (s.weight, s.occurred_at))
    excerpt = " ".join(strongest.text.split())[:_EXCERPT_LIMIT]
    if excerpt:
        return f"你在平台上的行为显示你正关注「{label}」，例如：{excerpt}"
    return f"你在平台上的行为显示你正关注「{label}」"


def group_by_topic(
    signals: tuple[ImportedSignal, ...],
) -> tuple[dict[str, tuple[ImportedSignal, ...]], tuple[ImportedSignal, ...]]:
    """按议题归类。返回 (已归类, 未能归类)。

    未能归类的信号不丢弃：它们仍然落成证据行，只是暂时不参与理解生成。
    """
    grouped: dict[str, list[ImportedSignal]] = {}
    unclassified: list[ImportedSignal] = []
    for signal in signals:
        topic = topic_for_text(signal.text)
        if topic is None:
            unclassified.append(signal)
            continue
        topic_code = topic_code_for(TOPIC_ISLANDS[topic])
        grouped.setdefault(topic_code, []).append(signal)
    return (
        {code: tuple(items) for code, items in grouped.items()},
        tuple(unclassified),
    )


def evaluate_promotion(
    signals: tuple[ImportedSignal, ...],
) -> tuple[TopicPromotion, ...]:
    """对每个议题给出晋升判定。按权重降序返回，结果稳定可复现。"""
    grouped, _ = group_by_topic(signals)

    promotions: list[TopicPromotion] = []
    for topic_code, items in grouped.items():
        topic = next(t for t in TOPIC_LABELS if t.value == topic_code)
        label = TOPIC_LABELS[topic]
        island_id = TOPIC_ISLANDS[topic]
        weight = sum(s.weight for s in items)
        kinds = {s.source for s in items}
        days = {s.occurred_on for s in items if s.occurred_on}
        has_authored = any(s.source in STANCE_ELIGIBLE_SOURCES for s in items)
        promoted = weight >= CANDIDATE_WEIGHT_FLOOR
        if promoted:
            reason = f"证据权重 {weight} 达到候选门槛 {CANDIDATE_WEIGHT_FLOOR}"
        else:
            reason = (
                f"「{label}」证据权重 {weight} 未达候选门槛 "
                f"{CANDIDATE_WEIGHT_FLOOR}，证据已保留但暂不生成理解"
            )
        promotions.append(
            TopicPromotion(
                topic_code=topic_code,
                island_id=island_id,
                label=label,
                signals=items,
                weight=weight,
                statement=_statement_for(label, items),
                confidence=_confidence_for(weight),
                promoted=promoted,
                reason=reason,
                # 长期晋升合取条件：≥2 信号类型 ∧ ≥2 自然日 ∧ 含本人创作。
                meets_long_term_conjunction=(
                    len(kinds) >= 2 and len(days) >= 2 and has_authored
                ),
            )
        )

    return tuple(sorted(promotions, key=lambda p: (-p.weight, p.topic_code)))


def normalize_sources(
    sources: tuple[EvidenceSource | str, ...],
) -> tuple[EvidenceSource, ...]:
    """收敛来源词表。拼错的取值在写入前失败，而不是安静地绕过白名单。"""
    return tuple(coerce_source(s) for s in sources)
