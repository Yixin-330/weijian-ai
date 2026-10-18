from datetime import timedelta

from sqlalchemy import select, update, insert, or_, and_, case, func

from app.domain.errors import NotFound
from app.domain.matching import MatchProfile, demo_snapshot, PAIR_COOLDOWN_SECONDS, POOL_LIMIT
from app.domain.matching_memory import PACE
from app.domain.memory_layer import aware
from app.domain.memory_service import snapshot_for
from app.domain.models import ExplorationState, ContextPurpose, utc_now
from .schema import users, lifeforms, user_consents, encounters, relationships
from .matching_schema import exploration_states, matching_guard, pair_exclusions, private_encounter_decisions


def acquire_matching_guard(module, connection):
    module._insert_if_missing(connection, matching_guard, matching_guard.c.id == 1, id=1)
    connection.execute(select(matching_guard.c.id).where(matching_guard.c.id == 1).with_for_update()).one()


class SqlMatchingRepository:
    def __init__(self, module, connection):
        self.module, self.connection = module, connection

    def get_state(self, user_id):
        row = self.connection.execute(select(lifeforms, users.c.social_intent)
            .join(users, users.c.id == lifeforms.c.user_id)
            .where(lifeforms.c.user_id == user_id)).mappings().first()
        if row is None:
            raise NotFound("user not found")
        found = self.connection.execute(select(exploration_states)
            .where(exploration_states.c.lifeform_id == row["id"])).mappings().first()
        if found is None:
            demo = row["id"] in {"lifeform-lumi", "lifeform-ache"}
            pace = PACE.get(row["social_intent"], "observe_first")
            state = ExplorationState(lifeform_id=row["id"], user_id=user_id,
                island_id=row["current_island_id"], enabled=pace != "observe_first",
                allow_cross_island=demo, allow_demo_partners=demo, is_demo=demo,
                social_pace=pace, waiting_since=aware(row["created_at"]),
                available_at=aware(row["created_at"]))
            self.connection.execute(insert(exploration_states).values(**self.values(state)))
            return state
        return self.from_row(found).model_copy(update={"island_id": row["current_island_id"]})

    @staticmethod
    def from_row(row):
        values = dict(row)
        for name in ("waiting_since", "available_at"):
            values[name] = aware(values[name])
        return ExplorationState.model_validate(values)

    @staticmethod
    def values(state):
        values = state.model_dump()
        values["social_pace"] = state.social_pace.value
        values["excluded_topics"] = list(state.excluded_topics)
        return values

    def put_state(self, state):
        self.connection.execute(update(exploration_states)
            .where(exploration_states.c.lifeform_id == state.lifeform_id).values(**self.values(state)))

    def profile(self, state, now):
        unit = self.module._read_memory_unit(self.connection, state.user_id)
        snapshot = snapshot_for(unit, ContextPurpose.SOCIAL_RECOMMENDATION)
        enabled = unit.memory_enabled and unit.social_enabled
        if state.is_demo:
            snapshot = demo_snapshot(snapshot)
            enabled = True
        return MatchProfile(state, snapshot, enabled)

    def pool(self, actor, island, now):
        enabled_scope = lambda scope: select(user_consents.c.user_id).where(
            user_consents.c.user_id == exploration_states.c.user_id,
            user_consents.c.scope == scope, user_consents.c.enabled.is_(True)).exists()
        active = select(encounters.c.id).where(
            or_(encounters.c.lifeform_a_id == exploration_states.c.lifeform_id,
                encounters.c.lifeform_b_id == exploration_states.c.lifeform_id),
            encounters.c.status.in_(("queued", "running"))).exists()
        excluded = self.exclusions(actor.state.lifeform_id, now)
        query = select(exploration_states).where(
            exploration_states.c.lifeform_id != actor.state.lifeform_id,
            exploration_states.c.enabled.is_(True),
            exploration_states.c.availability == "available",
            exploration_states.c.available_at <= now,
            exploration_states.c.social_pace != "observe_first", ~active,
            or_(exploration_states.c.island_id == island.island_id,
                exploration_states.c.allow_cross_island.is_(True)),
            or_(exploration_states.c.is_demo.is_(True),
                and_(enabled_scope("memory_inference"), enabled_scope("social_recommendation"))))
        if excluded:
            query = query.where(exploration_states.c.lifeform_id.not_in(excluded))
        if not actor.state.allow_demo_partners:
            query = query.where(exploration_states.c.is_demo.is_(False))
        if actor.state.is_demo:
            query = query.where(exploration_states.c.allow_demo_partners.is_(True))
        rows = self.connection.execute(query.order_by(
            case((exploration_states.c.island_id == island.island_id, 0), else_=1),
            exploration_states.c.waiting_since, exploration_states.c.lifeform_id)
            .limit(POOL_LIMIT)).mappings().all()
        return tuple(self.profile(self.from_row(row), now) for row in rows)

    def exclusions(self, actor_id, now):
        excluded = set()
        rows = self.connection.execute(select(pair_exclusions).where(
            or_(pair_exclusions.c.lifeform_id == actor_id,
                pair_exclusions.c.target_lifeform_id == actor_id),
            or_(pair_exclusions.c.until_at.is_(None), pair_exclusions.c.until_at > now))).mappings()
        for row in rows:
            excluded.add(row["target_lifeform_id"] if row["lifeform_id"] == actor_id else row["lifeform_id"])
        recent = self.connection.execute(select(encounters).where(
            or_(encounters.c.lifeform_a_id == actor_id, encounters.c.lifeform_b_id == actor_id),
            or_(encounters.c.status.in_(("queued", "running")),
                encounters.c.completed_at > now - timedelta(seconds=PAIR_COOLDOWN_SECONDS)))).mappings()
        for row in recent:
            excluded.add(row["lifeform_b_id"] if row["lifeform_a_id"] == actor_id else row["lifeform_a_id"])
        ended = self.connection.execute(select(relationships).where(
            or_(relationships.c.lifeform_a_id == actor_id, relationships.c.lifeform_b_id == actor_id),
            relationships.c.status.in_(("ended", "blocked")))).mappings()
        for row in ended:
            excluded.add(row["lifeform_b_id"] if row["lifeform_a_id"] == actor_id else row["lifeform_a_id"])
        return frozenset(excluded)

    def encounter_counts(self, actor_id):
        peer = case((encounters.c.lifeform_a_id == actor_id, encounters.c.lifeform_b_id),
                    else_=encounters.c.lifeform_a_id)
        return dict(self.connection.execute(select(peer, func.count()).where(
            or_(encounters.c.lifeform_a_id == actor_id, encounters.c.lifeform_b_id == actor_id))
            .group_by(peer)).all())

    def has_active(self, lifeform_id):
        return self.connection.execute(select(encounters.c.id).where(
            or_(encounters.c.lifeform_a_id == lifeform_id, encounters.c.lifeform_b_id == lifeform_id),
            encounters.c.status.in_(("queued", "running"))).limit(1)).first() is not None

    def save_snapshot(self, snapshot):
        return self.module._save_snapshot_in(self.connection, snapshot)

    def latest_encounter(self, lifeform_id):
        row = self.connection.execute(select(encounters.c.id).where(
            or_(encounters.c.lifeform_a_id == lifeform_id, encounters.c.lifeform_b_id == lifeform_id),
            encounters.c.status.in_(("completed", "left")))
            .order_by(encounters.c.completed_at.desc()).limit(1)).first()
        return self.encounter(row.id) if row else None

    def encounter(self, encounter_id):
        from .schema import encounter_turns
        row = self.connection.execute(select(encounters).where(encounters.c.id == encounter_id)).mappings().first()
        if row is None:
            raise NotFound("encounter not found")
        turns = self.connection.execute(select(encounter_turns).where(
            encounter_turns.c.encounter_id == encounter_id).order_by(encounter_turns.c.turn_number)).mappings().all()
        return self.module._encounter_from_rows(row, turns)

    def find_decision(self, user_id, key):
        row = self.connection.execute(select(private_encounter_decisions).where(
            private_encounter_decisions.c.user_id == user_id,
            private_encounter_decisions.c.idempotency_key == key)).mappings().first()
        if row is None:
            return None
        result = dict(row)
        result["occurred_at"] = aware(result["occurred_at"])
        return result

    def save_decision(self, row):
        self.connection.execute(insert(private_encounter_decisions).values(**row))

    def suppress(self, actor, peer, decision, until_at):
        where = (pair_exclusions.c.lifeform_id == actor,
                 pair_exclusions.c.target_lifeform_id == peer)
        old = self.connection.execute(select(pair_exclusions).where(*where)).mappings().first()
        if old and old["decision"] in {"end", "block"}:
            return
        if old:
            self.connection.execute(update(pair_exclusions).where(*where)
                .values(decision=decision, until_at=until_at))
        else:
            self.connection.execute(insert(pair_exclusions).values(lifeform_id=actor,
                target_lifeform_id=peer, decision=decision, until_at=until_at))

    def set_social_pace(self, user_id, pace):
        self.connection.execute(update(users).where(users.c.id == user_id)
            .values(social_intent={v: k for k, v in PACE.items()}[pace], updated_at=utc_now()))

    def audit(self, event, actor, subject, details):
        self.module._write_audit(self.connection, event_type=event, actor_id=actor,
            subject_id=subject, details=details, occurred_at=utc_now())
