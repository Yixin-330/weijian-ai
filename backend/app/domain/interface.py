from __future__ import annotations

from typing import Protocol

from .models import (
    CalibrationRequest,
    Encounter,
    EvidenceIngestRequest,
    EvidenceRecord,
    AgentContextSnapshot,
    ContextPurpose,
    ConsentChange,
    UnderstandingChange,
    ExplorationSettings,
    EncounterDecisionRequest,
    Lifeform,
    Memory,
    OnboardingRequest,
    Relationship,
    TriggerType,
    WorldReadModel,
    WorldTick,
)


class Experience(Protocol):
    """Stable interface shared by the in-memory and MySQL adapters."""

    def bootstrap_demo(self) -> WorldReadModel: ...

    def onboard(
        self, request: OnboardingRequest, *, idempotency_key: str
    ) -> WorldReadModel: ...

    def get_world(self, user_id: str) -> WorldReadModel: ...

    def get_exploration(self, user_id: str) -> dict: ...

    def update_exploration(self, user_id: str, request: ExplorationSettings) -> dict: ...

    def decide_encounter(self, encounter_id: str, request: EncounterDecisionRequest,
                         *, idempotency_key: str) -> dict: ...

    def get_lifeform(self, lifeform_id: str) -> Lifeform: ...

    def get_relationship(self, relationship_id: str) -> Relationship: ...

    def get_encounter(self, encounter_id: str) -> Encounter: ...

    def get_tick_encounter(self, tick_id: str) -> Encounter: ...

    def get_tick(self, tick_id: str) -> WorldTick: ...

    def ingest_evidence(
        self, user_id: str, request: EvidenceIngestRequest
    ) -> EvidenceRecord: ...

    def get_evidence(self, evidence_id: str, *, user_id: str) -> EvidenceRecord: ...

    def calibrate_memory(self, memory_id: str, request: CalibrationRequest) -> Memory: ...

    def derive_understandings(self, user_id: str) -> tuple[Memory, ...]: ...

    def change_understanding(self, memory_id: str, request: UnderstandingChange) -> Memory: ...

    def change_memory_consent(self, user_id: str, request: ConsentChange) -> dict: ...

    def create_context_snapshot(self, user_id: str,
        purpose: ContextPurpose = ContextPurpose.EXPLORATION) -> AgentContextSnapshot: ...

    def get_context_snapshot(self, snapshot_id: str, *, user_id: str) -> AgentContextSnapshot: ...

    def understanding_history(self, memory_id: str, *, user_id: str) -> tuple[dict, ...]: ...

    def run_world_tick(
        self,
        *,
        user_id: str,
        trigger_type: TriggerType,
        idempotency_key: str,
    ) -> WorldTick: ...

    def check_ready(self) -> bool: ...

    def list_tick_candidates(self, *, limit: int = 1000) -> tuple[str, ...]: ...

    def close(self) -> None: ...
