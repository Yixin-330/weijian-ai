"""证据来源词表与立场白名单。

本模块是 `evidence.source_type` 取值的**单一事实源**，并把 PRD 8.4
「关注与立场分离」从文档规则变成代码强制约束。

## 为什么需要这个模块

此前白名单只写在 `app/zhihu/schemas.py` 的 `STANCE_ELIGIBLE` 里，
而那是导入适配层——它只认识平台信号，不认识应用内输入与理解校准，
而且没有任何记忆写入路径调用它。同时数据库种子用 `favlist_description`、
适配层用 `favlist_naming`，两套词表已经开始漂移。词表一旦漂移，
白名单校验就从根上失效：拼错的来源既不在白名单内、也不会被发现。

## 规则来源（PRD 8.4）

- **关注（topic）**：任意来源均可形成，只表示用户正在留意某个议题。
- **立场（stance）**：只能来自用户主动撰写或明确确认的内容，
  即应用内主动输入、理解校准，以及本人创作对应的标题与 `Summary`。
- 收藏、关注、应用内浏览只能说明用户在关注什么，不能说明立场——
  收藏一篇内容完全可能是为了反驳它。
- `Summary` 是平台返回的摘要，不等同于用户逐字原话，因此只能开启
  低或中置信度的立场**候选**，不能直接生成已确认立场。
"""

from __future__ import annotations

from enum import StrEnum

from .errors import DomainError


class EvidenceSource(StrEnum):
    """`evidence.source_type` 的完整词表。

    分两类：平台一次性导入（与 `app.zhihu.schemas.SignalKind` 一一对应）
    和应用内持续行为（「未见」自有）。
    """

    # --- A 类：平台导入（冷启动燃料）---
    AUTHORED_CONTENT = "authored_content"  # 本人创作的标题与 Summary
    FAVLIST_NAMING = "favlist_naming"  # 收藏夹自命名与描述
    FAVORITE_ITEM = "favorite_item"  # 收藏条目
    FOLLOWEE_HEADLINE = "followee_headline"  # 关注对象 Headline

    # --- B 类：应用内行为（长期主力）---
    IN_APP_INPUT = "in_app_input"  # 用户主动写下的想法与开放问题回答
    CALIBRATION = "calibration"  # 理解校准（很像我／只是最近／我在反对／理解错了）
    RETURNED_QUESTION_REPLY = "returned_question_reply"  # 对带回问题的回应
    IN_APP_BROWSE = "in_app_browse"  # 应用内浏览与停留


class MemoryType(StrEnum):
    """`memories.memory_type` 词表，与迁移中的 chk_memories_type 对齐。"""

    TOPIC = "topic"
    STANCE = "stance"
    PREFERENCE = "preference"
    BOUNDARY = "boundary"
    SOCIAL_INTENT = "social_intent"


class MemoryStatus(StrEnum):
    """`memories.status` 词表，与 chk_memories_status 对齐。"""

    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


# 立场来源白名单（PRD 8.4）。
# 收藏夹自命名虽是用户亲手命名，但它组织的是「关注什么」而非「站哪边」，
# 因此不在白名单内。
STANCE_ELIGIBLE_SOURCES: frozenset[EvidenceSource] = frozenset(
    {
        EvidenceSource.AUTHORED_CONTENT,
        EvidenceSource.IN_APP_INPUT,
        EvidenceSource.CALIBRATION,
    }
)

# 各来源的证据权重（PRD 8.4）。
#
# 权重表放在领域层而不是 `app/zhihu/schemas.py`：导入适配层的模块文档明确
# 写着「不做记忆判断」，而权重就是记忆判断——它决定一条候选理解能否成立。
# 适配层的 `SIGNAL_WEIGHT` 现在反向委托到这里，与 `STANCE_ELIGIBLE` 同一套
# 防漂移做法。
#
# 数值的含义是「这条行为多大程度上说明用户真的在意」：
# - 本人创作是用户花时间写下的东西，最强；
# - 收藏夹自命名是用户亲手起的名字，说明他在主动组织自己的关注；
# - 单条收藏可能只是顺手，关注某人更可能只是想看他的内容；
# - 应用内浏览停留最弱，单独永远不足以形成候选。
# 校准高于主动输入：校准是用户对着一条具体理解说「很像我」或「理解错了」，
# 比自由输入更明确地指向某个议题。
EVIDENCE_WEIGHT: dict[EvidenceSource, int] = {
    # A 类：平台导入。四个数值与 PRD 8.4 的阶梯一致，改动会直接影响
    # `app.domain.promotion.CANDIDATE_WEIGHT_FLOOR` 的语义。
    EvidenceSource.AUTHORED_CONTENT: 100,
    EvidenceSource.FAVLIST_NAMING: 80,
    EvidenceSource.FAVORITE_ITEM: 40,
    EvidenceSource.FOLLOWEE_HEADLINE: 20,
    # B 类：应用内行为。
    EvidenceSource.CALIBRATION: 120,
    EvidenceSource.IN_APP_INPUT: 100,
    EvidenceSource.RETURNED_QUESTION_REPLY: 60,
    EvidenceSource.IN_APP_BROWSE: 10,
}

