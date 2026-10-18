"""Deterministic projection from four onboarding answers to initial lifeform state.

The answers establish an editable starting point, not a personality diagnosis.
This module is deliberately pure so both persistence adapters and tests share
exactly the same interpretation rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from .island_policy import (
    ISLAND_AI_LONELINESS,
    ISLAND_INTIMACY,
    ISLAND_STABILITY,
)
from .models import ExplorationStyle, OnboardingRequest, OnboardingTopic, SocialPace


TOPIC_LABELS: dict[OnboardingTopic, str] = {
    OnboardingTopic.CHOICE_UNCERTAINTY: "选择、稳定与冒险",
    OnboardingTopic.INTIMACY_AND_AUTONOMY: "亲密关系与独立",
    OnboardingTopic.AI_AND_LONELINESS: "AI、陪伴与真实关系",
}

TOPIC_ISLANDS: dict[OnboardingTopic, str] = {
    OnboardingTopic.CHOICE_UNCERTAINTY: ISLAND_STABILITY,
    OnboardingTopic.INTIMACY_AND_AUTONOMY: ISLAND_INTIMACY,
    OnboardingTopic.AI_AND_LONELINESS: ISLAND_AI_LONELINESS,
}

EXPLORATION_LABELS: dict[ExplorationStyle, str] = {
    ExplorationStyle.OBSERVE: "安静观察",
    ExplorationStyle.INQUIRE: "温和追问",
    ExplorationStyle.ACT: "主动尝试",
}

APPEARANCE_LABELS: dict[ExplorationStyle, str] = {
    ExplorationStyle.OBSERVE: "雾蓝",
    ExplorationStyle.INQUIRE: "晨光",
    ExplorationStyle.ACT: "流金",
}

SOCIAL_INTENTS: dict[SocialPace, str] = {
    SocialPace.OBSERVE_FIRST: "disabled",
    SocialPace.SHARED_EXPERIENCES: "exploring",
    SocialPace.OPEN_TO_CONNECTION: "open",
}

SOCIAL_LABELS: dict[SocialPace, str] = {
    SocialPace.OBSERVE_FIRST: "先观察，不主动接近",
    SocialPace.SHARED_EXPERIENCES: "共同经历几次后再靠近",
    SocialPace.OPEN_TO_CONNECTION: "合适时可以建议连接",
}

_NAMES = ("露米", "栖光", "弥岚", "澄野", "微澜", "朔羽")
_QUESTION_HINTS: tuple[tuple[OnboardingTopic, tuple[str, ...]], ...] = (
    (
        OnboardingTopic.AI_AND_LONELINESS,
        ("ai", "人工智能", "孤独", "陪伴", "机器人", "模型"),
    ),
    (
        OnboardingTopic.INTIMACY_AND_AUTONOMY,
        ("亲密", "关系", "恋爱", "伴侣", "自由", "独立", "边界"),
    ),
    (
        OnboardingTopic.CHOICE_UNCERTAINTY,
        ("工作", "职业", "稳定", "冒险", "选择", "创业", "离开"),
    ),
)


@dataclass(frozen=True)
class OnboardingProjection:
    primary_topic: OnboardingTopic
    initial_island_id: str
    lifeform_name: str
    appearance: str
    exploration_tendency: str
    social_intent: str
    social_pace_label: str
    current_focus: str
    candidate_statement: str
    birth_description: str


@dataclass(frozen=True)
class OnboardingIds:
    user_id: str
    lifeform_id: str
    question_evidence_id: str
    question_memory_id: str
    topic_evidence_ids: tuple[str, ...]
    topic_memory_ids: tuple[str, ...]


def topic_for_text(text: str) -> OnboardingTopic | None:
    """Classify free text into one of the three islands, or None if unclear.

    Returning None matters for the import path: a platform signal that matches
    no island still becomes an evidence row, but must not seed an understanding
    the user cannot trace back to anything.  Onboarding cannot use None (the
    user has already told us their long-term topics), so `_primary_topic`
    supplies its own fallback rather than pushing one in here.
    """
    lowered = text.casefold()
    for topic, keywords in _QUESTION_HINTS:
        if any(keyword in lowered for keyword in keywords):
            return topic
    return None


def _primary_topic(request: OnboardingRequest) -> OnboardingTopic:
    matched = topic_for_text(request.current_question)
    if matched is not None:
        return matched
    # The current question said nothing recognisable; fall back to the first
    # long-term topic the user picked explicitly.
    return request.long_term_topics[0]


def project_onboarding(request: OnboardingRequest) -> OnboardingProjection:
    primary = _primary_topic(request)
    exploration = EXPLORATION_LABELS[request.exploration_style]
    appearance = APPEARANCE_LABELS[request.exploration_style]
    name_seed = "|".join(
        (request.current_question, *(topic.value for topic in request.long_term_topics))
    ).encode("utf-8")
    name = _NAMES[sha256(name_seed).digest()[0] % len(_NAMES)]
    focus = request.current_question[:120]
    topic_label = TOPIC_LABELS[primary]
    social_label = SOCIAL_LABELS[request.social_pace]
    return OnboardingProjection(
        primary_topic=primary,
        initial_island_id=TOPIC_ISLANDS[primary],
        lifeform_name=name,
        appearance=appearance,
        exploration_tendency=exploration,
        social_intent=SOCIAL_INTENTS[request.social_pace],
        social_pace_label=social_label,
        current_focus=focus,
        candidate_statement=f"你最近正在关注：{request.current_question}",
        birth_description=(
            f"{name}从你对“{topic_label}”的好奇中醒来。"
            f"它更习惯{exploration}，与别人相遇时会{social_label}。"
        ),
    )


def onboarding_ids(idempotency_key: str, topic_count: int) -> OnboardingIds:
    """Create stable IDs so retrying the same onboarding request is safe."""

    def stable(kind: str, index: int | None = None) -> str:
        suffix = f":{index}" if index is not None else ""
        return uuid5(
            NAMESPACE_URL, f"weijian:onboarding:{idempotency_key}:{kind}{suffix}"
        ).hex

    return OnboardingIds(
        user_id=stable("user"),
        lifeform_id=stable("lifeform"),
        question_evidence_id=stable("question-evidence"),
        question_memory_id=stable("question-memory"),
        topic_evidence_ids=tuple(stable("topic-evidence", index) for index in range(topic_count)),
        topic_memory_ids=tuple(stable("topic-memory", index) for index in range(topic_count)),
    )
