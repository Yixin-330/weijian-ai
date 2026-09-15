from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.models import OnboardingRequest
from app.domain.onboarding import project_onboarding


def make_request(**overrides) -> OnboardingRequest:
    values = {
        "current_question": "  我要继续稳定工作，还是尝试一次新的方向？  ",
        "long_term_topics": ("choice_uncertainty",),
        "exploration_style": "observe",
        "social_pace": "observe_first",
        "allow_memory_inference": True,
        "allow_social_recommendation": False,
    }
    values.update(overrides)
    return OnboardingRequest.model_validate(values)


def test_projection_is_deterministic_and_normalizes_input():
    request = make_request()
    first = project_onboarding(request)
    second = project_onboarding(request)

    assert request.current_question == "我要继续稳定工作，还是尝试一次新的方向？"
    assert first == second
    assert first.initial_island_id == "stability"
    assert first.exploration_tendency == "安静观察"
    assert first.social_intent == "disabled"
    assert request.current_question in first.candidate_statement


def test_question_can_choose_a_more_relevant_island_than_first_topic():
    projection = project_onboarding(
        make_request(
            current_question="AI 陪伴最终会缓解孤独，还是替代真实关系？",
            long_term_topics=("choice_uncertainty", "ai_and_loneliness"),
            exploration_style="act",
            social_pace="open_to_connection",
        )
    )

    assert projection.primary_topic.value == "ai_and_loneliness"
    assert projection.initial_island_id == "ai_loneliness"
    assert projection.exploration_tendency == "主动尝试"
    assert projection.social_intent == "open"


def test_duplicate_topics_are_rejected():
    with pytest.raises(ValidationError):
        make_request(long_term_topics=("choice_uncertainty", "choice_uncertainty"))
