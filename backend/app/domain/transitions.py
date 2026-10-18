from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from .models import ConnectionStatus, EncounterStatus, RelationshipStatus


ENCOUNTER_TRANSITIONS: Mapping[EncounterStatus, frozenset[EncounterStatus]] = {
    EncounterStatus.QUEUED: frozenset(
        {EncounterStatus.RUNNING, EncounterStatus.DISCARDED}
    ),
    EncounterStatus.RUNNING: frozenset(
        {
            EncounterStatus.COMPLETED,
            EncounterStatus.INVALID,
            EncounterStatus.LEFT,
            EncounterStatus.FAILED,
            EncounterStatus.DISCARDED,
        }
    ),
    EncounterStatus.COMPLETED: frozenset(),
    EncounterStatus.INVALID: frozenset(),
    EncounterStatus.LEFT: frozenset(),
    EncounterStatus.FAILED: frozenset(),
    EncounterStatus.DISCARDED: frozenset(),
}

RELATIONSHIP_TRANSITIONS: Mapping[
    RelationshipStatus, frozenset[RelationshipStatus]
] = {
    RelationshipStatus.ACTIVE: frozenset(
        {RelationshipStatus.ENDED, RelationshipStatus.BLOCKED}
    ),
    RelationshipStatus.ENDED: frozenset(),
    RelationshipStatus.BLOCKED: frozenset(),
}

CONNECTION_TRANSITIONS: Mapping[ConnectionStatus, frozenset[ConnectionStatus]] = {
    ConnectionStatus.WAITING: frozenset(
        {ConnectionStatus.MUTUAL_ACCEPTED, ConnectionStatus.ENDED}
    ),
    ConnectionStatus.MUTUAL_ACCEPTED: frozenset(
        {ConnectionStatus.ACTIVE, ConnectionStatus.ENDED}
    ),
    ConnectionStatus.ACTIVE: frozenset({ConnectionStatus.ENDED}),
    ConnectionStatus.ENDED: frozenset(),
}


def require_transition(
    current: StrEnum,
    target: StrEnum,
    transitions: Mapping[StrEnum, frozenset[StrEnum]],
) -> None:
    """Reject state jumps before persistence.

    The LLM never calls this function and never commits state. It may only
    propose an action; deterministic application code owns every transition.
    """

    if target not in transitions.get(current, frozenset()):
        raise ValueError(f"illegal transition: {current.value} -> {target.value}")
