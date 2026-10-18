from datetime import timedelta

from .errors import NotFound
from .match_service import MatchingService
from .matching import MatchProfile, demo_snapshot, PAIR_COOLDOWN_SECONDS, POOL_LIMIT
from .memory_service import snapshot_for
from .models import ExplorationState, ContextPurpose, utc_now


PACE = {"disabled": "observe_first", "exploring": "shared_experiences", "open": "open_to_connection"}


class MemoryMatchingRepository:
    def __init__(self, module):
        self.module, self.state = module, module._state

    def get_state(self, user_id):
        world = self.module.get_world(user_id)
        state = self.state.exploration_states.get(world.lifeform.id)
        if state is None:
            demo = world.lifeform.id in {"lifeform-lumi", "lifeform-ache"}
            pace = PACE.get(self.state.user_social_intent.get(user_id, "disabled"), "observe_first")
            state = ExplorationState(lifeform_id=world.lifeform.id, user_id=user_id,
                island_id=world.lifeform.current_island_id, enabled=pace != "observe_first",
                is_demo=demo, allow_cross_island=demo, allow_demo_partners=demo, social_pace=pace)
            self.put_state(state)
        # Lifeform location is authoritative after autonomous exploration.
        return state.model_copy(update={"island_id": world.lifeform.current_island_id})

    def put_state(self, state):
        self.state.exploration_states[state.lifeform_id] = state

    def profile(self, state, now):
        with self.module._memory_unit(state.user_id) as unit:
            snapshot = snapshot_for(unit, ContextPurpose.SOCIAL_RECOMMENDATION)
            enabled = unit.memory_enabled and unit.social_enabled
        if state.is_demo:
            snapshot = demo_snapshot(snapshot)
            enabled = True
        return MatchProfile(state, snapshot, enabled)

    def pool(self, actor, island, now):
        states = [self.get_state(l.user_id) for l in self.state.lifeforms.values()
                  if l.id != actor.state.lifeform_id]
        states = [s for s in states if s.enabled and s.availability == "available"
                  and s.available_at <= now and not self.has_active(s.lifeform_id)
                  and (s.island_id == island.island_id or s.allow_cross_island)]
        states.sort(key=lambda s: (s.island_id != island.island_id, s.waiting_since, s.lifeform_id))
        return tuple(self.profile(s, now) for s in states[:POOL_LIMIT])

    def exclusions(self, actor_id, now):
        excluded = set()
        for (first, second), entry in self.state.pair_exclusions.items():
            if actor_id in (first, second) and (entry["until_at"] is None or entry["until_at"] > now):
                excluded.add(second if first == actor_id else first)
        for relationship in self.state.relationships.values():
            if actor_id in relationship.lifeform_ids and relationship.status in {"ended", "blocked"}:
                excluded.update(i for i in relationship.lifeform_ids if i != actor_id)
        cutoff = now - timedelta(seconds=PAIR_COOLDOWN_SECONDS)
        for encounter in self.state.encounters.values():
            if actor_id in encounter.lifeform_ids and (encounter.status in {"queued", "running"}
                    or encounter.completed_at > cutoff):
                excluded.update(i for i in encounter.lifeform_ids if i != actor_id)
        return frozenset(excluded)

    def encounter_counts(self, actor_id):
        counts = {}
        for encounter in self.state.encounters.values():
            if actor_id in encounter.lifeform_ids:
                peer = next(i for i in encounter.lifeform_ids if i != actor_id)
                counts[peer] = counts.get(peer, 0) + 1
        return counts

    def has_active(self, lifeform_id):
        return any(lifeform_id in e.lifeform_ids and e.status in {"queued", "running"}
                   for e in self.state.encounters.values())

    def save_snapshot(self, snapshot):
        return self.module._save_snapshot(snapshot)

    def latest_encounter(self, lifeform_id):
        rows = [e for e in self.state.encounters.values() if lifeform_id in e.lifeform_ids
                and e.status in {"completed", "left"}]
        return max(rows, key=lambda e: e.completed_at) if rows else None

    def encounter(self, encounter_id):
        return self.module.get_encounter(encounter_id)

    def find_decision(self, user_id, key):
        return self.state.private_decisions.get((user_id, key))

    def save_decision(self, row):
        self.state.private_decisions[(row["user_id"], row["idempotency_key"])] = row

    def suppress(self, actor, peer, decision, until_at):
        old = self.state.pair_exclusions.get((actor, peer))
        if old and old["decision"] in {"end", "block"}:
            return
        self.state.pair_exclusions[(actor, peer)] = dict(decision=decision, until_at=until_at)

    def set_social_pace(self, user_id, pace):
        self.state.user_social_intent[user_id] = {v: k for k, v in PACE.items()}[pace]

    def audit(self, event, actor, subject, details):
        self.module._append_audit(event_type=event, actor_id=actor,
            subject_id=subject, details=details)
