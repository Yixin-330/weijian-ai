"""Memory use cases shared by both storage adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

from .errors import Conflict, NotFound
from .evidence_ingestion import build_evidence_record
from .evidence_policy import MemoryStatus, MemoryType
from .memory_layer import candidates, context_snapshot, stable_id
from .models import (CalibrationRequest, ConsentChange, ContextPurpose,
    EvidenceIngestRequest, EvidenceRecord, Memory, UnderstandingChange, utc_now)
from .understanding import calibration_effect
from .onboarding import topic_for_text
from app.core.observability import current_trace_id


@dataclass
class MemoryUnit:
    user_id: str
    lifeform_id: str
    consent_version: int
    evidence: dict[str, EvidenceRecord]
    memories: dict[str, Memory]
    memory_enabled: bool = True
    social_enabled: bool = False
    revisions: list[dict] = field(default_factory=list)


def revise(unit: MemoryUnit, old: Memory, new: Memory, decision: str) -> None:
    unit.memories[new.id] = new
    unit.revisions.append(dict(id=uuid4().hex, memory_id=old.id,
        user_id=unit.user_id, decision=decision, previous_status=old.status.value,
        next_status=new.status.value,
        allow_social_recommendation=new.allow_social_recommendation,
        revision_payload={"before": old.model_dump(mode="json"),
                          "after": new.model_dump(mode="json"),
                          "trace_id": current_trace_id(), "rule_version": "memory.v1"},
        occurred_at=new.updated_at))


def snapshot_for(unit: MemoryUnit, purpose: ContextPurpose):
    return context_snapshot(user_id=unit.user_id, lifeform_id=unit.lifeform_id,
        consent_version=unit.consent_version, purpose=purpose,
        memories=tuple(unit.memories.values()), evidence=tuple(unit.evidence.values()),
        memory_enabled=unit.memory_enabled, social_enabled=unit.social_enabled,
        now=utc_now())


class MemoryService:
    # Adapters provide an atomic, owner-scoped _memory_unit context manager and
    # immutable _save_snapshot/_load_snapshot methods.
    def derive_understandings(self, user_id: str):
        with self._memory_unit(user_id) as unit:
            if not unit.memory_enabled:
                return ()
            additions = candidates(lifeform_id=unit.lifeform_id,
                evidence=tuple(unit.evidence.values()),
                existing=tuple(unit.memories.values()), now=utc_now())
            unit.memories.update({m.id: m for m in additions})
            return additions

    def calibrate_memory(self, memory_id: str, request: CalibrationRequest) -> Memory:
        with self._memory_unit(request.user_id) as unit:
            old = unit.memories.get(memory_id)
            if old is None:
                raise NotFound("understanding not found")
            if old.status not in {MemoryStatus.CANDIDATE, MemoryStatus.CONFIRMED}:
                raise Conflict("only active understandings can be calibrated")
            now = utc_now()
            evidence = build_evidence_record(user_id=unit.user_id,
                consent_version=unit.consent_version,
                request=EvidenceIngestRequest(
                    ingestion_key=f"calibration:{old.id}:{old.version + 1}",
                    source="calibration", content_text=f"{request.decision.value}：{old.statement}",
                    topic_code=old.topic_code, self_reference=True,
                    assertion_mode=request.decision.value,
                    allow_social_recommendation=request.allow_social_recommendation),
                created_at=now)
            unit.evidence[evidence.id] = evidence
            effect = calibration_effect(request.decision)
            # Opposing a statement confirms attention to its topic, never the
            # original stance. Explicit stance edits use the edit operation.
            new = old.model_copy(update=dict(status=effect.status,
                kind=MemoryType.TOPIC if request.decision == "opposes" else old.kind,
                statement=("你仍关注这个议题，但正在反对原观点：" + old.statement[:240]
                    if request.decision == "opposes" else old.statement),
                calibration=request.decision, version=old.version + 1,
                evidence_ids=(*old.evidence_ids, evidence.id), updated_at=now,
                score_updated_at=now,
                expires_at=now + timedelta(days=14) if request.decision == "recent" else None,
                allow_social_recommendation=request.allow_social_recommendation))
            revise(unit, old, new, request.decision.value)
            return new

    def change_understanding(self, memory_id: str, request: UnderstandingChange):
        with self._memory_unit(request.user_id) as unit:
            old = unit.memories.get(memory_id)
            if old is None:
                raise NotFound("understanding not found")
            if old.version != request.expected_version:
                raise Conflict("understanding changed; refresh before saving")
            if old.status in {MemoryStatus.DELETED, MemoryStatus.SUPERSEDED}:
                raise Conflict("understanding is no longer editable")
            now = utc_now()
            if request.operation == "edit":
                if request.statement is None or not request.statement.strip():
                    raise Conflict("an edited statement is required")
                classified = topic_for_text(request.statement)
                edited_topic = classified.value if classified else old.topic_code
                evidence = build_evidence_record(user_id=unit.user_id,
                    consent_version=unit.consent_version,
                    request=EvidenceIngestRequest(
                        ingestion_key=f"edit:{old.id}:{old.version + 1}",
                        source="in_app_input", content_text=request.statement,
                        topic_code=edited_topic, self_reference=True,
                        allow_social_recommendation=request.allow_social_recommendation),
                    created_at=now)
                unit.evidence[evidence.id] = evidence
                revise(unit, old, old.model_copy(update=dict(status=MemoryStatus.SUPERSEDED,
                    version=old.version + 1, updated_at=now)), "edit")
                new = old.model_copy(update=dict(id=stable_id(f"edit:{old.id}:{old.version+1}"),
                    statement=request.statement.strip(), status=MemoryStatus.CONFIRMED,
                    version=1, supersedes_id=old.id, calibration=None,
                    evidence_ids=(evidence.id,), updated_at=now, score_updated_at=now,
                    expires_at=None,
                    topic_code=edited_topic,
                    allow_social_recommendation=request.allow_social_recommendation))
                unit.memories[new.id] = new
                return new
            new = old.model_copy(update=dict(
                status=MemoryStatus.DELETED if request.operation == "delete" else old.status,
                allow_social_recommendation=(False if request.operation == "delete"
                    else request.allow_social_recommendation),
                version=old.version + 1, updated_at=now))
            revise(unit, old, new, request.operation)
            return new

    def change_memory_consent(self, user_id: str, request: ConsentChange):
        with self._memory_unit(user_id) as unit:
            unit.consent_version += 1
            unit.memory_enabled = request.memory_inference
            unit.social_enabled = request.social_recommendation
            return {"consent_version": unit.consent_version, **request.model_dump()}

    def create_context_snapshot(self, user_id: str, purpose=ContextPurpose.EXPLORATION):
        with self._memory_unit(user_id) as unit:
            snapshot = snapshot_for(unit, ContextPurpose(purpose))
        return self._save_snapshot(snapshot)

    def get_context_snapshot(self, snapshot_id: str, *, user_id: str):
        return self._load_snapshot(snapshot_id, user_id=user_id)

    def understanding_history(self, memory_id: str, *, user_id: str):
        with self._memory_unit(user_id) as unit:
            if memory_id not in unit.memories:
                raise NotFound("understanding not found")
            lineage = []
            current = memory_id
            while current and current not in lineage:
                lineage.append(current)
                current = unit.memories[current].supersedes_id
        rows = [r for mid in reversed(lineage)
                for r in self._memory_history(mid, user_id=user_id)]
        return tuple(sorted(rows, key=lambda r: r["occurred_at"]))
