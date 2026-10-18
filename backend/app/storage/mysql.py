from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import Engine, and_, case, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.observability import current_trace_id
from app.islands import get_islands
from app.domain.encounters import build_fixture_encounter, relationship_id_for_pair
from app.domain.errors import Conflict, Forbidden, NotFound
from app.domain.evidence_ingestion import (
    build_evidence_record,
    same_idempotent_fact,
)
from app.domain.evidence_policy import (
    EvidenceSource,
    MemoryType,
    validate_memory_evidence,
)
from app.domain.island_policy import (
    initial_island,
    materialized_decision_context,
    select_island,
)
from app.domain.experience import (
    DEMO_EVIDENCE_SOURCES,
    DEMO_LIFEFORM_ID,
    DEMO_MEMORY_ID,
    DEMO_MEMORY_TYPE,
    DEMO_RELATIONSHIP_ID,
    DEMO_USER_ID,
)
from app.domain.models import (
    CalibrationDecision,
    CalibrationRequest,
    Encounter,
    EncounterAction,
    EncounterTurn,
    EvidenceIngestRequest,
    EvidenceRecord,
    Lifeform,
    Memory,
    OnboardingRequest,
    Relationship,
    RelationshipStatus,
    TriggerType,
    UserState,
    WorldReadModel,
    WorldTick,
    utc_now,
)
from app.domain.understanding import (
    effective_direction_decision,
    explain_next_action,
    next_action,
)
from app.domain.onboarding import TOPIC_LABELS, onboarding_ids, project_onboarding

from .schema import (
    audit_events,
    encounters,
    encounter_turns,
    evidence,
    lifeforms,
    memories,
    memory_evidence,
    memory_revisions,
    relationships,
    relationship_events,
    user_consents,
    users,
    world_ticks,
    platform_import_snapshots,
)
from .memory import SqlMemoryService
from app.domain.memory_service import snapshot_for
from app.domain.models import ContextPurpose
from app.domain.match_service import MatchingService, choose_match, finish_match
from .matching import SqlMatchingRepository, acquire_matching_guard
from .matching_schema import exploration_states


DEMO_COMPANION_USER_ID = "user-ache"
DEMO_COMPANION_LIFEFORM_ID = "lifeform-ache"


def _utc(value: datetime | None) -> datetime:
    resolved = value or utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved


