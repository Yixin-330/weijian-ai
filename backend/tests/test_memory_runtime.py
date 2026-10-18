from datetime import timedelta

import pytest
from sqlalchemy import create_engine

from app.domain.errors import Conflict, NotFound
from app.domain.experience import ExperienceModule
from app.domain.models import (CalibrationRequest, ConsentChange, ContextPurpose,
    EvidenceIngestRequest, UnderstandingChange, TriggerType, utc_now)
from app.domain.memory_layer import context_snapshot
from app.storage.mysql import MySqlExperienceModule
from app.storage.schema import metadata
from tests.test_evidence_ingestion import onboarding_request


@pytest.fixture(params=["memory", "sql"])
def module(request, tmp_path):
    if request.param == "memory":
        module = ExperienceModule()
    else:
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'memory.db'}")
        metadata.create_all(engine)
        module = MySqlExperienceModule(engine)
    yield module
    module.close()


def test_calibration_snapshot_tick_and_replay(module):
    world = module.onboard(onboarding_request(), idempotency_key="runtime")
    memory = next(m for m in world.memories if m.status == "candidate")
    before = module.create_context_snapshot(world.user.id)
    calibrated = module.calibrate_memory(memory.id, CalibrationRequest(
        user_id=world.user.id, decision="opposes", allow_social_recommendation=False))
    assert calibrated.version == 2
    assert len(calibrated.evidence_ids) == 2
    after = module.create_context_snapshot(world.user.id)
    assert before.id != after.id
    assert after.calibration == "opposes"
    assert module.get_context_snapshot(before.id, user_id=world.user.id) == before
    tick = module.run_world_tick(user_id=world.user.id, trigger_type=TriggerType.MANUAL,
                                idempotency_key="snapshot-tick")
    snapshot = module.get_context_snapshot(tick.context_snapshot_id, user_id=world.user.id)
    assert memory.id in snapshot.understanding_ids
    assert snapshot.calibration == "opposes"
    assert module.understanding_history(memory.id, user_id=world.user.id)[0][
        "revision_payload"]["before"]["status"] == "candidate"


def test_permissions_deletion_and_revocation_filter_next_snapshot(module):
    world = module.onboard(onboarding_request(), idempotency_key="permissions")
    memory = world.memories[0]
    private = module.change_understanding(memory.id, UnderstandingChange(
        user_id=world.user.id, operation="permission", expected_version=1,
        allow_social_recommendation=False))
    assert memory.id in module.create_context_snapshot(world.user.id).understanding_ids
    assert memory.id not in module.create_context_snapshot(world.user.id,
        ContextPurpose.SOCIAL_RECOMMENDATION).understanding_ids
    module.change_understanding(memory.id, UnderstandingChange(user_id=world.user.id,
        operation="delete", expected_version=private.version))
    assert memory.id not in module.create_context_snapshot(world.user.id).understanding_ids
    module.change_memory_consent(world.user.id, ConsentChange(
        memory_inference=False, social_recommendation=False))
    assert module.create_context_snapshot(world.user.id).understanding_ids == ()


def test_edit_supersedes_and_version_conflicts_do_not_overwrite(module):
    world = module.onboard(onboarding_request(), idempotency_key="edit")
    memory = world.memories[0]
    new = module.change_understanding(memory.id, UnderstandingChange(
        user_id=world.user.id, operation="edit", expected_version=1,
        statement="我正在关注选择，并没有倾向冒险。"))
    assert new.id != memory.id and new.supersedes_id == memory.id
    snapshot = module.create_context_snapshot(world.user.id)
    assert memory.id not in snapshot.understanding_ids
    assert new.id in snapshot.understanding_ids
    assert len(module.understanding_history(new.id, user_id=world.user.id)) == 1
    with pytest.raises(Conflict):
        module.change_understanding(memory.id, UnderstandingChange(
            user_id=world.user.id, operation="delete", expected_version=1))
    with pytest.raises(NotFound):
        module.get_context_snapshot(snapshot.id, user_id="someone-else")


def test_candidate_generation_is_idempotent_and_browsing_cannot_create_stance(module):
    world = module.onboard(onboarding_request(), idempotency_key="derive")
    for index in range(12):
        module.ingest_evidence(world.user.id, EvidenceIngestRequest(
            ingestion_key=f"browse:{index}", source="in_app_browse",
            content_text="AI陪伴会让人孤独吗", topic_code="ai_and_loneliness"))
    assert module.derive_understandings(world.user.id) == ()
    module.ingest_evidence(world.user.id, EvidenceIngestRequest(
        ingestion_key="authored:ai", source="in_app_input",
        content_text="我最近想知道AI陪伴和真实关系如何共存"))
    additions = module.derive_understandings(world.user.id)
    assert len(additions) == 1 and additions[0].kind == "topic"
    assert len(additions[0].evidence_ids) == 13
    assert module.derive_understandings(world.user.id) == ()


def test_rejected_candidate_cannot_resurrect_on_rederive(module):
    world = module.onboard(onboarding_request(), idempotency_key="reject")
    memory = next(m for m in world.memories if m.status == "candidate")
    module.calibrate_memory(memory.id, CalibrationRequest(user_id=world.user.id,
        decision="wrong"))
    assert module.derive_understandings(world.user.id) == ()
    assert memory.id not in module.create_context_snapshot(world.user.id).understanding_ids


