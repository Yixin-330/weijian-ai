from __future__ import annotations

from typing import Protocol

from .models import (
    CalibrationRequest,
    Encounter,
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

    def get_lifeform(self, lifeform_id: str) -> Lifeform: ...

    def get_relationship(self, relationship_id: str) -> Relationship: ...

    def get_encounter(self, encounter_id: str) -> Encounter: ...

    def get_tick_encounter(self, tick_id: str) -> Encounter: ...

    def get_tick(self, tick_id: str) -> WorldTick: ...

    def calibrate_memory(self, memory_id: str, request: CalibrationRequest) -> Memory: ...

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
