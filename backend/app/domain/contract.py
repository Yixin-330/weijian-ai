from __future__ import annotations

from typing import Any

from app.islands import IslandSet, get_islands

from .models import (
    ConnectionStatus,
    ContextPurpose,
    EncounterAction,
    EncounterStatus,
    RelationshipStatus,
    UserDecisionKind,
)
from .evidence_policy import EvidenceSource, MemoryStatus, MemoryType


DOMAIN_CONTRACT_VERSION = "m2.v1"


def _values(enum_type: type) -> list[str]:
    return [item.value for item in enum_type]


def build_domain_contract(islands: IslandSet | None = None) -> dict[str, Any]:
    """Public vocabulary for clients and contract tests.

    Values are derived from the actual domain enums and active island fixture,
    so documentation endpoints cannot silently diverge from runtime behavior.
    """

    resolved = islands or get_islands()
    return {
        "version": DOMAIN_CONTRACT_VERSION,
        "island_ids": list(resolved.ids),
        "encounter_statuses": _values(EncounterStatus),
        "encounter_actions": _values(EncounterAction),
        "relationship_statuses": _values(RelationshipStatus),
        "user_decisions": _values(UserDecisionKind),
        "connection_statuses": _values(ConnectionStatus),
        "evidence_sources": _values(EvidenceSource),
        "understanding_types": _values(MemoryType),
        "understanding_statuses": _values(MemoryStatus),
        "context_purposes": _values(ContextPurpose),
        "matching": {"rule_version": "matching.v1", "max_candidates": 30,
            "encounter_cooldown_seconds": 600, "pair_cooldown_seconds": 86400,
            "distance_cooldown_seconds": 172800},
    }