# 新增来源却忘记赋权时，`dict.get(source, 0)` 会让它安静地变成零权重证据：
# 证据落库了，却永远推不动任何理解，而且没有任何报错。宁可在导入模块时
# 就失败。
_UNWEIGHTED = tuple(
    sorted(s.value for s in EvidenceSource if s not in EVIDENCE_WEIGHT)
)
if _UNWEIGHTED:  # pragma: no cover - 配置错误在导入时即暴露
    raise RuntimeError(
        f"EVIDENCE_WEIGHT 缺少来源 {', '.join(_UNWEIGHTED)}；"
        "新增 EvidenceSource 时必须同时给出权重。"
    )


def weight_of(source: EvidenceSource | str) -> int:
    """来源对应的证据权重。未知来源直接报错，不静默降级为 0。"""
    return EVIDENCE_WEIGHT[coerce_source(source)]


# 平台 Summary 派生立场的置信度上限。
# Summary 是平台摘要而非用户逐字原话，只能开启低或中置信度候选。
MAX_PLATFORM_STANCE_CONFIDENCE = 0.7

# 仅凭平台导入即可确认立场的来源为空集：确认必须有应用内证据参与。
_HIGHER_GRADE_SOURCES: frozenset[EvidenceSource] = frozenset(
    {EvidenceSource.IN_APP_INPUT, EvidenceSource.CALIBRATION}
)


class StanceSourceRejected(DomainError):
    """立场记忆的证据来源不满足白名单或置信度约束。

    继承 DomainError，因此 HTTP 层默认映射为 400——这是调用方的契约错误，
    不是资源缺失。
    """


def is_stance_eligible(source: EvidenceSource | str) -> bool:
    """该来源能否用于形成立场。未知来源一律视为不合格。"""
    try:
        resolved = EvidenceSource(source)
    except ValueError:
        return False
    return resolved in STANCE_ELIGIBLE_SOURCES


def coerce_source(value: EvidenceSource | str) -> EvidenceSource:
    """把字符串收敛为词表成员，未知取值直接报错。

    这是防词表漂移的关口：拼错的 source_type 会在写入前失败，
    而不是安静地变成一个「不在白名单里」的陌生值。
    """
    try:
        return EvidenceSource(value)
    except ValueError as exc:
        allowed = ", ".join(sorted(s.value for s in EvidenceSource))
        raise StanceSourceRejected(
            f"未知的证据来源 {value!r}；允许的取值为: {allowed}"
        ) from exc


def validate_memory_evidence(
    *,
    memory_type: MemoryType | str,
    sources: tuple[EvidenceSource | str, ...],
    status: MemoryStatus | str = MemoryStatus.CANDIDATE,
    confidence: float = 0.0,
) -> None:
    """校验一条记忆的证据来源组合是否合法。

    在**写入记忆之前**调用。关注类记忆不受来源限制；立场类记忆必须
    满足白名单，且仅有平台证据时受置信度与状态上限约束。

    抛 `StanceSourceRejected` 而不是静默降级为 topic：静默改写会让
    用户看到一条自己无法解释来源的记忆，违背 PRD 的可解释性要求。
    """
    resolved_type = MemoryType(memory_type)
    resolved_status = MemoryStatus(status)
    resolved_sources = tuple(coerce_source(s) for s in sources)

    if not resolved_sources:
        raise StanceSourceRejected("记忆必须至少关联一条证据")

    if resolved_type is not MemoryType.STANCE:
        # 关注、偏好、边界、社交意愿均可由任意来源形成。
        return

    disallowed = tuple(s for s in resolved_sources if s not in STANCE_ELIGIBLE_SOURCES)
    if disallowed:
        names = ", ".join(sorted(s.value for s in disallowed))
        allowed = ", ".join(sorted(s.value for s in STANCE_ELIGIBLE_SOURCES))
        raise StanceSourceRejected(
            f"立场记忆不能使用来源 {names}：这些信号只能说明用户在关注什么，"
            f"不能说明其立场。允许的来源为 {allowed}。"
            "如需保留该证据，请改为关注（topic）类记忆。"
        )

    # 只有平台 Summary 证据时，只能形成低或中置信度候选。
    has_in_app_evidence = any(s in _HIGHER_GRADE_SOURCES for s in resolved_sources)
    if not has_in_app_evidence:
        if resolved_status is not MemoryStatus.CANDIDATE:
            raise StanceSourceRejected(
                "仅凭平台创作摘要不能直接生成已确认立场："
                "Summary 是平台返回的摘要，不等同于用户逐字原话。"
                "确认需要应用内主动输入或用户校准参与。"
            )
        if confidence > MAX_PLATFORM_STANCE_CONFIDENCE:
            raise StanceSourceRejected(
                f"仅凭平台创作摘要的立场候选置信度不得超过 "
                f"{MAX_PLATFORM_STANCE_CONFIDENCE}，当前为 {confidence}。"
            )


def stance_confidence_ceiling(sources: tuple[EvidenceSource | str, ...]) -> float:
    """给定证据组合下，立场记忆的置信度上限。供记忆晋升层计算使用。"""
    resolved = tuple(coerce_source(s) for s in sources)
    if any(s in _HIGHER_GRADE_SOURCES for s in resolved):
        return 1.0
    return MAX_PLATFORM_STANCE_CONFIDENCE
