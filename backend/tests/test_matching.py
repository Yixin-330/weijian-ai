from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select, update, func

from app.domain.errors import NotFound, Conflict
from app.domain.experience import ExperienceModule
from app.domain.matching import MatchProfile, recall_candidates
from app.domain.models import (OnboardingRequest, ExplorationSettings,
    EncounterDecisionRequest, ConsentChange, TriggerType, utc_now)
from app.storage.mysql import MySqlExperienceModule
from app.storage.schema import metadata, lifeforms, encounters, world_ticks
from app.storage.matching_schema import exploration_states


@pytest.fixture(params=["memory", "sql"])
def module(request, tmp_path):
    if request.param == "memory":
        result = ExperienceModule()
    else:
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'matching.db'}",
                               connect_args={"timeout": 20})
        metadata.create_all(engine)
        result = MySqlExperienceModule(engine)
    yield result
    result.close()


def create(module, key, *, topic="choice_uncertainty", social=True):
    return module.onboard(OnboardingRequest(current_question={
        "choice_uncertainty": "稳定工作还是尝试新的选择？",
        "intimacy_and_autonomy": "如何处理亲密关系中的独立？",
        "ai_and_loneliness": "AI陪伴是否会让人更孤独？"}[topic],
        long_term_topics=(topic,), exploration_style="observe",
        social_pace="shared_experiences", allow_memory_inference=True,
        allow_social_recommendation=social), idempotency_key=key)


def tick(module, world, key):
    return module.run_world_tick(user_id=world.user.id,
        trigger_type=TriggerType.MANUAL, idempotency_key=key)


def set_time(monkeypatch, value):
    monkeypatch.setattr("app.domain.experience.utc_now", lambda: value)
    monkeypatch.setattr("app.storage.mysql.utc_now", lambda: value)


def test_two_real_users_match_with_authorized_snapshot_and_idempotency(module):
    first, second = create(module, "first"), create(module, "second")
    result = tick(module, first, "real-match")
    assert result.matching_status == "matched"
    encounter = module.get_tick_encounter(result.id)
    assert set(encounter.lifeform_ids) == {first.lifeform.id, second.lifeform.id}
    assert encounter.match_reason and not encounter.companion_is_demo
    assert module.get_context_snapshot(encounter.actor_snapshot_id,
        user_id=first.user.id).purpose == "social_recommendation"
    assert module.get_context_snapshot(encounter.companion_snapshot_id,
        user_id=second.user.id).purpose == "social_recommendation"
    assert tick(module, first, "real-match").id == result.id
    assert module.get_exploration(second.user.id)["last_encounter_id"] == encounter.id
    assert tick(module, second, "other-user-same-window").matching_status == "cooldown"


def test_no_users_and_no_consent_do_not_force_encounters(module):
    first = create(module, "alone")
    result = tick(module, first, "alone")
    assert result.matching_status == "waiting" and result.encounter_id is None
    second = create(module, "private", social=False)
    assert tick(module, second, "no-consent").matching_status == "paused"
    assert tick(module, first, "still-alone").matching_status == "waiting"


def test_real_users_do_not_silently_match_demo_partners(module):
    module.bootstrap_demo()
    real = create(module, "no-fake")
    assert tick(module, real, "no-fake").matching_status == "waiting"
    module.update_exploration(real.user.id, ExplorationSettings(allow_demo_partners=True))
    result = tick(module, real, "explicit-demo")
    assert result.matching_status == "matched"
    assert module.get_tick_encounter(result.id).companion_is_demo


def test_cross_island_requires_explicit_travel_permission(module):
    actor = create(module, "cross-actor")
    peer = create(module, "cross-peer", topic="intimacy_and_autonomy")
    assert tick(module, actor, "cannot-teleport").matching_status == "waiting"
    assert module.get_lifeform(peer.lifeform.id).current_island_id == "intimacy"
    module.update_exploration(peer.user.id, ExplorationSettings(allow_cross_island=True))
    result = tick(module, actor, "allowed-to-travel")
    assert result.matching_status == "matched"
    assert module.get_lifeform(peer.lifeform.id).current_island_id == "stability"
    assert "跨岛" in result.match_reason


def test_hard_topic_boundary_and_consent_revoke_are_enforced(module):
    first, second = create(module, "boundary-a"), create(module, "boundary-b")
    module.update_exploration(second.user.id, ExplorationSettings(
        excluded_topics=("choice_uncertainty",)))
    assert tick(module, first, "hard-veto").matching_status == "waiting"
    module.update_exploration(second.user.id, ExplorationSettings())
    module.change_memory_consent(second.user.id, ConsentChange(
        memory_inference=True, social_recommendation=False))
    assert tick(module, first, "revoked").matching_status == "waiting"


@pytest.mark.parametrize("decision", ["distance", "end", "block"])
def test_private_decisions_suppress_both_directions_without_leaking(module, monkeypatch, decision):
    first, second = create(module, "decision-a"), create(module, "decision-b")
    result = tick(module, first, "decision-encounter")
    request = EncounterDecisionRequest(user_id=first.user.id, decision=decision)
    saved = module.decide_encounter(result.encounter_id, request, idempotency_key="private-1")
    assert module.decide_encounter(result.encounter_id, request,
                                   idempotency_key="private-1")["id"] == saved["id"]
    with pytest.raises(Conflict):
        module.decide_encounter(result.encounter_id, request.model_copy(
            update={"decision": "invite"}), idempotency_key="private-1")
    set_time(monkeypatch, utc_now() + timedelta(hours=25))
    next_tick = tick(module, second, "suppressed")
    assert next_tick.matching_status == "waiting"
    assert decision not in next_tick.match_reason
    status = module.get_exploration(second.user.id)
    assert "decision" not in status and "other_user_decision" not in status