class MySqlExperienceModule(SqlMemoryService, MatchingService):
    """Persistent adapter for the Experience interface.

    All multi-row writes are committed in one database transaction. MySQL is
    the source of truth; this module never writes through Redis or an LLM.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def _matching_session(self):
        with self._engine.begin() as connection:
            acquire_matching_guard(self, connection)
            yield SqlMatchingRepository(self, connection)

    def check_ready(self) -> bool:
        try:
            with self._engine.connect() as connection:
                connection.execute(select(1)).scalar_one()
            return True
        except SQLAlchemyError:
            return False

    def list_tick_candidates(self, *, limit: int = 1000) -> tuple[str, ...]:
        if limit < 1:
            return ()
        with self._engine.connect() as connection:
            return tuple(
                connection.execute(
                    select(users.c.id)
                    .select_from(users.join(lifeforms, users.c.id == lifeforms.c.user_id)
                        .join(exploration_states, exploration_states.c.lifeform_id == lifeforms.c.id))
                    .where(users.c.social_intent.in_(("exploring", "open")))
                    .where(exploration_states.c.enabled.is_(True))
                    .order_by(users.c.id)
                    .limit(limit)
                ).scalars().all()
            )

    def close(self) -> None:
        self._engine.dispose()

    def bootstrap_demo(self) -> WorldReadModel:
        now = utc_now()
        # 演示种子的岛屿来自 fixture，与 tick 决策共用同一套 ID。
        seed_island = initial_island()
        with self._engine.begin() as connection:
            self._insert_if_missing(
                connection,
                users,
                users.c.id == DEMO_USER_ID,
                id=DEMO_USER_ID,
                external_zhihu_uid=None,
                display_name="体验用户",
                consent_version=1,
                social_intent="exploring",
                created_at=now,
                updated_at=now,
            )
            self._insert_if_missing(
                connection,
                users,
                users.c.id == DEMO_COMPANION_USER_ID,
                id=DEMO_COMPANION_USER_ID,
                external_zhihu_uid=None,
                display_name="同行者",
                consent_version=1,
                social_intent="exploring",
                created_at=now,
                updated_at=now,
            )
            self._insert_if_missing(
                connection,
                lifeforms,
                lifeforms.c.id == DEMO_LIFEFORM_ID,
                id=DEMO_LIFEFORM_ID,
                user_id=DEMO_USER_ID,
                name="露米",
                appearance="雾蓝",
                exploration_tendency="安静观察",
                current_island_id=seed_island.island_id,
                current_focus="选择中的不确定性",
                status="正在与阿澈交流",
                version=1,
                created_at=now,
                updated_at=now,
            )
            self._insert_if_missing(
                connection,
                lifeforms,
                lifeforms.c.id == DEMO_COMPANION_LIFEFORM_ID,
                id=DEMO_COMPANION_LIFEFORM_ID,
                user_id=DEMO_COMPANION_USER_ID,
                name="阿澈",
                appearance="深海蓝",
                exploration_tendency="温和追问",
                current_island_id=seed_island.island_id,
                current_focus="稳定与选择权",
                status="正在与露米交流",
                version=1,
                created_at=now,
                updated_at=now,
            )
            # 种子数据同样过白名单校验：演示数据违规会在启动时立刻暴露，
            # 而不是等到评委面前才发现一条无法解释来源的记忆。
            validate_memory_evidence(
                memory_type=DEMO_MEMORY_TYPE,
                sources=DEMO_EVIDENCE_SOURCES,
                status="candidate",
                confidence=0.62,
            )
            # source_type 取值来自 EvidenceSource 词表，不再写字面量：
            # 此前这里用 favlist_description，而适配层用 favlist_naming，
            # 两套词表漂移会让白名单校验失效（拼错的来源既不在白名单内、
            # 也不会被发现）。
            for evidence_id, source, authored in (
                (
                    "evidence-authored-1",
                    EvidenceSource.AUTHORED_CONTENT,
                    True,
                ),
                (
                    "evidence-favlist-1",
                    EvidenceSource.FAVLIST_NAMING,
                    True,
                ),
            ):
                source_type = source.value
                self._insert_if_missing(
                    connection,
                    evidence,
                    evidence.c.id == evidence_id,
                    id=evidence_id,
                    ingestion_key=f"fixture:{evidence_id}",
                    user_id=DEMO_USER_ID,
                    snapshot_id=None,
                    source_type=source_type,
                    source_ref=None,
                    content_text=(
                        "我反复思考稳定与冒险之间的选择"
                        if source is EvidenceSource.AUTHORED_CONTENT
                        else "稳定、选择与新的可能"
                    ),
                    topic_code="choice_uncertainty",
                    authored_by_user=authored,
                    self_reference=True,
                    assertion_mode="reflection",
                    polarity=None,
                    confidence=0.7,
                    consent_version=1,
                    is_sensitive=False,
                    allow_social_recommendation=True,
                    source_occurred_at=now,
                    created_at=now,
                )
            self._insert_if_missing(
                connection,
                memories,
                memories.c.id == DEMO_MEMORY_ID,
                id=DEMO_MEMORY_ID,
                lifeform_id=DEMO_LIFEFORM_ID,
                # 「更关注……」属关注（topic）而非立场（stance）：
                # 它说明用户在留意什么议题，不说明其立场。原先错标为 stance，
                # 因此挂上了收藏夹证据——正是 PRD 8.4 要防的组合。
                memory_type=DEMO_MEMORY_TYPE.value,
                statement="你可能更关注选择中的不确定性",
                status="candidate",
                confidence=0.62,
                importance=0.7,
                score=1.0,
                score_updated_at=now,
                allow_social_recommendation=True,
                version=1,
                supersedes_memory_id=None,
                topic_code="choice_uncertainty",
                created_at=now,
                updated_at=now,
                expires_at=None,
            )
            for evidence_id in ("evidence-authored-1", "evidence-favlist-1"):
                self._insert_if_missing(
                    connection,
                    memory_evidence,
                    and_(
                        memory_evidence.c.memory_id == DEMO_MEMORY_ID,
                        memory_evidence.c.evidence_id == evidence_id,
                    ),
                    memory_id=DEMO_MEMORY_ID,
                    evidence_id=evidence_id,
                    contribution=0.5,
                )
            first_lifeform, second_lifeform = sorted(
                (DEMO_LIFEFORM_ID, DEMO_COMPANION_LIFEFORM_ID)
            )
            self._insert_if_missing(
                connection,
                relationships,
                relationships.c.id == DEMO_RELATIONSHIP_ID,
                id=DEMO_RELATIONSHIP_ID,
                lifeform_a_id=first_lifeform,
                lifeform_b_id=second_lifeform,
                status=RelationshipStatus.ACTIVE.value,
                last_island_id=seed_island.island_id,
                headline="它们从不同答案里，看见了彼此",
                shared_experiences=["灯塔即将熄灭", "关于稳定与选择权的第一次碰撞"],
                encounter_count=1,
                source_mode="precomputed",
                projection_version=1,
                ended_at=None,
                created_at=now,
                updated_at=now,
            )
            repo = SqlMatchingRepository(self, connection)
            repo.get_state(DEMO_USER_ID)
            repo.get_state(DEMO_COMPANION_USER_ID)
        return self.get_world(DEMO_USER_ID)

    def onboard(
        self, request: OnboardingRequest, *, idempotency_key: str
    ) -> WorldReadModel:
        if not idempotency_key or len(idempotency_key) > 128:
            raise Conflict("a valid idempotency key is required")
        if not request.allow_memory_inference:
            raise Forbidden("创建生命体需要允许当前四项回答用于初始理解")

        ids = onboarding_ids(idempotency_key, len(request.long_term_topics))
        projection = project_onboarding(request)
        now = utc_now()
        try:
            with self._engine.begin() as connection:
                if connection.execute(
                    select(users.c.id).where(users.c.id == ids.user_id)
                ).first():
                    return self.get_world(ids.user_id)

                connection.execute(
                    insert(users).values(
                        id=ids.user_id,
                        external_zhihu_uid=None,
                        display_name="新朋友",
                        consent_version=1,
                        social_intent=projection.social_intent,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for scope, enabled in (
                    ("memory_inference", True),
                    ("social_recommendation", request.allow_social_recommendation),
                ):
                    connection.execute(
                        insert(user_consents).values(
                            user_id=ids.user_id,
                            scope=scope,
                            enabled=enabled,
                            version=1,
                            changed_at=now,
                        )
                    )
                connection.execute(
                    insert(lifeforms).values(
                        id=ids.lifeform_id,
                        user_id=ids.user_id,
                        name=projection.lifeform_name,
                        appearance={
                            "palette": projection.appearance,
                            "form": "translucent_seed",
                        },
                        exploration_tendency=projection.exploration_tendency,
                        current_island_id=projection.initial_island_id,
                        current_focus=projection.current_focus,
                        status="刚刚诞生，正在形成初始理解",
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )

                SqlMatchingRepository(self, connection).get_state(ids.user_id)
                question_evidence = build_evidence_record(
                    user_id=ids.user_id,
                    consent_version=1,
                    request=EvidenceIngestRequest(
                        ingestion_key=f"onboarding:{ids.question_evidence_id}",
                        source=EvidenceSource.IN_APP_INPUT,
                        content_text=request.current_question,
                        source_ref="onboarding:current_question",
                        topic_code=projection.primary_topic.value,
                        self_reference=True,
                        assertion_mode="question",
                        confidence=0.82,
                        allow_social_recommendation=request.allow_social_recommendation,
                    ),
                    evidence_id=ids.question_evidence_id,
                    created_at=now,
                )
                validate_memory_evidence(
                    memory_type=MemoryType.TOPIC,
                    sources=(EvidenceSource.IN_APP_INPUT,),
                    status="candidate",
                    confidence=0.82,
                )
                connection.execute(
                    insert(evidence).values(**self._evidence_values(question_evidence))
                )
                connection.execute(
                    insert(memories).values(
                        id=ids.question_memory_id,
                        lifeform_id=ids.lifeform_id,
                        memory_type=MemoryType.TOPIC.value,
                        statement=projection.candidate_statement,
                        status="candidate",
                        confidence=0.82,
                        importance=0.8,
                        score=0.82,
                        score_updated_at=now,
                        allow_social_recommendation=request.allow_social_recommendation,
                        version=1,
                        supersedes_memory_id=None,
                        topic_code=projection.primary_topic.value,
                        created_at=now,
                        updated_at=now,
                        expires_at=None,
                    )
                )
                connection.execute(
                    insert(memory_evidence).values(
                        memory_id=ids.question_memory_id,
                        evidence_id=ids.question_evidence_id,
                        contribution=1.0,
                    )
                )

                for index, topic in enumerate(request.long_term_topics):
                    evidence_id = ids.topic_evidence_ids[index]
                    memory_id = ids.topic_memory_ids[index]
                    topic_evidence = build_evidence_record(
                        user_id=ids.user_id,
                        consent_version=1,
                        request=EvidenceIngestRequest(
                            ingestion_key=f"onboarding:{evidence_id}",
                            source=EvidenceSource.IN_APP_INPUT,
                            content_text=TOPIC_LABELS[topic],
                            source_ref=f"onboarding:topic:{topic.value}",
                            topic_code=topic.value,
                            self_reference=True,
                            assertion_mode="selection",
                            confidence=1.0,
                            allow_social_recommendation=request.allow_social_recommendation,
                        ),
                        evidence_id=evidence_id,
                        created_at=now,
                    )
                    validate_memory_evidence(
                        memory_type=MemoryType.TOPIC,
                        sources=(EvidenceSource.IN_APP_INPUT,),
                        status="confirmed",
                        confidence=1.0,
                    )
                    connection.execute(
                        insert(evidence).values(**self._evidence_values(topic_evidence))
                    )
                    connection.execute(
                        insert(memories).values(
                            id=memory_id,
                            lifeform_id=ids.lifeform_id,
                            memory_type=MemoryType.TOPIC.value,
                            statement=f"你愿意长期关注「{TOPIC_LABELS[topic]}」",
                            status="confirmed",
                            confidence=1.0,
                            importance=0.72,
                            score=0.78,
                            score_updated_at=now,
                            allow_social_recommendation=request.allow_social_recommendation,
                            version=1,
                            supersedes_memory_id=None,
                            topic_code=topic.value,
                            created_at=now,
                            updated_at=now,
                            expires_at=None,
                        )
                    )
                    connection.execute(
                        insert(memory_evidence).values(
                            memory_id=memory_id,
                            evidence_id=evidence_id,
                            contribution=1.0,
                        )
                    )

                self._write_audit(
                    connection,
                    event_type="onboarding.completed",
                    actor_id=ids.user_id,
                    subject_id=ids.lifeform_id,
                    details={
                        "answer_count": 4,
                        "topic_count": len(request.long_term_topics),
                        "initial_island_id": projection.initial_island_id,
                        "allow_social_recommendation": request.allow_social_recommendation,
                    },
                    occurred_at=now,
                )
        except IntegrityError:
            with self._engine.connect() as connection:
                if connection.execute(
                    select(users.c.id).where(users.c.id == ids.user_id)
                ).first():
                    return self.get_world(ids.user_id)
            raise
        return self.get_world(ids.user_id)

    def get_world(self, user_id: str) -> WorldReadModel:
        with self._engine.connect() as connection:
            user_row = connection.execute(
                select(users).where(users.c.id == user_id)
            ).mappings().first()
            if user_row is None:
                raise NotFound(f"user {user_id!r} was not found")
            lifeform_row = connection.execute(
                select(lifeforms).where(lifeforms.c.user_id == user_id)
            ).mappings().first()
            if lifeform_row is None:
                raise NotFound(f"lifeform for user {user_id!r} was not found")
            memory_rows = connection.execute(
                select(memories)
                .where(
                    memories.c.lifeform_id == lifeform_row["id"],
                    memories.c.status.in_(("candidate", "confirmed", "rejected")),
                )
                .order_by(memories.c.updated_at.desc())
            ).mappings().all()
            relationship_rows = connection.execute(
                select(relationships).where(
                    or_(
                        relationships.c.lifeform_a_id == lifeform_row["id"],
                        relationships.c.lifeform_b_id == lifeform_row["id"],
                    )
                )
            ).mappings().all()
            tick_row = connection.execute(
                select(world_ticks)
                .where(world_ticks.c.user_id == user_id)
                .order_by(world_ticks.c.started_at.desc())
                .limit(1)
            ).mappings().first()
            return WorldReadModel(
                user=self._user_from_row(user_row),
                lifeform=self._lifeform_from_row(lifeform_row),
                memories=tuple(
                    self._memory_from_row(connection, row) for row in memory_rows
                ),
                relationships=tuple(
                    self._relationship_from_row(row) for row in relationship_rows
                ),
                latest_tick=self._tick_from_row(tick_row) if tick_row else None,
                source_mode="live" if tick_row or user_id != DEMO_USER_ID else "precomputed",
            )

    def get_lifeform(self, lifeform_id: str) -> Lifeform:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(lifeforms).where(lifeforms.c.id == lifeform_id)
            ).mappings().first()
            if row is None:
                raise NotFound(f"lifeform {lifeform_id!r} was not found")
            return self._lifeform_from_row(row)

    def get_relationship(self, relationship_id: str) -> Relationship:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(relationships).where(relationships.c.id == relationship_id)
            ).mappings().first()
            if row is None:
                raise NotFound(f"relationship {relationship_id!r} was not found")
            return self._relationship_from_row(row)

    def get_encounter(self, encounter_id: str) -> Encounter:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(encounters).where(encounters.c.id == encounter_id)
            ).mappings().first()
            if row is None:
                raise NotFound(f"encounter {encounter_id!r} was not found")
            turn_rows = connection.execute(
                select(encounter_turns)
                .where(encounter_turns.c.encounter_id == encounter_id)
                .order_by(encounter_turns.c.turn_number)
            ).mappings().all()
            return self._encounter_from_rows(row, turn_rows)

    def get_tick_encounter(self, tick_id: str) -> Encounter:
        with self._engine.connect() as connection:
            encounter_id = connection.execute(
                select(encounters.c.id).where(encounters.c.world_tick_id == tick_id)
            ).scalar_one_or_none()
        if encounter_id is None:
            raise NotFound(f"world tick {tick_id!r} did not create an encounter")
        return self.get_encounter(encounter_id)

    def get_tick(self, tick_id: str) -> WorldTick:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(world_ticks).where(world_ticks.c.id == tick_id)
            ).mappings().first()
            if row is None:
                raise NotFound(f"world tick {tick_id!r} was not found")
            return self._tick_from_row(row)

    def ingest_evidence(
        self, user_id: str, request: EvidenceIngestRequest
    ) -> EvidenceRecord:
        now = utc_now()
        candidate: EvidenceRecord | None = None
        try:
            with self._engine.begin() as connection:
                user_row = connection.execute(
                    select(users).where(users.c.id == user_id).with_for_update()
                ).mappings().first()
                if user_row is None:
                    raise NotFound(f"user {user_id!r} was not found")

                candidate = build_evidence_record(
                    user_id=user_id,
                    consent_version=int(user_row["consent_version"]),
                    request=request,
                    created_at=now,
                )
                existing_row = connection.execute(
                    select(evidence).where(
                        evidence.c.user_id == user_id,
                        evidence.c.ingestion_key == request.ingestion_key,
                    )
                ).mappings().first()
                if existing_row is not None:
                    existing = self._evidence_from_row(existing_row)
                    if not same_idempotent_fact(existing, candidate):
                        raise Conflict(
                            "ingestion key was already used for different evidence"
                        )
                    return existing

                if candidate.snapshot_id is not None:
                    source_snapshot = connection.execute(select(platform_import_snapshots.c.id)
                        .where(platform_import_snapshots.c.id == candidate.snapshot_id,
                               platform_import_snapshots.c.user_id == user_id,
                               platform_import_snapshots.c.status == "active")).first()
                    if source_snapshot is None:
                        raise NotFound("active source snapshot not found")
                connection.execute(
                    insert(evidence).values(**self._evidence_values(candidate))
                )
                self._write_audit(
                    connection,
                    event_type="evidence.ingested",
                    actor_id=user_id,
                    subject_id=candidate.id,
                    details={
                        "source": candidate.source.value,
                        "topic_code": candidate.topic_code,
                        "consent_version": candidate.consent_version,
                        "allow_social_recommendation": (
                            candidate.allow_social_recommendation
                        ),
                    },
                    occurred_at=now,
                )
                return candidate
        except IntegrityError:
            # Two workers may race after both observe no row. The unique key is
            # the final arbiter; the loser returns the committed immutable fact.
            if candidate is not None:
                with self._engine.connect() as connection:
                    row = connection.execute(
                        select(evidence).where(
                            evidence.c.user_id == user_id,
                            evidence.c.ingestion_key == request.ingestion_key,
                        )
                    ).mappings().first()
                if row is not None:
                    existing = self._evidence_from_row(row)
                    if same_idempotent_fact(existing, candidate):
                        return existing
                    raise Conflict(
                        "ingestion key was already used for different evidence"
                    )
            raise

    def get_evidence(self, evidence_id: str, *, user_id: str) -> EvidenceRecord:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(evidence).where(
                    evidence.c.id == evidence_id,
                    evidence.c.user_id == user_id,
                )
            ).mappings().first()
            if row is None:
                raise NotFound(f"evidence {evidence_id!r} was not found")
            return self._evidence_from_row(row)


    def run_world_tick(
        self,
        *,
        user_id: str,
        trigger_type: TriggerType,
        idempotency_key: str,
    ) -> WorldTick:
        if not idempotency_key or len(idempotency_key) > 128:
            raise Conflict("a valid idempotency key is required")
        now = utc_now()
        try:
            with self._engine.begin() as connection:
                acquire_matching_guard(self, connection)
                existing = connection.execute(
                    select(world_ticks).where(
                        world_ticks.c.user_id == user_id,
                        world_ticks.c.idempotency_key == idempotency_key,
                    )
                ).mappings().first()
                if existing:
                    return self._tick_from_row(existing)

                lifeform_row = connection.execute(
                    select(lifeforms).where(lifeforms.c.user_id == user_id).with_for_update()
                ).mappings().first()
                if lifeform_row is None:
                    raise NotFound(f"user {user_id!r} was not found")
                repeat_rows = connection.execute(
                    select(world_ticks.c.selected_island_id, func.count())
                    .where(
                        world_ticks.c.user_id == user_id,
                        world_ticks.c.status == "completed",
                        world_ticks.c.selected_island_id.is_not(None),
                    )
                    .group_by(world_ticks.c.selected_island_id)
                ).all()
                repeat_counts = {
                    island_id: int(count) for island_id, count in repeat_rows
                }
                social_intent = connection.execute(
                    select(users.c.social_intent).where(users.c.id == user_id)
                ).scalar_one()
                social_willingness = {
                    "disabled": 0.0,
                    "exploring": 0.58,
                    "open": 0.82,
                }.get(social_intent, 0.0)
                curiosity = {
                    "安静观察": 0.64,
                    "温和追问": 0.72,
                    "主动尝试": 0.78,
                }.get(lifeform_row["exploration_tendency"], 0.55)
                unit = self._read_memory_unit(connection, user_id)
                snapshot = self._save_snapshot_in(connection,
                    snapshot_for(unit, ContextPurpose.EXPLORATION))
                raw_calibration = snapshot.calibration
                calibration = effective_direction_decision(raw_calibration)
                recent_topic_weights = snapshot.topic_weights
                long_term_topic_weights = snapshot.long_term_topic_weights
                choice = select_island(
                    context=materialized_decision_context(
                        calibration=calibration,
                        recent_topic_weights=recent_topic_weights,
                        long_term_topic_weights=long_term_topic_weights,
                        repeat_counts=repeat_counts,
                        curiosity=curiosity,
                        social_willingness=social_willingness,
                    )
                )
                island_id = choice.island_id
                action = next_action(raw_calibration)
                reason = explain_next_action(
                    decision=raw_calibration,
                    island_reason=choice.reason,
                )
                if snapshot.excluded_understanding_ids:
                    reason = "已停止使用不再有效或未获授权的理解；" + reason

                tick_id = uuid4().hex
                trace_id = current_trace_id()
                connection.execute(
                    insert(world_ticks).values(
                        id=tick_id,
                        user_id=user_id,
                        lifeform_id=lifeform_row["id"],
                        trigger_type=trigger_type.value,
                        idempotency_key=idempotency_key,
                        fixture_version=choice.fixture_version,
                        context_snapshot_id=snapshot.id,
                        selected_island_id=island_id,
                        decision_reason=reason,
                        source_mode="live",
                        status="completed",
                        trace_id=trace_id,
                        started_at=now,
                        completed_at=now,
                    )
                )
                connection.execute(
                    update(lifeforms)
                    .where(lifeforms.c.id == lifeform_row["id"])
                    .values(
                        current_island_id=island_id,
                        status=f"{action} · 正在前往新的问题岛",
                        version=lifeforms.c.version + 1,
                        updated_at=now,
                    )
                )
                self._write_audit(
                    connection,
                    event_type="world.tick.completed",
                    actor_id=user_id,
                    subject_id=tick_id,
                    details={
                        "trigger_type": trigger_type.value,
                        "selected_island_id": island_id,
                        "next_action": action,
                        "calibrated_understanding_id": (
                            snapshot.understanding_ids[-1] if snapshot.understanding_ids else ""
                        ),
                        "understanding_affects_direction": calibration is not None,
                        "context_snapshot_id": snapshot.id,
                    },
                    occurred_at=now,
                )
                result = self._run_fixture_encounter(
                    connection,
                    tick_id=tick_id,
                    fixture_version=choice.fixture_version,
                    island_id=island_id,
                    actor_row=lifeform_row,
                    actor_user_id=user_id,
                    occurred_at=now,
                    trace_id=trace_id,
                    seed=f"{user_id}:{idempotency_key}",
                )
                connection.execute(update(world_ticks).where(world_ticks.c.id == tick_id)
                    .values(match_payload=result))
            return self.get_tick(tick_id)
        except IntegrityError:
            with self._engine.connect() as connection:
                existing = connection.execute(
                    select(world_ticks).where(
                        world_ticks.c.user_id == user_id,
                        world_ticks.c.idempotency_key == idempotency_key,
                    )
                ).mappings().first()
                if existing:
                    return self._tick_from_row(existing)
            raise

    def _run_fixture_encounter(
        self,
        connection,
        *,
        tick_id: str,
        fixture_version: str,
        island_id: str,
        actor_row,
        actor_user_id: str,
        occurred_at: datetime,
        trace_id: str,
        seed: str,
    ) -> dict:
        island = get_islands(fixture_version).by_id(island_id)
        if not island.design_ready:
            return {"status": "waiting", "reason": "这座岛的共同事件尚未开放，生命体会继续探索。"}
        repo = SqlMatchingRepository(self, connection)
        result, selected = choose_match(repo, user_id=actor_user_id, island=island,
            seed=seed, now=occurred_at)
        repo.audit("matching.decided", actor_user_id, tick_id,
            {"status": result["status"], "candidate_count": len(result["candidates"]),
             "rule_version": result["rule_version"]})
        if selected is None:
            return result
        actor_user = connection.execute(
            select(users).where(users.c.id == actor_user_id)
        ).mappings().one()
        companion_row = connection.execute(select(lifeforms).where(
            lifeforms.c.id == selected.lifeform_id)).mappings().one()
        companion_user = connection.execute(
            select(users).where(users.c.id == companion_row["user_id"])
        ).mappings().one()

        first_id, second_id = sorted((actor_row["id"], companion_row["id"]))
        relationship_row = connection.execute(
            select(relationships)
            .where(
                relationships.c.lifeform_a_id == first_id,
                relationships.c.lifeform_b_id == second_id,
            )
            .with_for_update()
        ).mappings().first()
        relationship_id = (
            relationship_row["id"]
            if relationship_row
            else relationship_id_for_pair(first_id, second_id)
        )
        previous_event_count = connection.execute(
            select(func.count())
            .select_from(encounters)
            .where(
                encounters.c.lifeform_a_id == first_id,
                encounters.c.lifeform_b_id == second_id,
                encounters.c.island_id == island_id,
                encounters.c.status == "completed",
            )
        ).scalar_one()
        encounter = build_fixture_encounter(
            tick_id=tick_id,
            fixture_version=fixture_version,
            island=island,
            actor=self._lifeform_from_row(actor_row),
            companion=self._lifeform_from_row(companion_row),
            previous_event_count=int(previous_event_count),
            relationship_id=relationship_id,
            occurred_at=occurred_at,
        )

        consent_by_lifeform = {
            actor_row["id"]: actor_user["consent_version"],
            companion_row["id"]: companion_user["consent_version"],
        }
        connection.execute(
            insert(encounters).values(
                id=encounter.id,
                world_tick_id=tick_id,
                island_id=island_id,
                lifeform_a_id=first_id,
                lifeform_b_id=second_id,
                consent_version_a=consent_by_lifeform[first_id],
                consent_version_b=consent_by_lifeform[second_id],
                fixture_version=fixture_version,
                status=encounter.status,
                outcome_summary=encounter.outcome_summary,
                trace_id=trace_id,
                created_at=occurred_at,
                completed_at=occurred_at,
                match_payload={k: result[k] for k in ("reason", "actor_snapshot_id",
                    "companion_snapshot_id", "companion_is_demo")},
            )
        )
        common_payload = {
            "event_id": encounter.event_id,
            "title": encounter.title,
            "dilemma": encounter.dilemma,
            "relationship_id": encounter.relationship_id,
            "shared_memory": encounter.shared_memory,
            "return_question": encounter.return_question,
            "source_mode": encounter.source_mode,
        }
        for turn in encounter.turns:
            connection.execute(
                insert(encounter_turns).values(
                    id=turn.id,
                    encounter_id=encounter.id,
                    turn_number=turn.turn_number,
                    actor_lifeform_id=turn.actor_lifeform_id,
                    action=turn.action.value,
                    public_utterance=turn.public_utterance,
                    proposal_payload={
                        **common_payload,
                        "reason_summary": turn.reason_summary,
                    },
                    validation_status="accepted",
                    created_at=occurred_at,
                )
            )

        previous_experiences = (
            list(relationship_row["shared_experiences"] or ())
            if relationship_row
            else []
        )
        headline = {
            "stability": "它们从不同答案里，看见了彼此",
            "intimacy": "它们在靠近与边界之间，学会了先询问",
            "ai_loneliness": "它们开始分辨被回应与被理解的不同",
        }[island_id]
        if relationship_row:
            connection.execute(
                update(relationships)
                .where(relationships.c.id == relationship_id)
                .values(
                    status=RelationshipStatus.ACTIVE.value,
                    last_island_id=island_id,
                    headline=headline,
                    shared_experiences=[*previous_experiences, encounter.shared_memory],
                    encounter_count=relationships.c.encounter_count + 1,
                    source_mode="live",
                    projection_version=relationships.c.projection_version + 1,
                    updated_at=occurred_at,
                )
            )
        else:
            connection.execute(
                insert(relationships).values(
                    id=relationship_id,
                    lifeform_a_id=first_id,
                    lifeform_b_id=second_id,
                    status=RelationshipStatus.ACTIVE.value,
                    last_island_id=island_id,
                    headline=headline,
                    shared_experiences=[encounter.shared_memory],
                    encounter_count=1,
                    source_mode="live",
                    projection_version=1,
                    ended_at=None,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
            )
        connection.execute(
            insert(relationship_events).values(
                id=uuid4().hex,
                relationship_id=relationship_id,
                event_type="encounter_completed",
                previous_status=(
                    relationship_row["status"]
                    if relationship_row
                    else RelationshipStatus.ACTIVE.value
                ),
                proposed_status=None,
                committed_status=RelationshipStatus.ACTIVE.value,
                encounter_id=encounter.id,
                actor_user_id=actor_user_id,
                dimensions_delta={"curiosity": 1, "respect": 1},
                evidence_refs={
                    "encounter_id": encounter.id,
                    "turn_ids": [turn.id for turn in encounter.turns],
                },
                trace_id=trace_id,
                occurred_at=occurred_at,
            )
        )
        connection.execute(
            update(lifeforms)
            .where(lifeforms.c.id == actor_row["id"])
            .values(
                status=f"已从「{encounter.title}」带回一个问题",
                version=lifeforms.c.version + 1,
                updated_at=occurred_at,
            )
        )
        connection.execute(
            update(lifeforms)
            .where(lifeforms.c.id == companion_row["id"])
            .values(
                current_island_id=island_id,
                status=f"刚刚完成「{encounter.title}」",
                version=lifeforms.c.version + 1,
                updated_at=occurred_at,
            )
        )
        self._write_audit(
            connection,
            event_type="encounter.completed",
            actor_id=actor_row["id"],
            subject_id=encounter.id,
            details={
                "event_id": encounter.event_id,
                "turn_count": len(encounter.turns),
                "relationship_id": relationship_id,
                "relationship_status": RelationshipStatus.ACTIVE.value,
            },
            occurred_at=occurred_at,
        )
        finish_match(repo, (actor_user_id, selected.user_id), island_id, occurred_at)
        return {**result, "encounter_id": encounter.id}

    @property
    def audit_count(self) -> int:
        with self._engine.connect() as connection:
            return connection.execute(select(func.count()).select_from(audit_events)).scalar_one()

    def _get_memory(self, memory_id: str) -> Memory:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(memories).where(memories.c.id == memory_id)
            ).mappings().first()
            if row is None:
                raise NotFound(f"memory {memory_id!r} was not found")
            return self._memory_from_row(connection, row)

    @staticmethod
    def _insert_if_missing(connection, table, predicate, **values) -> None:
        # Demo bootstrap may be requested twice at once (for example by React
        # StrictMode).  A read-then-insert check is not atomic, so both
        # transactions can observe a missing row and race on the primary key.
        # Use each supported database's conflict-safe insert for this seed path.
        dialect = connection.dialect.name
        if dialect == "mysql":
            connection.execute(insert(table).prefix_with("IGNORE").values(**values))
            return
        if dialect == "sqlite":
            connection.execute(insert(table).prefix_with("OR IGNORE").values(**values))
            return
        primary_key = next(iter(table.primary_key.columns))
        if connection.execute(select(primary_key).where(predicate)).first() is None:
            connection.execute(insert(table).values(**values))

    @staticmethod
    def _write_audit(
        connection,
        *,
        event_type: str,
        actor_id: str,
        subject_id: str,
        details: dict[str, str | bool],
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            insert(audit_events).values(
                id=uuid4().hex,
                event_type=event_type,
                actor_id=actor_id,
                subject_id=subject_id,
                trace_id=current_trace_id(),
                redacted_details=details,
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def _user_from_row(row) -> UserState:
        return UserState(
            id=row["id"],
            display_name=row["display_name"],
            consent_version=row["consent_version"],
        )

    @staticmethod
    def _lifeform_from_row(row) -> Lifeform:
        appearance = row["appearance"]
        if isinstance(appearance, dict):
            appearance = appearance.get("palette", "未命名")
        return Lifeform(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            appearance=str(appearance),
            exploration_tendency=row["exploration_tendency"],
            current_island_id=row["current_island_id"],
            current_focus=row["current_focus"],
            status=row["status"],
        )

    @staticmethod
    def _relationship_from_row(row) -> Relationship:
        return Relationship(
            id=row["id"],
            lifeform_ids=(row["lifeform_a_id"], row["lifeform_b_id"]),
            status=RelationshipStatus(row["status"]),
            island_id=row["last_island_id"],
            headline=row["headline"],
            shared_experiences=tuple(row["shared_experiences"] or ()),
            encounter_count=int(row["encounter_count"]),
            source_mode=row["source_mode"],
        )

    @staticmethod
    def _encounter_from_rows(row, turn_rows) -> Encounter:
        if not turn_rows:
            raise NotFound(f"encounter {row['id']!r} has no accepted turns")
        payload = turn_rows[0]["proposal_payload"]
        turns = tuple(
            EncounterTurn(
                id=turn["id"],
                turn_number=turn["turn_number"],
                actor_lifeform_id=turn["actor_lifeform_id"],
                action=EncounterAction(turn["action"]),
                public_utterance=turn["public_utterance"] or "",
                reason_summary=turn["proposal_payload"].get("reason_summary", ""),
            )
            for turn in turn_rows
            if turn["validation_status"] == "accepted"
        )
        return Encounter(
            id=row["id"],
            world_tick_id=row["world_tick_id"],
            island_id=row["island_id"],
            fixture_version=row["fixture_version"],
            event_id=payload["event_id"],
            title=payload["title"],
            dilemma=payload["dilemma"],
            lifeform_ids=(row["lifeform_a_id"], row["lifeform_b_id"]),
            status=row["status"],
            turns=turns,
            outcome_summary=row["outcome_summary"] or "",
            relationship_id=payload["relationship_id"],
            shared_memory=payload["shared_memory"],
            return_question=payload["return_question"],
            source_mode="fixture",
            match_reason=(row["match_payload"] or {}).get("reason", ""),
            actor_snapshot_id=(row["match_payload"] or {}).get("actor_snapshot_id"),
            companion_snapshot_id=(row["match_payload"] or {}).get("companion_snapshot_id"),
            companion_is_demo=(row["match_payload"] or {}).get("companion_is_demo", False),
            created_at=_utc(row["created_at"]),
            completed_at=_utc(row["completed_at"]),
        )

    def _memory_from_row(self, connection, row) -> Memory:
        evidence_ids = tuple(
            connection.execute(
                select(memory_evidence.c.evidence_id)
                .where(memory_evidence.c.memory_id == row["id"])
                .order_by(memory_evidence.c.evidence_id)
            ).scalars().all()
        )
        decision = connection.execute(
            select(memory_revisions.c.decision)
            .where(memory_revisions.c.memory_id == row["id"])
            .where(memory_revisions.c.decision.in_(tuple(d.value for d in CalibrationDecision)))
            .order_by(memory_revisions.c.occurred_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return Memory(
            id=row["id"],
            lifeform_id=row["lifeform_id"],
            kind=row["memory_type"],
            statement=row["statement"],
            status=row["status"],
            confidence=float(row["confidence"]),
            evidence_ids=evidence_ids,
            allow_social_recommendation=bool(row["allow_social_recommendation"]),
            version=int(row["version"]),
            supersedes_id=row["supersedes_memory_id"],
            calibration=CalibrationDecision(decision) if decision in {d.value for d in CalibrationDecision} else None,
            topic_code=row["topic_code"],
            score=float(row["score"]),
            score_updated_at=_utc(row["score_updated_at"]),
            expires_at=_utc(row["expires_at"]) if row["expires_at"] else None,
            updated_at=_utc(row["updated_at"]),
        )

    @staticmethod
    def _evidence_values(record: EvidenceRecord) -> dict:
        return {
            "id": record.id,
            "ingestion_key": record.ingestion_key,
            "user_id": record.user_id,
            "snapshot_id": record.snapshot_id,
            "source_type": record.source.value,
            "source_ref": record.source_ref,
            "content_text": record.content_text,
            "topic_code": record.topic_code,
            "authored_by_user": record.authored_by_user,
            "self_reference": record.self_reference,
            "assertion_mode": record.assertion_mode,
            "polarity": record.polarity,
            "confidence": record.confidence,
            "consent_version": record.consent_version,
            "is_sensitive": record.is_sensitive,
            "allow_social_recommendation": record.allow_social_recommendation,
            "source_occurred_at": record.source_occurred_at,
            "created_at": record.created_at,
        }

    @staticmethod
    def _evidence_from_row(row) -> EvidenceRecord:
        return EvidenceRecord(
            id=row["id"],
            user_id=row["user_id"],
            ingestion_key=row["ingestion_key"],
            source=EvidenceSource(row["source_type"]),
            content_text=row["content_text"],
            source_ref=row["source_ref"],
            topic_code=row["topic_code"],
            authored_by_user=bool(row["authored_by_user"]),
            self_reference=bool(row["self_reference"]),
            assertion_mode=row["assertion_mode"],
            polarity=row["polarity"],
            confidence=float(row["confidence"]),
            consent_version=int(row["consent_version"]),
            is_sensitive=bool(row["is_sensitive"]),
            allow_social_recommendation=bool(row["allow_social_recommendation"]),
            snapshot_id=row["snapshot_id"],
            source_occurred_at=(
                _utc(row["source_occurred_at"])
                if row["source_occurred_at"] is not None
                else None
            ),
            created_at=_utc(row["created_at"]),
        )

    @staticmethod
    def _tick_from_row(row) -> WorldTick:
        return WorldTick(
            id=row["id"],
            user_id=row["user_id"],
            lifeform_id=row["lifeform_id"],
            trigger_type=TriggerType(row["trigger_type"]),
            idempotency_key=row["idempotency_key"],
            selected_island_id=row["selected_island_id"],
            fixture_version=row["fixture_version"],
            context_snapshot_id=row["context_snapshot_id"],
            matching_status=(row["match_payload"] or {}).get("status", "waiting"),
            match_reason=(row["match_payload"] or {}).get("reason", ""),
            encounter_id=(row["match_payload"] or {}).get("encounter_id"),
            decision_reason=row["decision_reason"],
            status="completed",
            source_mode="live",
            trace_id=row["trace_id"],
            created_at=_utc(row["completed_at"] or row["started_at"]),
        )
