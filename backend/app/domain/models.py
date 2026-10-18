from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .evidence_policy import EvidenceSource, MemoryStatus, MemoryType


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


class ExplorationSettings(StrictModel):
    enabled: bool = True
    allow_cross_island: bool = False
    allow_demo_partners: bool = False
    social_pace: SocialPace = SocialPace.SHARED_EXPERIENCES
    excluded_topics: tuple[OnboardingTopic, ...] = ()


class ExplorationState(StrictModel):
    lifeform_id: str
    user_id: str
    island_id: str
    enabled: bool
    allow_cross_island: bool = False
    allow_demo_partners: bool = False
    is_demo: bool = False
    social_pace: SocialPace = SocialPace.SHARED_EXPERIENCES
    excluded_topics: tuple[str, ...] = ()
    availability: Literal["available", "busy"] = "available"
    waiting_since: datetime = Field(default_factory=utc_now)
    available_at: datetime = Field(default_factory=utc_now)
    latest_social_snapshot_id: str | None = None


class EncounterDecisionRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=64)
    decision: Literal["observe_again", "invite", "distance", "end", "block"]


class TriggerType(StrEnum):
    CRON = "cron"
    MANUAL = "manual"
    FIXTURE = "fixture"


class EncounterStatus(StrEnum):
    """Technical lifecycle only; it never describes how the pair feels."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    INVALID = "invalid"
    LEFT = "left"
    FAILED = "failed"
    DISCARDED = "discarded"


class RelationshipStatus(StrEnum):
    """Whether a pair may keep exploring, not an inferred intimacy level."""

    ACTIVE = "active"
    ENDED = "ended"
    BLOCKED = "blocked"


class UserDecisionKind(StrEnum):
    OBSERVE_AGAIN = "observe_again"
    INVITE = "invite"
    DISTANCE = "distance"
    END = "end"
    BLOCK = "block"


class ConnectionStatus(StrEnum):
    WAITING = "waiting"
    MUTUAL_ACCEPTED = "mutual_accepted"
    ACTIVE = "active"
    ENDED = "ended"


class MessageStatus(StrEnum):
    SENT = "sent"
    DELETED = "deleted"


class ContextPurpose(StrEnum):
    EXPLORATION = "exploration"
    SOCIAL_RECOMMENDATION = "social_recommendation"


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


class UnderstandingChange(StrictModel):
    user_id: str
    operation: Literal["edit", "delete", "permission"]
    expected_version: int = Field(ge=1)
    statement: str | None = Field(default=None, min_length=1, max_length=1000)
    allow_social_recommendation: bool = False


class ConsentChange(StrictModel):
    memory_inference: bool
    social_recommendation: bool


class EvidenceIngestRequest(StrictModel):
    """A source fact entering the append-only growth-evidence log."""

    ingestion_key: str = Field(min_length=1, max_length=128)
    source: EvidenceSource
    content_text: str = Field(min_length=1, max_length=10000)
    source_ref: str | None = Field(default=None, max_length=500)
    topic_code: str = Field(default="unclassified", min_length=1, max_length=64)
    self_reference: bool = False
    assertion_mode: str | None = Field(default=None, max_length=24)
    polarity: str | None = Field(default=None, max_length=24)
    confidence: float = Field(default=0.5, ge=0, le=1)
    is_sensitive: bool = False
    allow_social_recommendation: bool = False
    snapshot_id: str | None = Field(default=None, max_length=36)
    source_occurred_at: datetime | None = None

    @field_validator("content_text")
    @classmethod
    def normalize_content_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("content_text must contain visible characters")
        return normalized


class EvidenceRecord(StrictModel):
    id: str
    user_id: str
    ingestion_key: str
    source: EvidenceSource
    content_text: str
    source_ref: str | None
    topic_code: str
    authored_by_user: bool
    self_reference: bool
    assertion_mode: str | None
    polarity: str | None
    confidence: float = Field(ge=0, le=1)
    consent_version: int = Field(ge=1)
    is_sensitive: bool
    allow_social_recommendation: bool
    snapshot_id: str | None
    source_occurred_at: datetime | None
    created_at: datetime = Field(default_factory=utc_now)


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
    kind: MemoryType
    statement: str
    status: MemoryStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]
    allow_social_recommendation: bool
    version: int = Field(default=1, ge=1)
    supersedes_id: str | None = None
    topic_code: str = "unclassified"
    score: float = Field(default=1.0, ge=0)
    score_updated_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    calibration: CalibrationDecision | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class AgentContextSnapshot(StrictModel):
    id: str
    user_id: str
    lifeform_id: str
    purpose: ContextPurpose
    consent_version: int = Field(ge=1)
    understanding_version: int = Field(ge=0)
    understanding_ids: tuple[str, ...]
    topics: tuple[str, ...]
    stances: tuple[str, ...]
    preferences: tuple[str, ...]
    boundaries: tuple[str, ...]
    social_intents: tuple[str, ...]
    topic_weights: dict[str, float] = Field(default_factory=dict)
    long_term_topic_weights: dict[str, float] = Field(default_factory=dict)
    calibration: CalibrationDecision | None = None
    rule_version: str = "memory.v1"
    content_hash: str = ""
    excluded_understanding_ids: tuple[str, ...] = ()
    evidence_cutoff_at: datetime
    created_at: datetime = Field(default_factory=utc_now)


class Relationship(StrictModel):
    """A factual pair-exploration read model used by the relationship curtain.

    The user-facing page keeps the familiar name ``Relationship``. ``status``
    only controls whether future encounters are allowed; observations must come
    from encounter events and never from an inferred emotional stage.
    """

    id: str
    lifeform_ids: tuple[str, str]
    status: RelationshipStatus
    island_id: str
    headline: str
    shared_experiences: tuple[str, ...]
    encounter_count: int = Field(ge=0)
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
    status: EncounterStatus
    turns: tuple[EncounterTurn, ...]
    outcome_summary: str
    relationship_id: str
    shared_memory: str
    return_question: str
    source_mode: Literal["fixture"] = "fixture"
    match_reason: str = ""
    actor_snapshot_id: str | None = None
    companion_snapshot_id: str | None = None
    companion_is_demo: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)


class UserDecision(StrictModel):
    id: str
    encounter_id: str
    user_id: str
    decision: UserDecisionKind
    decided_at: datetime = Field(default_factory=utc_now)


class Connection(StrictModel):
    id: str
    relationship_id: str
    status: ConnectionStatus
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(StrictModel):
    id: str
    channel_id: str
    sender_user_id: str
    content: str = Field(min_length=1, max_length=4000)
    status: MessageStatus = MessageStatus.SENT
    created_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = None


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
    context_snapshot_id: str | None = None
    matching_status: Literal["waiting", "matched", "paused", "cooldown", "failed"] = "waiting"
    match_reason: str = ""
    encounter_id: str | None = None
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
