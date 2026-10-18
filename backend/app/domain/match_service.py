from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from .errors import Conflict, NotFound
from .matching import (ENCOUNTER_COOLDOWN_SECONDS, MATCH_RULE_VERSION, MatchProfile,
    can_participate, recall_candidates, select_candidate)
from .models import EncounterDecisionRequest, ExplorationSettings, utc_now


def choose_match(repo, *, user_id, island, seed, now):
    state = repo.get_state(user_id)
    state = state.model_copy(update={"island_id": island.island_id})
    repo.put_state(state)
    actor = repo.profile(state, now)
    base = dict(rule_version=MATCH_RULE_VERSION, seed=seed, status="waiting",
        reason="暂时没有合适的同行者，生命体会继续私人探索。", candidates=[])
    if not state.enabled or state.social_pace == "observe_first" or not actor.consent_enabled:
        return {**base, "status": "paused", "reason": "相遇已暂停；你可以在探索设置中调整参与意愿与授权。"}, None
    if state.availability != "available" or state.available_at > now or repo.has_active(state.lifeform_id):
        return {**base, "status": "cooldown", "reason": "生命体正在休息或已有相遇，稍后继续探索。"}, None
    if not can_participate(actor, now, island.topic_code):
        return base, None
    candidates = recall_candidates(actor=actor,
        pool=repo.pool(actor, island, now), island_id=island.island_id,
        topic_code=island.topic_code, seed=seed, now=now,
        excluded_ids=repo.exclusions(state.lifeform_id, now),
        encounter_counts=repo.encounter_counts(state.lifeform_id))
    selected = select_candidate(candidates)
    base["candidates"] = [asdict(c) for c in candidates]
    if selected is None:
        return base, None
    # Re-read all owner-controlled gates at the commit boundary. SQL holds the
    # shared scheduling guard; memory holds the same module lock throughout.
    peer_state = repo.get_state(selected.user_id)
    actor = repo.profile(repo.get_state(user_id), now)
    peer = repo.profile(peer_state, now)
    checked = recall_candidates(actor=actor, pool=(peer,), island_id=island.island_id,
        topic_code=island.topic_code, seed=seed, now=now,
        excluded_ids=repo.exclusions(state.lifeform_id, now),
        encounter_counts=repo.encounter_counts(state.lifeform_id))
    if not checked:
        return base, None
    selected = checked[0]
    for profile in (actor, peer):
        saved = repo.save_snapshot(profile.snapshot)
        repo.put_state(profile.state.model_copy(update={"availability": "busy",
            "latest_social_snapshot_id": saved.id}))
    return {**base, "status": "matched", "reason": selected.reason,
        "actor_snapshot_id": actor.snapshot.id,
        "companion_snapshot_id": peer.snapshot.id,
        "companion_lifeform_id": peer.state.lifeform_id,
        "companion_is_demo": peer.state.is_demo or actor.state.is_demo,
        "score_breakdown": selected.score_breakdown,
        "recall_source": selected.recall_source}, selected


def finish_match(repo, user_ids, island_id, now):
    for user_id in user_ids:
        state = repo.get_state(user_id)
        repo.put_state(state.model_copy(update={"availability": "available",
            "island_id": island_id, "waiting_since": now,
            "available_at": now + timedelta(seconds=ENCOUNTER_COOLDOWN_SECONDS)}))


class MatchingService:
    def get_exploration(self, user_id):
        with self._matching_session() as repo:
            state = repo.get_state(user_id)
            now = utc_now()
            profile = repo.profile(state, now)
            status = "paused" if (not state.enabled or not profile.consent_enabled or
                state.social_pace == "observe_first") else (
                "cooldown" if state.available_at > now or state.availability == "busy"
                    or repo.has_active(state.lifeform_id) else "waiting")
            encounter = repo.latest_encounter(state.lifeform_id)
            return {"state": state, "status": status,
                "last_encounter_id": encounter.id if encounter else None,
                "last_match_reason": encounter.match_reason if encounter else "",
                "last_encounter_is_demo": encounter.companion_is_demo if encounter else False,
                "authorized_topics": profile.snapshot.topics}

    def update_exploration(self, user_id: str, request: ExplorationSettings):
        with self._matching_session() as repo:
            state = repo.get_state(user_id)
            state = state.model_copy(update={**request.model_dump(),
                "excluded_topics": tuple(t.value for t in request.excluded_topics)})
            repo.put_state(state)
            repo.set_social_pace(user_id, request.social_pace)
            repo.audit("exploration.settings_changed", user_id, state.lifeform_id,
                {"enabled": request.enabled, "allow_cross_island": request.allow_cross_island})
        return self.get_exploration(user_id)

    def decide_encounter(self, encounter_id: str, request: EncounterDecisionRequest,
                         *, idempotency_key: str):
        if not idempotency_key or len(idempotency_key) > 128:
            raise Conflict("a valid idempotency key is required")
        with self._matching_session() as repo:
            state = repo.get_state(request.user_id)
            encounter = repo.encounter(encounter_id)
            if state.lifeform_id not in encounter.lifeform_ids:
                raise NotFound("encounter not found")
            existing = repo.find_decision(request.user_id, idempotency_key)
            if existing:
                if existing["encounter_id"] != encounter_id or existing["decision"] != request.decision:
                    raise Conflict("decision key was used for a different choice")
                return existing
            target = next(i for i in encounter.lifeform_ids if i != state.lifeform_id)
            now = utc_now()
            row = dict(id=uuid4().hex, user_id=request.user_id,
                encounter_id=encounter_id, lifeform_id=state.lifeform_id,
                target_lifeform_id=target, decision=request.decision,
                idempotency_key=idempotency_key, occurred_at=now)
            repo.save_decision(row)
            if request.decision in {"distance", "end", "block"}:
                repo.suppress(state.lifeform_id, target, request.decision,
                    now + timedelta(hours=48) if request.decision == "distance" else None)
            repo.audit("encounter.private_decision", request.user_id, encounter_id,
                       {"decision": request.decision})
            # Never expose the other user's choice or open a chat here.
            return row
