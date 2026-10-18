from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.domain import (
    CalibrationRequest,
    EvidenceIngestRequest,
    Experience,
    OnboardingRequest,
    TickCommand,
    TriggerType,
)
from app.domain.island_catalog import IslandCatalog
from app.domain.contract import build_domain_contract
from app.domain.models import (UnderstandingChange, ConsentChange, ContextPurpose,
    ExplorationSettings, EncounterDecisionRequest)
from app.islands import FixtureError, IslandSet
from app.scheduling.interface import WorldScheduler


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=64)
    trigger_type: TriggerType = TriggerType.MANUAL


def _island_read_model(snapshot: IslandSet) -> dict:
    return {
        "fixture_version": snapshot.fixture_version,
        "fetched_on": snapshot.fetched_on,
        "islands": [
            {
                "island_id": island.island_id,
                "island_name": island.island_name,
                "topic_code": island.topic_code,
                "display_order": island.display_order,
                "tension_axis": island.tension_axis,
                "source": {
                    "platform": island.source.platform,
                    "question_id": island.source.question_id,
                    "question_title": island.source.question_title,
                    "question_url": island.source.question_url,
                },
                "viewpoint_count": len(island.safe_materials()),
                "viewpoint_materials": [
                    {
                        "material_id": material.material_id,
                        "summary": material.summary,
                        "source_url": material.source_url,
                    }
                    for material in island.safe_materials()
                ],
                "scene": island.scene,
                "events": island.events,
                "authored_status": island.authored_status,
                "design_ready": island.design_ready,
            }
            for island in snapshot.islands
        ],
    }


def build_router(
    module: Experience,
    island_catalog: IslandCatalog,
    settings: Settings,
    scheduler: WorldScheduler,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/islands")
    def list_islands():
        try:
            return _island_read_model(island_catalog.list_islands())
        except FixtureError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @router.get("/meta/domain-contract")
    def get_domain_contract():
        try:
            return build_domain_contract(island_catalog.list_islands())
        except FixtureError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    @router.post("/demo/bootstrap")
    def bootstrap_demo():
        return module.bootstrap_demo()

    @router.post("/onboarding", status_code=status.HTTP_201_CREATED)
    def onboard(
        body: OnboardingRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ):
        return module.onboard(body, idempotency_key=idempotency_key)

    @router.get("/users/{user_id}/world")
    def get_world(user_id: str):
        return module.get_world(user_id)

    @router.get("/users/{user_id}/exploration")
    def get_exploration(user_id: str):
        return module.get_exploration(user_id)

    @router.post("/users/{user_id}/exploration")
    def update_exploration(user_id: str, body: ExplorationSettings):
        return module.update_exploration(user_id, body)

    @router.post("/encounters/{encounter_id}/decisions")
    def decide_encounter(encounter_id: str, body: EncounterDecisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
        return module.decide_encounter(encounter_id, body, idempotency_key=idempotency_key)

    @router.get("/lifeforms/{lifeform_id}")
    def get_lifeform(lifeform_id: str):
        return module.get_lifeform(lifeform_id)

    @router.post(
        "/users/{user_id}/evidence",
        status_code=status.HTTP_201_CREATED,
    )
    def ingest_evidence(user_id: str, body: EvidenceIngestRequest):
        """Append one normalized source fact; retries reuse the ingestion key."""
        return module.ingest_evidence(user_id, body)

    @router.get("/users/{user_id}/evidence/{evidence_id}")
    def get_evidence(user_id: str, evidence_id: str):
        return module.get_evidence(evidence_id, user_id=user_id)

    @router.post("/users/{user_id}/understandings/derive")
    def derive_understandings(user_id: str):
        return {"items": module.derive_understandings(user_id)}

    @router.post("/understandings/{understanding_id}/changes")
    def change_understanding(understanding_id: str, body: UnderstandingChange):
        return module.change_understanding(understanding_id, body)

    @router.get("/understandings/{understanding_id}/history")
    def understanding_history(understanding_id: str, user_id: str):
        return {"items": module.understanding_history(understanding_id, user_id=user_id)}

    @router.post("/users/{user_id}/memory-consent")
    def change_memory_consent(user_id: str, body: ConsentChange):
        return module.change_memory_consent(user_id, body)

    @router.post("/users/{user_id}/context-snapshots")
    def create_context_snapshot(user_id: str, purpose: ContextPurpose = ContextPurpose.EXPLORATION):
        return module.create_context_snapshot(user_id, purpose)

    @router.get("/users/{user_id}/context-snapshots/{snapshot_id}")
    def get_context_snapshot(user_id: str, snapshot_id: str):
        return module.get_context_snapshot(snapshot_id, user_id=user_id)

    @router.get("/lifeforms/{lifeform_id}/understandings")
    def list_understandings(lifeform_id: str, user_id: str):
        """Product-facing read alias for the MVP candidate-understanding layer."""
        world = module.get_world(user_id)
        if world.lifeform.id != lifeform_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lifeform not found")
        return {"items": world.memories}

    @router.post("/memories/{memory_id}/calibrations")
    def calibrate_memory(memory_id: str, body: CalibrationRequest):
        return module.calibrate_memory(memory_id, body)

    @router.post("/understandings/{understanding_id}/calibrations")
    def calibrate_understanding(
        understanding_id: str, body: CalibrationRequest
    ):
        """Product-facing write alias; persistence keeps the existing memory ID."""
        return module.calibrate_memory(understanding_id, body)

    @router.post("/world/ticks", status_code=status.HTTP_202_ACCEPTED)
    async def run_tick(
        body: TickRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=120),
        demo_admin_token: str = Header(alias="X-Demo-Admin-Token"),
    ):
        if demo_admin_token != settings.demo_admin_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid demo admin token")
        return await scheduler.submit(
            TickCommand(
                user_id=body.user_id,
                trigger_type=body.trigger_type,
                idempotency_key=f"manual:{idempotency_key}",
            )
        )

    @router.post(
        "/users/{user_id}/next-action",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def run_user_next_action(
        user_id: str,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=1, max_length=120
        ),
    ):
        """Advance one user's lifeform after an explicit in-product action.

        The admin tick remains protected for cron and demos.  This endpoint is
        the MVP user path; production authentication will replace the explicit
        user id before launch.
        """
        return await scheduler.submit(
            TickCommand(
                user_id=user_id,
                trigger_type=TriggerType.MANUAL,
                idempotency_key=f"user-action:{idempotency_key}",
            )
        )

    @router.get("/world/tick-jobs/{job_id}")
    async def get_tick_job(job_id: str):
        return await scheduler.get(job_id)

    @router.get("/world/ticks/{tick_id}")
    def get_tick(tick_id: str):
        return module.get_tick(tick_id)

    @router.get("/world/ticks/{tick_id}/encounter")
    def get_tick_encounter(tick_id: str):
        return module.get_tick_encounter(tick_id)

    @router.get("/encounters/{encounter_id}")
    def get_encounter(encounter_id: str):
        return module.get_encounter(encounter_id)

    @router.get("/relationships/{relationship_id}")
    def get_relationship(relationship_id: str):
        return module.get_relationship(relationship_id)

    return router
