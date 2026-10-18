"""Atomic owner-scoped persistence for shared M1 use cases."""
from contextlib import contextmanager

from sqlalchemy import insert, select, update

from app.domain.errors import NotFound
from app.domain.memory_service import MemoryService, MemoryUnit
from app.domain.models import AgentContextSnapshot, utc_now
from .schema import (agent_context_snapshots, evidence, lifeforms, memories,
    memory_evidence, memory_revisions, user_consents, users, platform_import_snapshots)


class SqlMemoryService(MemoryService):
    def _read_memory_unit(self, connection, user_id):
        user = connection.execute(select(users).where(users.c.id == user_id)
            .with_for_update()).mappings().first()
        lifeform = connection.execute(select(lifeforms)
            .where(lifeforms.c.user_id == user_id)).mappings().first()
        if user is None or lifeform is None:
            raise NotFound("user not found")
        evidence_rows = connection.execute(select(evidence)
            .where(evidence.c.user_id == user_id)).mappings().all()
        active_sources = set(connection.execute(select(platform_import_snapshots.c.id)
            .where(platform_import_snapshots.c.user_id == user_id,
                   platform_import_snapshots.c.status == "active")).scalars())
        evidence_rows = [r for r in evidence_rows if r["snapshot_id"] is None
                         or r["snapshot_id"] in active_sources]
        memory_rows = connection.execute(select(memories)
            .where(memories.c.lifeform_id == lifeform["id"])).mappings().all()
        scopes = dict(connection.execute(select(user_consents.c.scope,
            user_consents.c.enabled).where(user_consents.c.user_id == user_id)).all())
        return MemoryUnit(user_id, lifeform["id"], user["consent_version"],
            {r["id"]: self._evidence_from_row(r) for r in evidence_rows},
            {r["id"]: self._memory_from_row(connection, r) for r in memory_rows},
            scopes.get("memory_inference", True),
            scopes.get("social_recommendation", user_id == "user-lumi"))

    @contextmanager
    def _memory_unit(self, user_id):
        with self._engine.begin() as connection:
            unit = self._read_memory_unit(connection, user_id)
            previous_memories = dict(unit.memories)
            previous_evidence = set(unit.evidence)
            previous_consent = unit.consent_version
            yield unit
            for eid in sorted(set(unit.evidence) - previous_evidence):
                connection.execute(insert(evidence).values(
                    **self._evidence_values(unit.evidence[eid])))
            for mid, memory in unit.memories.items():
                if previous_memories.get(mid) == memory:
                    continue
                values = dict(lifeform_id=memory.lifeform_id,
                    memory_type=memory.kind.value, statement=memory.statement,
                    status=memory.status.value, confidence=memory.confidence,
                    importance=0.7, score=memory.score,
                    score_updated_at=memory.score_updated_at,
                    allow_social_recommendation=memory.allow_social_recommendation,
                    version=memory.version, supersedes_memory_id=memory.supersedes_id,
                    topic_code=memory.topic_code, updated_at=memory.updated_at,
                    expires_at=memory.expires_at)
                if mid in previous_memories:
                    connection.execute(update(memories).where(memories.c.id == mid)
                        .values(**values))
                else:
                    connection.execute(insert(memories).values(id=mid,
                        created_at=memory.updated_at, **values))
                old_refs = set(previous_memories[mid].evidence_ids) if mid in previous_memories else set()
                for eid in set(memory.evidence_ids) - old_refs:
                    connection.execute(insert(memory_evidence).values(memory_id=mid,
                        evidence_id=eid, contribution=1 / len(memory.evidence_ids)))
            for revision in unit.revisions:
                connection.execute(insert(memory_revisions).values(**revision))
            if previous_consent != unit.consent_version:
                connection.execute(update(users).where(users.c.id == user_id)
                    .values(consent_version=unit.consent_version, updated_at=utc_now()))
                for scope, enabled in (("memory_inference", unit.memory_enabled),
                                        ("social_recommendation", unit.social_enabled)):
                    existing = connection.execute(select(user_consents).where(
                        user_consents.c.user_id == user_id,
                        user_consents.c.scope == scope)).first()
                    values = dict(enabled=enabled, version=unit.consent_version,
                                  changed_at=utc_now())
                    if existing:
                        connection.execute(update(user_consents).where(
                            user_consents.c.user_id == user_id,
                            user_consents.c.scope == scope).values(**values))
                    else:
                        connection.execute(insert(user_consents).values(user_id=user_id,
                            scope=scope, **values))
            if unit.memories != previous_memories or previous_consent != unit.consent_version:
                self._write_audit(connection, event_type="memory.context_changed",
                    actor_id=user_id, subject_id=unit.lifeform_id,
                    details={"consent_version": unit.consent_version,
                        "memory_inference": unit.memory_enabled,
                        "social_recommendation": unit.social_enabled,
                        "revision_count": len(unit.revisions), "rule_version": "memory.v1"},
                    occurred_at=utc_now())

    def _save_snapshot_in(self, connection, snapshot):
        row = connection.execute(select(agent_context_snapshots)
            .where(agent_context_snapshots.c.id == snapshot.id)).mappings().first()
        if row:
            return AgentContextSnapshot.model_validate(row["context_payload"])
        connection.execute(insert(agent_context_snapshots).values(
            id=snapshot.id, user_id=snapshot.user_id, lifeform_id=snapshot.lifeform_id,
            purpose=snapshot.purpose.value, consent_version=snapshot.consent_version,
            understanding_version=snapshot.understanding_version,
            understanding_ids=list(snapshot.understanding_ids),
            context_payload=snapshot.model_dump(mode="json"),
            evidence_cutoff_at=snapshot.evidence_cutoff_at, created_at=snapshot.created_at))
        return snapshot

    def _save_snapshot(self, snapshot):
        with self._engine.begin() as connection:
            connection.execute(select(users.c.id).where(users.c.id == snapshot.user_id)
                .with_for_update()).first()
            return self._save_snapshot_in(connection, snapshot)

    def _load_snapshot(self, snapshot_id, *, user_id):
        with self._engine.connect() as connection:
            row = connection.execute(select(agent_context_snapshots).where(
                agent_context_snapshots.c.id == snapshot_id,
                agent_context_snapshots.c.user_id == user_id)).mappings().first()
            if row is None:
                raise NotFound("context snapshot not found")
            return AgentContextSnapshot.model_validate(row["context_payload"])

    def _memory_history(self, memory_id, *, user_id):
        with self._engine.connect() as connection:
            return tuple(dict(r) for r in connection.execute(select(memory_revisions)
                .where(memory_revisions.c.memory_id == memory_id,
                       memory_revisions.c.user_id == user_id)
                .order_by(memory_revisions.c.occurred_at)).mappings().all())
