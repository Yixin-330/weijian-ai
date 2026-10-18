"""Shared, deterministic M1 policy. No network or model calls on writes/reads."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from uuid import NAMESPACE_URL, uuid5

from .evidence_policy import EvidenceSource, MemoryStatus, MemoryType, weight_of
from .models import AgentContextSnapshot, ContextPurpose, EvidenceRecord, Memory
from .onboarding import TOPIC_LABELS, topic_for_text


RULE_VERSION = "memory.v1"


def stable_id(value: str) -> str:
    return uuid5(NAMESPACE_URL, f"weijian:{value}").hex


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def candidates(*, lifeform_id: str, evidence: tuple[EvidenceRecord, ...],
               existing: tuple[Memory, ...], now: datetime) -> tuple[Memory, ...]:
    groups: dict[str, list[EvidenceRecord]] = {}
    excluded_evidence = {eid for m in existing if m.status in {
        MemoryStatus.REJECTED, MemoryStatus.DELETED, MemoryStatus.SUPERSEDED
    } for eid in m.evidence_ids}
    for item in sorted(evidence, key=lambda e: e.id):
        if item.id in excluded_evidence:
            continue
        topic = item.topic_code
        if topic == "unclassified":
            classified = topic_for_text(item.content_text)
            topic = classified.value if classified else topic
        if topic not in {t.value for t in TOPIC_LABELS}:
            continue
        # Calibration belongs to the version it corrects, not to a fresh
        # inference batch; otherwise rejecting a claim could resurrect it.
        if item.source == EvidenceSource.CALIBRATION:
            continue
        groups.setdefault(topic, []).append(item)
    result = []
    for topic, items in sorted(groups.items()):
        refs = tuple(e.id for e in items)
        covered = {eid for m in existing if m.topic_code == topic for eid in m.evidence_ids}
        if set(refs) <= covered:
            continue
        weight = sum(weight_of(e.source) for e in items)
        # Browsing alone never opens an understanding, however often it occurs.
        if weight < 100 or not any(e.authored_by_user for e in items):
            continue
        label = next(label for key, label in TOPIC_LABELS.items() if key.value == topic)
        strongest = max(items, key=lambda e: (weight_of(e.source), e.id))
        confidence = min(0.75, 0.35 + weight / 400)
        result.append(Memory(
            id=stable_id(f"candidate:{lifeform_id}:{topic}:{':'.join(refs)}"),
            lifeform_id=lifeform_id, kind=MemoryType.TOPIC,
            statement=f"你可能正在关注「{label}」；依据：{strongest.content_text[:60]}",
            status=MemoryStatus.CANDIDATE, confidence=confidence,
            evidence_ids=refs, topic_code=topic, score=confidence,
            score_updated_at=now, updated_at=now,
            allow_social_recommendation=all(e.allow_social_recommendation and
                not e.is_sensitive for e in items),
        ))
    return tuple(result)


def context_snapshot(*, user_id: str, lifeform_id: str, consent_version: int,
                     purpose: ContextPurpose, memories: tuple[Memory, ...],
                     evidence: tuple[EvidenceRecord, ...], memory_enabled: bool,
                     social_enabled: bool, now: datetime) -> AgentContextSnapshot:
    by_id = {e.id: e for e in evidence}
    effective: list[Memory] = []
    weights: dict[str, float] = {}
    long_term: dict[str, float] = {}
    for memory in sorted(memories, key=lambda m: m.id):
        if not memory_enabled or memory.status not in {
            MemoryStatus.CANDIDATE, MemoryStatus.CONFIRMED
        } or (memory.expires_at and aware(memory.expires_at) <= now):
            continue
        refs = [by_id[e] for e in memory.evidence_ids if e in by_id]
        if not refs or len(refs) != len(memory.evidence_ids):
            continue
        # A later explicit calibration/permission revision can authorize this
        # understanding's use without rewriting the evidence's original grant.
        # Global authorization and sensitivity remain hard gates.
        if purpose == ContextPurpose.SOCIAL_RECOMMENDATION and (
            not social_enabled or not memory.allow_social_recommendation or
            any(e.is_sensitive or (not e.allow_social_recommendation and
                memory.version == 1) for e in refs)
        ):
            continue
        age_days = max(0, (now - aware(memory.score_updated_at)).total_seconds() / 86400)
        decayed = min(1.0, memory.score) * math.exp(-math.log(2) * age_days / 30)
        if memory.calibration == "opposes":
            decayed *= 0.4
        if decayed < 0.05:
            continue
        effective.append(memory)
        if memory.kind == MemoryType.TOPIC:
            weights[memory.topic_code] = max(weights.get(memory.topic_code, 0), decayed)
            if memory.status == MemoryStatus.CONFIRMED and memory.calibration != "recent":
                long_term[memory.topic_code] = max(long_term.get(memory.topic_code, 0), decayed)
    # Corrections rejected/deleted/superseded never steer through old revisions.
    calibrated = [m for m in effective if m.calibration is not None]
    latest = max(calibrated, key=lambda m: (aware(m.updated_at), m.id)) if calibrated else None
    payload = dict(
        user_id=user_id, lifeform_id=lifeform_id, purpose=purpose,
        consent_version=consent_version,
        understanding_version=sum(m.version for m in memories),
        understanding_ids=tuple(m.id for m in effective),
        topics=tuple(sorted(weights)),
        stances=tuple(m.statement for m in effective if m.kind == MemoryType.STANCE),
        preferences=tuple(m.statement for m in effective if m.kind == MemoryType.PREFERENCE),
        boundaries=tuple(m.statement for m in effective if m.kind == MemoryType.BOUNDARY),
        social_intents=tuple(m.statement for m in effective if m.kind == MemoryType.SOCIAL_INTENT),
        topic_weights={k: round(v, 6) for k, v in sorted(weights.items())},
        long_term_topic_weights={k: round(v, 6) for k, v in sorted(long_term.items())},
        calibration=latest.calibration if latest else None,
        rule_version=RULE_VERSION,
        excluded_understanding_ids=tuple(sorted(m.id for m in memories
            if m.id not in {x.id for x in effective})),
    )
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                               default=str).encode()).hexdigest()
    return AgentContextSnapshot(id=stable_id(f"context:{digest}"),
        content_hash=digest, evidence_cutoff_at=now, created_at=now, **payload)
