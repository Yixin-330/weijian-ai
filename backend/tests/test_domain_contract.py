from __future__ import annotations

import pytest

from app.core.config import Settings
from app.domain.contract import DOMAIN_CONTRACT_VERSION, build_domain_contract
from app.domain.experience import ExperienceModule
from app.domain.island_catalog import FixtureIslandCatalog
from app.domain.models import (
    ConnectionStatus,
    EncounterStatus,
    RelationshipStatus,
    UserDecisionKind,
)
from app.domain.transitions import (
    CONNECTION_TRANSITIONS,
    ENCOUNTER_TRANSITIONS,
    RELATIONSHIP_TRANSITIONS,
    require_transition,
)
from app.main import create_app


def test_m0_contract_has_canonical_islands_and_no_emotional_relationship_stages():
    contract = build_domain_contract()

    assert contract["version"] == DOMAIN_CONTRACT_VERSION
    assert contract["island_ids"] == ["stability", "intimacy", "ai_loneliness"]
    assert contract["relationship_statuses"] == ["active", "ended", "blocked"]
    assert contract["user_decisions"] == [
        "observe_again",
        "invite",
        "distance",
        "end",
        "block",
    ]
    forbidden = {"noticed", "shared_experience", "cared", "connection_candidate"}
    assert forbidden.isdisjoint(contract["relationship_statuses"])


def test_m1_contract_exposes_evidence_understanding_and_context_vocabularies():
    contract = build_domain_contract()

    assert contract["version"] == "m2.v1"
    assert "in_app_input" in contract["evidence_sources"]
    assert contract["understanding_types"] == [
        "topic",
        "stance",
        "preference",
        "boundary",
        "social_intent",
    ]
    assert contract["understanding_statuses"] == [
        "candidate",
        "confirmed",
        "rejected",
        "superseded",
        "deleted",
    ]
    assert contract["context_purposes"] == [
        "exploration",
        "social_recommendation",
    ]


def test_domain_contract_is_available_to_frontend_clients():
    app = create_app(
        settings=Settings(environment="test", demo_admin_token="test-admin"),
        experience=ExperienceModule(),
        island_catalog=FixtureIslandCatalog(),
    )
    operation = app.openapi()["paths"]["/api/v1/meta/domain-contract"]["get"]
    assert operation["operationId"] == "get_domain_contract_api_v1_meta_domain_contract_get"


def test_state_machines_only_allow_operational_transitions():
    require_transition(
        EncounterStatus.QUEUED,
        EncounterStatus.RUNNING,
        ENCOUNTER_TRANSITIONS,
    )
    require_transition(
        RelationshipStatus.ACTIVE,
        RelationshipStatus.ENDED,
        RELATIONSHIP_TRANSITIONS,
    )
    require_transition(
        ConnectionStatus.WAITING,
        ConnectionStatus.MUTUAL_ACCEPTED,
        CONNECTION_TRANSITIONS,
    )

    with pytest.raises(ValueError, match="illegal transition"):
        require_transition(
            EncounterStatus.COMPLETED,
            EncounterStatus.RUNNING,
            ENCOUNTER_TRANSITIONS,
        )


def test_single_invitation_is_not_an_active_connection():
    assert UserDecisionKind.INVITE.value == "invite"
    assert ConnectionStatus.WAITING != ConnectionStatus.ACTIVE
    assert ConnectionStatus.MUTUAL_ACCEPTED in CONNECTION_TRANSITIONS[
        ConnectionStatus.WAITING
    ]
    assert ConnectionStatus.ACTIVE not in CONNECTION_TRANSITIONS[
        ConnectionStatus.WAITING
    ]