def test_decay_and_recent_expiry_are_deterministic_without_mutating_storage(module):
    world = module.onboard(onboarding_request(), idempotency_key="decay")
    memory = next(m for m in world.memories if m.status == "candidate")
    recent = module.calibrate_memory(memory.id, CalibrationRequest(
        user_id=world.user.id, decision="recent"))
    with module._memory_unit(world.user.id) as unit:
        kwargs = dict(user_id=unit.user_id, lifeform_id=unit.lifeform_id,
            consent_version=unit.consent_version, purpose=ContextPurpose.EXPLORATION,
            memories=(recent,), evidence=tuple(unit.evidence.values()),
            memory_enabled=True, social_enabled=True, now=utc_now())
        first = context_snapshot(**kwargs)
        assert context_snapshot(**kwargs) == first
        assert first.long_term_topic_weights == {}
        kwargs["now"] += timedelta(days=15)
        assert context_snapshot(**kwargs).understanding_ids == ()


def test_global_revoke_applies_to_next_tick_and_private_evidence_can_be_authorized(module):
    request = onboarding_request().model_copy(update={"allow_social_recommendation": False})
    world = module.onboard(request, idempotency_key="authorization")
    memory = world.memories[0]
    module.change_memory_consent(world.user.id, ConsentChange(
        memory_inference=True, social_recommendation=True))
    assert module.create_context_snapshot(world.user.id,
        ContextPurpose.SOCIAL_RECOMMENDATION).understanding_ids == ()
    module.change_understanding(memory.id, UnderstandingChange(user_id=world.user.id,
        operation="permission", expected_version=1, allow_social_recommendation=True))
    assert memory.id in module.create_context_snapshot(world.user.id,
        ContextPurpose.SOCIAL_RECOMMENDATION).understanding_ids
    module.change_memory_consent(world.user.id, ConsentChange(
        memory_inference=False, social_recommendation=False))
    tick = module.run_world_tick(user_id=world.user.id, trigger_type=TriggerType.MANUAL,
                                idempotency_key="revoked-tick")
    snapshot = module.get_context_snapshot(tick.context_snapshot_id, user_id=world.user.id)
    assert snapshot.understanding_ids == ()
    assert snapshot.consent_version == 3


def test_sensitive_understanding_cannot_be_social_even_after_explicit_permission(module):
    world = module.onboard(onboarding_request(), idempotency_key="sensitive")
    module.ingest_evidence(world.user.id, EvidenceIngestRequest(
        ingestion_key="sensitive:1", source="in_app_input", is_sensitive=True,
        content_text="我对于AI陪伴的私人经历", allow_social_recommendation=True))
    memory = module.derive_understandings(world.user.id)[0]
    module.change_understanding(memory.id, UnderstandingChange(user_id=world.user.id,
        operation="permission", expected_version=1, allow_social_recommendation=True))
    assert memory.id in module.create_context_snapshot(world.user.id).understanding_ids
    assert memory.id not in module.create_context_snapshot(world.user.id,
        ContextPurpose.SOCIAL_RECOMMENDATION).understanding_ids


def test_permission_revision_preserves_last_calibration(module):
    world = module.onboard(onboarding_request(), idempotency_key="retain-calibration")
    old = world.memories[0]
    calibrated = module.calibrate_memory(old.id, CalibrationRequest(
        user_id=world.user.id, decision="recent"))
    module.change_understanding(old.id, UnderstandingChange(user_id=world.user.id,
        operation="permission", expected_version=calibrated.version))
    assert module.create_context_snapshot(world.user.id).calibration == "recent"


def test_adapters_use_same_snapshot_policy_after_restart(tmp_path):
    path = tmp_path / "adapter-parity.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    metadata.create_all(engine)
    local, persistent = ExperienceModule(), MySqlExperienceModule(engine)
    for adapter in (local, persistent):
        world = adapter.onboard(onboarding_request(), idempotency_key="same-user")
        target = next(m for m in world.memories if m.status == "candidate")
        adapter.calibrate_memory(target.id, CalibrationRequest(
            user_id=world.user.id, decision="opposes"))
    persistent.close()
    persistent = MySqlExperienceModule(create_engine(f"sqlite+pysqlite:///{path}"))
    first = local.create_context_snapshot(world.user.id)
    second = persistent.create_context_snapshot(world.user.id)
    assert first.understanding_ids == second.understanding_ids
    assert first.calibration == second.calibration
    assert first.topic_weights == second.topic_weights
    assert first.long_term_topic_weights == second.long_term_topic_weights
    ticks = [adapter.run_world_tick(user_id=world.user.id,
        trigger_type=TriggerType.MANUAL, idempotency_key="same-tick")
        for adapter in (local, persistent)]
    assert ticks[0].selected_island_id == ticks[1].selected_island_id
    stored = persistent.get_context_snapshot(ticks[1].context_snapshot_id,
                                             user_id=world.user.id)
    persistent.close()
    restarted = MySqlExperienceModule(create_engine(f"sqlite+pysqlite:///{path}"))
    assert restarted.get_context_snapshot(stored.id, user_id=world.user.id) == stored
    restarted.close()
