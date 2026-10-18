"""Canonical construction rules for append-only growth evidence.

Every producer uses this module before persistence.  It derives authorship from
the source vocabulary (rather than trusting callers), enforces the boundary
between platform snapshots and in-app events, and applies the sensitive-data
social-use rule at the write boundary.  Candidate-understanding generation is a
separate M1 stage and deliberately does not live here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .errors import Conflict
from .evidence_policy import EvidenceSource
from .models import EvidenceIngestRequest, EvidenceRecord, utc_now


PLATFORM_SOURCES: frozenset[EvidenceSource] = frozenset(
    {
        EvidenceSource.AUTHORED_CONTENT,
        EvidenceSource.FAVLIST_NAMING,
        EvidenceSource.FAVORITE_ITEM,
        EvidenceSource.FOLLOWEE_HEADLINE,
    }
)

IN_APP_SOURCES: frozenset[EvidenceSource] = frozenset(EvidenceSource) - PLATFORM_SOURCES

# Authorship and stance eligibility are intentionally different.  A collection
# name and returned-question reply are user-authored facts, but the stance
# whitelist remains the stricter rule in evidence_policy.py.
USER_AUTHORED_SOURCES: frozenset[EvidenceSource] = frozenset(
    {
        EvidenceSource.AUTHORED_CONTENT,
        EvidenceSource.FAVLIST_NAMING,
        EvidenceSource.IN_APP_INPUT,
        EvidenceSource.CALIBRATION,
        EvidenceSource.RETURNED_QUESTION_REPLY,
    }
)


def evidence_id_for(user_id: str, ingestion_key: str) -> str:
    """Stable ID for an idempotent source event."""

    return uuid5(
        NAMESPACE_URL, f"weijian:evidence:{user_id}:{ingestion_key}"
    ).hex


def build_evidence_record(
    *,
    user_id: str,
    consent_version: int,
    request: EvidenceIngestRequest,
    evidence_id: str | None = None,
    created_at: datetime | None = None,
) -> EvidenceRecord:
    """Validate and normalize one source fact without touching persistence."""

    if consent_version < 1:
        raise Conflict("consent_version must be at least 1")
    if request.source in PLATFORM_SOURCES and request.snapshot_id is None:
        raise Conflict("platform evidence must reference its immutable import snapshot")
    if request.source in IN_APP_SOURCES and request.snapshot_id is not None:
        raise Conflict("in-app evidence cannot reference a platform import snapshot")

    return EvidenceRecord(
        id=evidence_id or evidence_id_for(user_id, request.ingestion_key),
        user_id=user_id,
        ingestion_key=request.ingestion_key,
        source=request.source,
        content_text=request.content_text,
        source_ref=request.source_ref,
        topic_code=request.topic_code,
        authored_by_user=request.source in USER_AUTHORED_SOURCES,
        self_reference=request.self_reference,
        assertion_mode=request.assertion_mode,
        polarity=request.polarity,
        confidence=request.confidence,
        consent_version=consent_version,
        is_sensitive=request.is_sensitive,
        # Sensitive evidence may still support private exploration, but never
        # enters social recommendation automatically.
        allow_social_recommendation=(
            request.allow_social_recommendation and not request.is_sensitive
        ),
        snapshot_id=request.snapshot_id,
        source_occurred_at=request.source_occurred_at,
        created_at=created_at or utc_now(),
    )


def same_idempotent_fact(
    existing: EvidenceRecord, candidate: EvidenceRecord
) -> bool:
    """Whether a retried ingestion key carries the same immutable fact."""

    comparable = (
        "user_id",
        "ingestion_key",
        "source",
        "content_text",
        "source_ref",
        "topic_code",
        "self_reference",
        "assertion_mode",
        "polarity",
        "confidence",
        "is_sensitive",
        "allow_social_recommendation",
        "snapshot_id",
        "source_occurred_at",
    )
    return all(getattr(existing, name) == getattr(candidate, name) for name in comparable)
