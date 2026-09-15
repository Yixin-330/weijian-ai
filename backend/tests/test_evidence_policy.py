"""证据来源词表与立场白名单测试。

对应 PRD 19.1 的 TC-MEM-004：仅有收藏与关注证据时，不得生成立场记忆。

重点不在「合法输入能通过」，而在**违规输入会被拒绝**——白名单的价值
完全体现在拒绝上。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.evidence_policy import (
    MAX_PLATFORM_STANCE_CONFIDENCE,
    STANCE_ELIGIBLE_SOURCES,
    EvidenceSource,
    MemoryStatus,
    MemoryType,
    StanceSourceRejected,
    coerce_source,
    is_stance_eligible,
    stance_confidence_ceiling,
    validate_memory_evidence,
)
from app.domain.experience import DEMO_EVIDENCE_SOURCES, DEMO_MEMORY_TYPE

MIGRATION_SQL = Path(__file__).resolve().parent.parent / "migrations" / "0001_core.sql"


# ---------- 立场白名单：拒绝路径（TC-MEM-004）----------


@pytest.mark.parametrize(
    "source",
    [
        EvidenceSource.FAVLIST_NAMING,
        EvidenceSource.FAVORITE_ITEM,
        EvidenceSource.FOLLOWEE_HEADLINE,
        EvidenceSource.IN_APP_BROWSE,
    ],
)
def test_stance_rejects_non_authored_sources(source: EvidenceSource):
    """收藏、关注、浏览只能说明关注什么，不能说明立场。"""
    with pytest.raises(StanceSourceRejected, match="不能说明其立场"):
        validate_memory_evidence(memory_type=MemoryType.STANCE, sources=(source,))


def test_stance_rejects_mixed_when_any_source_disallowed():
    """混合来源里只要有一项不合格就整体拒绝，不允许「有一条合格就放行」。"""
    with pytest.raises(StanceSourceRejected):
        validate_memory_evidence(
            memory_type=MemoryType.STANCE,
            sources=(EvidenceSource.IN_APP_INPUT, EvidenceSource.FAVORITE_ITEM),
        )


def test_rejection_message_names_the_remedy():
    """错误信息要说明补救方式，否则调用方只会把 stance 硬改成通过。"""
    with pytest.raises(StanceSourceRejected) as exc:
        validate_memory_evidence(
            memory_type=MemoryType.STANCE,
            sources=(EvidenceSource.FAVORITE_ITEM,),
        )
    assert "topic" in str(exc.value)


def test_validation_does_not_silently_downgrade():
    """违规必须抛错，不能静默改写成 topic。

    静默降级会让用户看到一条自己无法解释来源的记忆。
    """
    with pytest.raises(StanceSourceRejected):
        validate_memory_evidence(
            memory_type=MemoryType.STANCE,
            sources=(EvidenceSource.FAVLIST_NAMING,),
        )


# ---------- 立场白名单：通过路径 ----------


@pytest.mark.parametrize("source", sorted(STANCE_ELIGIBLE_SOURCES))
def test_stance_accepts_whitelisted_sources(source: EvidenceSource):
    validate_memory_evidence(
        memory_type=MemoryType.STANCE,
        sources=(source,),
        status=MemoryStatus.CANDIDATE,
        confidence=0.5,
    )


def test_whitelist_contents_match_prd():
    """白名单恰好三项：应用内主动输入、理解校准、本人创作。"""
    assert {s.value for s in STANCE_ELIGIBLE_SOURCES} == {
        "in_app_input",
        "calibration",
        "authored_content",
    }


# ---------- 关注类不受限制 ----------


@pytest.mark.parametrize("source", sorted(EvidenceSource))
def test_topic_accepts_any_source(source: EvidenceSource):
    """关注（topic）可由任意信号形成，包括被动行为。"""
    validate_memory_evidence(memory_type=MemoryType.TOPIC, sources=(source,))


@pytest.mark.parametrize(
    "memory_type",
    [MemoryType.PREFERENCE, MemoryType.BOUNDARY, MemoryType.SOCIAL_INTENT],
)
def test_non_stance_types_unrestricted(memory_type: MemoryType):
    validate_memory_evidence(
        memory_type=memory_type, sources=(EvidenceSource.FAVORITE_ITEM,)
    )


# ---------- Summary 不等同用户原话 ----------


def test_platform_only_stance_cannot_be_confirmed():
    """仅凭平台 Summary 不能直接生成已确认立场。"""
    with pytest.raises(StanceSourceRejected, match="不等同于用户逐字原话"):
        validate_memory_evidence(
            memory_type=MemoryType.STANCE,
            sources=(EvidenceSource.AUTHORED_CONTENT,),
            status=MemoryStatus.CONFIRMED,
            confidence=0.9,
        )


def test_platform_only_stance_confidence_capped():
    with pytest.raises(StanceSourceRejected, match="置信度不得超过"):
        validate_memory_evidence(
            memory_type=MemoryType.STANCE,
            sources=(EvidenceSource.AUTHORED_CONTENT,),
            confidence=MAX_PLATFORM_STANCE_CONFIDENCE + 0.01,
        )


def test_in_app_evidence_allows_confirmation():
    """应用内主动输入或校准参与后，才可确认立场。"""
    validate_memory_evidence(
        memory_type=MemoryType.STANCE,
        sources=(EvidenceSource.AUTHORED_CONTENT, EvidenceSource.CALIBRATION),
        status=MemoryStatus.CONFIRMED,
        confidence=0.95,
    )


def test_confidence_ceiling_depends_on_evidence_grade():
    assert (
        stance_confidence_ceiling((EvidenceSource.AUTHORED_CONTENT,))
        == MAX_PLATFORM_STANCE_CONFIDENCE
    )
    assert stance_confidence_ceiling((EvidenceSource.IN_APP_INPUT,)) == 1.0
    assert (
        stance_confidence_ceiling(
            (EvidenceSource.AUTHORED_CONTENT, EvidenceSource.CALIBRATION)
        )
        == 1.0
    )


# ---------- 防词表漂移 ----------


def test_unknown_source_is_rejected_not_ignored():
    """拼错的来源必须报错。

    若静默放行，它既不在白名单内、也不会被发现——漂移的白名单等于没有白名单。
    """
    with pytest.raises(StanceSourceRejected, match="未知的证据来源"):
        coerce_source("favlist_description")  # 迁移里曾用过的旧拼写


def test_unknown_source_never_stance_eligible():
    assert not is_stance_eligible("favlist_description")
    assert not is_stance_eligible("anything_else")


def test_empty_evidence_rejected():
    """记忆必须有证据支撑，否则无法回答「为什么发生这种变化」。"""
    with pytest.raises(StanceSourceRejected, match="至少关联一条证据"):
        validate_memory_evidence(memory_type=MemoryType.TOPIC, sources=())


def test_sql_check_vocabulary_matches_enum():
    """数据库 CHECK 与 EvidenceSource 词表必须一致。

    这是代码与迁移之间的对照：任一侧增删来源而忘了另一侧，此用例失败。
    """
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    match = re.search(
        r"chk_evidence_source_type CHECK \(source_type IN \((.*?)\)\)", sql, re.S
    )
    assert match, "迁移中缺少 chk_evidence_source_type 约束"
    in_sql = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert in_sql == {s.value for s in EvidenceSource}


def test_adapter_whitelist_delegates_to_domain():
    """适配层不得另存一份白名单，只能从领域层派生。"""
    from app.zhihu.schemas import STANCE_ELIGIBLE, SignalKind

    assert {k.value for k in STANCE_ELIGIBLE} == {
        s.value for s in STANCE_ELIGIBLE_SOURCES if s.value in {k.value for k in SignalKind}
    }
    # 适配层只见平台信号，因此其白名单是领域层白名单的子集
    assert {k.value for k in STANCE_ELIGIBLE} <= {s.value for s in STANCE_ELIGIBLE_SOURCES}


def test_signal_kinds_are_valid_evidence_sources():
    """适配层每个 SignalKind 都必须是合法的 EvidenceSource。"""
    from app.zhihu.schemas import SignalKind

    for kind in SignalKind:
        assert coerce_source(kind.value)


# ---------- 演示种子合规 ----------


def test_demo_seed_passes_validation():
    """演示种子必须合规：违规数据应在启动时暴露，而不是在评委面前。"""
    validate_memory_evidence(
        memory_type=DEMO_MEMORY_TYPE,
        sources=DEMO_EVIDENCE_SOURCES,
        status=MemoryStatus.CANDIDATE,
        confidence=0.62,
    )


def test_demo_seed_would_fail_as_stance():
    """确认种子若仍错标为 stance 会被拒绝——这正是修正前的状态。"""
    with pytest.raises(StanceSourceRejected):
        validate_memory_evidence(
            memory_type=MemoryType.STANCE,
            sources=DEMO_EVIDENCE_SOURCES,
            confidence=0.62,
        )
