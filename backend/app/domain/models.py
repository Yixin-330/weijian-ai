from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CalibrationDecision(StrEnum):
    LIKE_ME = "like_me"
    RECENT = "recent"
    OPPOSES = "opposes"
    WRONG = "wrong"


class OnboardingTopic(StrEnum):
    CHOICE_UNCERTAINTY = "choice_uncertainty"
    INTIMACY_AND_AUTONOMY = "intimacy_and_autonomy"
    AI_AND_LONELINESS = "ai_and_loneliness"


class ExplorationStyle(StrEnum):
    OBSERVE = "observe"
    INQUIRE = "inquire"
    ACT = "act"


class SocialPace(StrEnum):
    OBSERVE_FIRST = "observe_first"
    SHARED_EXPERIENCES = "shared_experiences"
    OPEN_TO_CONNECTION = "open_to_connection"


class TriggerType(StrEnum):
    CRON = "cron"
    MANUAL = "manual"
    FIXTURE = "fixture"


class RelationshipStage(StrEnum):
    UNMET = "unmet"
    NOTICED = "noticed"
    SHARED_EXPERIENCE = "shared_experience"
    CARED = "cared"
    CONNECTION_CANDIDATE = "connection_candidate"
    STALLED = "stalled"
    DISTANT = "distant"
    ENDED = "ended"


class EncounterAction(StrEnum):
    APPROACH = "approach"
    OBSERVE = "observe"
    RESPOND = "respond"
    COOPERATE = "cooperate"
    AVOID = "avoid"
    LEAVE = "leave"


class CalibrationRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=64)
    decision: CalibrationDecision
    allow_social_recommendation: bool = True


class OnboardingRequest(StrictModel):
    """The four onboarding answers plus their separate memory-use consent."""

    current_question: str = Field(min_length=4, max_length=240)
    long_term_topics: tuple[OnboardingTopic, ...] = Field(min_length=1, max_length=3)
    exploration_style: ExplorationStyle
    social_pace: SocialPace
    allow_memory_inference: bool
    allow_social_recommendation: bool = False

    @field_validator("current_question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 4:
            raise ValueError("current_question must contain at least four visible characters")
        return normalized

    @field_validator("long_term_topics")
    @classmethod
    def reject_duplicate_topics(
        cls, value: tuple[OnboardingTopic, ...]
    ) -> tuple[OnboardingTopic, ...]:
        if len(set(value)) != len(value):
            raise ValueError("long_term_topics must not contain duplicates")
        return value


class UserState(StrictModel):
    id: str
    display_name: str
    consent_version: int = Field(ge=1)


class Lifeform(StrictModel):
    id: str
    user_id: str
    name: str
    appearance: str
    exploration_tendency: str
    current_island_id: str
    current_focus: str
    status: str


class Memory(StrictModel):
    id: str
    lifeform_id: str
    kind: Literal["topic", "stance", "preference", "boundary", "social_intent"]
    statement: str
    status: Literal["candidate", "confirmed", "rejected"]
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]
    allow_social_recommendation: bool
    calibration: CalibrationDecision | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class Relationship(StrictModel):
    id: str
    lifeform_ids: tuple[str, str]
    stage: RelationshipStage
    island_id: str
    headline: str
    shared_experiences: tuple[str, ...]
    source_mode: Literal["precomputed", "live", "fallback"]


class EncounterTurn(StrictModel):
    id: str
    turn_number: int = Field(ge=1, le=5)
    actor_lifeform_id: str
    action: EncounterAction
    public_utterance: str
    reason_summary: str


class Encounter(StrictModel):
    id: str
    world_tick_id: str
    island_id: str
    fixture_version: str
    event_id: str
    title: str
    dilemma: str
    lifeform_ids: tuple[str, str]
    status: Literal["completed", "left"]
    turns: tuple[EncounterTurn, ...]
    outcome_summary: str
    relationship_id: str
    relationship_before: RelationshipStage
    relationship_after: RelationshipStage
    shared_memory: str
    return_question: str
    source_mode: Literal["fixture"] = "fixture"
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)


class AuditRecord(StrictModel):
    id: str
    event_type: str
    actor_id: str
    subject_id: str
    trace_id: str
    details: dict[str, str | int | bool]
    occurred_at: datetime = Field(default_factory=utc_now)


class WorldTick(StrictModel):
    id: str
    user_id: str
    lifeform_id: str
    trigger_type: TriggerType
    idempotency_key: str
    selected_island_id: str
    # 记录本次决策使用的 fixture 版本，使 tick 可回溯到当时的岛屿快照。
    # 数据库 world_ticks.fixture_version 列一直存在，此前没有模型字段承载。
    fixture_version: str | None = None
    # 数据库为 VARCHAR(500)；在模型层同样约束，避免超长理由到写库才失败。
    decision_reason: str = Field(max_length=500)
    status: Literal["completed"] = "completed"
    source_mode: Literal["live"] = "live"
    trace_id: str
    created_at: datetime = Field(default_factory=utc_now)


class WorldReadModel(StrictModel):
    user: UserState
    lifeform: Lifeform
    memories: tuple[Memory, ...]
    relationships: tuple[Relationship, ...]
    latest_tick: WorldTick | None
    source_mode: Literal["precomputed", "live"]


class TickCommand(StrictModel):
    user_id: str = Field(min_length=1, max_length=64)
    trigger_type: TriggerType
    idempotency_key: str = Field(min_length=1, max_length=128)


class TickSubmission(StrictModel):
    job_id: str
    status: Literal["queued", "in_progress", "completed", "failed", "not_found"]
    tick: WorldTick | None = None
    error: str | None = None