def test_pair_cooldown_and_distance_expiry(module, monkeypatch):
    first, second = create(module, "cooldown-a"), create(module, "cooldown-b")
    result = tick(module, first, "first")
    set_time(monkeypatch, utc_now() + timedelta(minutes=11))
    assert tick(module, first, "pair-cooldown").matching_status == "waiting"
    module.decide_encounter(result.encounter_id, EncounterDecisionRequest(
        user_id=first.user.id, decision="distance"), idempotency_key="distance")
    set_time(monkeypatch, utc_now() + timedelta(hours=49))
    assert tick(module, first, "after-expiry").matching_status == "matched"


def test_execution_failure_rolls_back_claims_and_tick(module, monkeypatch):
    first, second = create(module, "failure-a"), create(module, "failure-b")
    def fail(**_):
        raise RuntimeError("fixture executor failed")
    monkeypatch.setattr("app.domain.experience.build_fixture_encounter", fail)
    monkeypatch.setattr("app.storage.mysql.build_fixture_encounter", fail)
    with pytest.raises(RuntimeError):
        tick(module, first, "failed")
    for world in (first, second):
        assert module.get_exploration(world.user.id)["state"].availability == "available"
        assert module.get_exploration(world.user.id)["last_encounter_id"] is None


def test_unrelated_user_cannot_decide_on_an_encounter(module):
    first, second = create(module, "owner-a"), create(module, "owner-b")
    result = tick(module, first, "owners")
    stranger = create(module, "stranger")
    with pytest.raises(NotFound):
        module.decide_encounter(result.encounter_id, EncounterDecisionRequest(
            user_id=stranger.user.id, decision="block"), idempotency_key="not-owner")


def test_recall_is_bounded_seeded_and_prioritizes_same_island_new_partners(module):
    world = create(module, "recall-actor")
    now = utc_now() + timedelta(seconds=1)
    with module._matching_session() as repo:
        actor = repo.profile(repo.get_state(world.user.id), now)
    pool = tuple(MatchProfile(actor.state.model_copy(update={"lifeform_id": f"peer-{i}",
        "user_id": f"user-{i}", "waiting_since": now - timedelta(hours=1)}),
        actor.snapshot.model_copy(update={"id": f"snapshot-{i}"}), True) for i in range(50))
    kwargs = dict(actor=actor, pool=pool, island_id="stability", topic_code="choice_uncertainty",
                  seed="same-scene", now=now)
    one = recall_candidates(**kwargs)
    assert len(one) == 30 and one == recall_candidates(**kwargs)
    assert one != recall_candidates(**{**kwargs, "seed": "another-scene"})
    assert {c.lifeform_id for c in one}.isdisjoint({world.lifeform.id})


def test_concurrent_ticks_cannot_reuse_a_participant(module):
    first, second, third = (create(module, f"concurrent-{i}") for i in range(3))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda w: tick(module, w, "same-window"), (first, second)))
    matched = [r for r in results if r.matching_status == "matched"]
    assert len(matched) == 1
    encounter = module.get_tick_encounter(matched[0].id)
    assert len(set(encounter.lifeform_ids)) == 2


def test_parallel_idempotent_submission_produces_one_encounter(module):
    first, second = create(module, "idem-a"), create(module, "idem-b")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: tick(module, first, "same-key"), range(3)))
    assert len({r.id for r in results}) == 1
    assert len({r.encounter_id for r in results}) == 1
    assert results[0].matching_status == "matched"


def test_cron_and_manual_use_same_match_rules(module):
    import asyncio
    from app.worker import execute_world_tick
    from app.domain.models import TickCommand
    first, second = create(module, "cron-a"), create(module, "cron-b")
    result = asyncio.run(execute_world_tick({"experience": module}, TickCommand(
        user_id=first.user.id, trigger_type=TriggerType.CRON,
        idempotency_key="cron-window").model_dump(mode="json")))
    assert result["matching_status"] == "matched"
    assert tick(module, second, "manual-same-window").matching_status == "cooldown"


def test_disabled_participant_is_not_scheduled_by_cron(module):
    world = create(module, "pause-cron")
    module.update_exploration(world.user.id, ExplorationSettings(enabled=False))
    assert world.user.id not in module.list_tick_candidates()


def test_private_suppression_and_match_snapshots_survive_restart(tmp_path, monkeypatch):
    path = tmp_path / "restart-matching.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    metadata.create_all(engine)
    module = MySqlExperienceModule(engine)
    first, second = create(module, "restart-a"), create(module, "restart-b")
    result = tick(module, first, "before-restart")
    encounter = module.get_tick_encounter(result.id)
    module.decide_encounter(encounter.id, EncounterDecisionRequest(
        user_id=first.user.id, decision="end"), idempotency_key="end-once")
    module.close()
    restarted = MySqlExperienceModule(create_engine(f"sqlite+pysqlite:///{path}"))
    assert restarted.get_tick_encounter(result.id).match_reason == encounter.match_reason
    assert restarted.get_context_snapshot(encounter.companion_snapshot_id,
        user_id=second.user.id).purpose == "social_recommendation"
    set_time(monkeypatch, utc_now() + timedelta(days=2))
    assert tick(restarted, second, "after-restart").matching_status == "waiting"
    restarted.close()
