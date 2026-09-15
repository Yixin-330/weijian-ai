"""岛屿决策策略测试。

关注两件事：决策来自 fixture 而非硬编码字符串，以及决策可解释、可回溯。
"""

from __future__ import annotations

import pytest

from app.domain.island_policy import (
    ISLAND_AI_LONELINESS,
    ISLAND_INTIMACY,
    ISLAND_STABILITY,
    IslandDecisionContext,
    IslandSignal,
    demo_decision_context,
    initial_island,
    select_island,
    topic_code_for,
)
from app.domain.models import CalibrationDecision
from app.islands import FixtureError, get_islands


def test_island_ids_exist_in_fixture():
    """三个常量必须都能在 fixture 中找到，避免常量与快照漂移。"""
    islands = get_islands()
    for island_id in (ISLAND_STABILITY, ISLAND_INTIMACY, ISLAND_AI_LONELINESS):
        assert islands.by_id(island_id).island_id == island_id


def test_no_calibration_goes_to_stability():
    choice = select_island(context=demo_decision_context(None))
    assert choice.island_id == ISLAND_STABILITY


def test_affirming_calibration_stays_on_stability():
    for decision in (CalibrationDecision.LIKE_ME, CalibrationDecision.RECENT):
        assert select_island(context=demo_decision_context(decision)).island_id == ISLAND_STABILITY


def test_negating_calibration_switches_island():
    """用户否定单一偏好后，生命体转向探索差异——这是校准真的产生影响的证据。"""
    for decision in (CalibrationDecision.OPPOSES, CalibrationDecision.WRONG):
        assert select_island(context=demo_decision_context(decision)).island_id == ISLAND_INTIMACY


def test_reason_cites_real_zhihu_question():
    """决策理由必须落到真实议题上（PRD 8.3 可解释性）。"""
    islands = get_islands()
    for decision in (None, CalibrationDecision.OPPOSES):
        choice = select_island(context=demo_decision_context(decision))
        island = islands.by_id(choice.island_id)
        assert island.source.question_title in choice.reason
        assert island.island_name in choice.reason


def test_reason_fits_database_column():
    """decision_reason 列为 VARCHAR(500)，理由不得超长。"""
    for decision in (None, *CalibrationDecision):
        assert len(select_island(context=demo_decision_context(decision)).reason) <= 500


def test_choice_carries_fixture_version_for_replay():
    choice = select_island(context=demo_decision_context(None))
    assert choice.fixture_version == get_islands().fixture_version
    assert choice.fixture_version


def test_choice_exposes_question_url():
    """来源链接不得隐去，供前端标注出处。"""
    choice = select_island(context=demo_decision_context(None))
    assert choice.question_url.startswith("https://www.zhihu.com/question/")


def test_approved_design_allows_encounters():
    """场景与事件已评审，岛屿可以进入双 Agent 相遇（PRD 8.5）。"""
    assert select_island(context=demo_decision_context(None)).design_ready is True


def test_selection_is_deterministic():
    """同输入同输出，满足固定场景可复现（PRD 19.2）。"""
    a = select_island(context=demo_decision_context(CalibrationDecision.OPPOSES))
    b = select_island(context=demo_decision_context(CalibrationDecision.OPPOSES))
    assert a == b


def test_initial_island_matches_no_calibration():
    assert initial_island().island_id == select_island(
        context=demo_decision_context(None)
    ).island_id


def test_unknown_island_id_is_rejected():
    """岛屿 ID 只能来自 fixture：未知 ID 必须报错而不是静默写入。"""
    with pytest.raises(FixtureError):
        get_islands().by_id("not-an-island")
    with pytest.raises(FixtureError):
        topic_code_for("not-an-island")


def test_topic_codes_are_distinct():
    codes = {
        topic_code_for(i)
        for i in (ISLAND_STABILITY, ISLAND_INTIMACY, ISLAND_AI_LONELINESS)
    }
    assert len(codes) == 3
    # 与演示种子的 evidence.topic_code 保持一致
    assert topic_code_for(ISLAND_STABILITY) == "choice_uncertainty"


def test_third_island_is_reachable():
    context = IslandDecisionContext(
        calibration=None,
        signals=(
            IslandSignal(ISLAND_STABILITY, 0.05, 0.10, 0.30, 1),
            IslandSignal(ISLAND_INTIMACY, 0.08, 0.12, 0.30, 1),
            IslandSignal(ISLAND_AI_LONELINESS, 0.95, 0.82, 0.75, 0),
        ),
        curiosity=0.70,
        social_willingness=0.55,
    )
    choice = select_island(context=context)
    assert choice.island_id == ISLAND_AI_LONELINESS
    assert dict(choice.score_breakdown)["recent_attention"] > 0


def test_repeat_penalty_can_diversify_an_otherwise_equal_choice():
    context = IslandDecisionContext(
        calibration=CalibrationDecision.RECENT,
        signals=(
            IslandSignal(ISLAND_STABILITY, 0.60, 0.50, 0.50, 3),
            IslandSignal(ISLAND_INTIMACY, 0.60, 0.50, 0.50, 0),
        ),
        curiosity=0.70,
        social_willingness=0.50,
    )
    assert select_island(context=context).island_id == ISLAND_INTIMACY
