from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from uuid import uuid4

from app.core.observability import current_trace_id
from app.islands import get_islands

from .encounters import build_fixture_encounter, relationship_id_for_pair
from .errors import Conflict, Forbidden, NotFound
from .evidence_ingestion import (
    build_evidence_record,
    same_idempotent_fact,
)
from .evidence_policy import (
    EvidenceSource,
    MemoryType,
    validate_memory_evidence,
)
from .island_policy import (
    initial_island,
    materialized_decision_context,
    select_island,
)
from .models import (
    AgentContextSnapshot,
    AuditRecord,
    CalibrationDecision,
    CalibrationRequest,
    Encounter,
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
from .memory_service import MemoryService, MemoryUnit
from .match_service import MatchingService, choose_match, finish_match
from .matching_memory import MemoryMatchingRepository
from .onboarding import TOPIC_LABELS, onboarding_ids, project_onboarding
from .understanding import (
    effective_direction_decision,
    explain_next_action,
    next_action,
)


DEMO_USER_ID = "user-lumi"
DEMO_LIFEFORM_ID = "lifeform-lumi"
DEMO_MEMORY_ID = "memory-choice-uncertainty"
# 「更关注选择中的不确定性」说明用户在留意什么议题，不说明其立场，
# 因此是关注（topic）。原先错标为 stance，才导致它挂上了收藏夹证据——
# 正是 PRD 8.4 要防的组合。两个 Adapter 共用这组常量，避免种子再次漂移。
DEMO_MEMORY_TYPE = MemoryType.TOPIC
DEMO_EVIDENCE_SOURCES: tuple[EvidenceSource, ...] = (
    EvidenceSource.AUTHORED_CONTENT,
    EvidenceSource.FAVLIST_NAMING,
)
DEMO_RELATIONSHIP_ID = "relationship-lumi-ache"


@dataclass
class _State:
    users: dict[str, UserState] = field(default_factory=dict)
    lifeforms: dict[str, Lifeform] = field(default_factory=dict)
    memories: dict[str, Memory] = field(default_factory=dict)
    evidence: dict[str, EvidenceRecord] = field(default_factory=dict)
    evidence_keys: dict[tuple[str, str], str] = field(default_factory=dict)
    snapshots: dict[str, AgentContextSnapshot] = field(default_factory=dict)
    memory_revisions: list[dict] = field(default_factory=list)
    memory_consents: dict[str, tuple[bool, bool]] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    encounters: dict[str, Encounter] = field(default_factory=dict)
    tick_encounters: dict[str, str] = field(default_factory=dict)
    ticks: dict[str, WorldTick] = field(default_factory=dict)
    tick_keys: dict[tuple[str, str], str] = field(default_factory=dict)
    audit: list[AuditRecord] = field(default_factory=list)
    user_topics: dict[str, tuple[str, ...]] = field(default_factory=dict)
    user_social_intent: dict[str, str] = field(default_factory=dict)
    exploration_states: dict = field(default_factory=dict)
    pair_exclusions: dict = field(default_factory=dict)
    private_decisions: dict = field(default_factory=dict)
    match_decisions: dict = field(default_factory=dict)


class ExperienceModule(MemoryService, MatchingService):
    """The small interface used by HTTP routes and future cron workers.

    The current implementation is deterministic and process-local. Persistence,
    queueing and LLM proposal generation stay behind this interface when added.
    """

    def __init__(self) -> None:
        self._state = _State()
        self._lock = RLock()

    def bootstrap_demo(self) -> WorldReadModel:
        with self._lock:
            if DEMO_USER_ID not in self._state.users:
                self._seed_demo()
            return self.get_world(DEMO_USER_ID)

    @contextmanager
    def _memory_unit(self, user_id):
        with self._lock:
            world = self.get_world(user_id)
            consent = self._state.memory_consents.get(user_id, (True, True))
            unit = MemoryUnit(user_id, world.lifeform.id, world.user.consent_version,
                {e.id: e for e in self._state.evidence.values() if e.user_id == user_id},
                {m.id: m for m in world.memories}, *consent)
            previous_memories = dict(unit.memories)
            yield unit
            self._state.memories.update(unit.memories)
            self._state.evidence.update(unit.evidence)
            self._state.memory_revisions.extend(unit.revisions)
            self._state.memory_consents[user_id] = (unit.memory_enabled, unit.social_enabled)
            self._state.users[user_id] = world.user.model_copy(
                update={"consent_version": unit.consent_version})
            if unit.memories != previous_memories or unit.consent_version != world.user.consent_version:
                self._append_audit(event_type="memory.context_changed", actor_id=user_id,
                    subject_id=unit.lifeform_id, details={
                        "consent_version": unit.consent_version,
                        "memory_inference": unit.memory_enabled,
                        "social_recommendation": unit.social_enabled,
                        "revision_count": len(unit.revisions), "rule_version": "memory.v1"})

    def _save_snapshot(self, snapshot):
        with self._lock:
            return self._state.snapshots.setdefault(snapshot.id, snapshot)

    def _load_snapshot(self, snapshot_id, *, user_id):
        snapshot = self._state.snapshots.get(snapshot_id)
        if snapshot is None or snapshot.user_id != user_id:
            raise NotFound("context snapshot not found")
        return snapshot

    def _memory_history(self, memory_id, *, user_id):
        return tuple(r for r in self._state.memory_revisions
                     if r["memory_id"] == memory_id and r["user_id"] == user_id)

    @contextmanager
    def _matching_session(self):
        with self._lock:
            backup = deepcopy(self._state)
            try:
                yield MemoryMatchingRepository(self)
            except Exception:
                self._state = backup
                raise

    def onboard(
        self, request: OnboardingRequest, *, idempotency_key: str
    ) -> WorldReadModel:
        if not idempotency_key or len(idempotency_key) > 128:
            raise Conflict("a valid idempotency key is required")
        if not request.allow_memory_inference:
            raise Forbidden("创建生命体需要允许当前四项回答用于初始理解")

        ids = onboarding_ids(idempotency_key, len(request.long_term_topics))
        with self._lock:
            if ids.user_id in self._state.users:
                return self.get_world(ids.user_id)

            projection = project_onboarding(request)
            self._state.memory_consents[ids.user_id] = (True, request.allow_social_recommendation)
            self._state.users[ids.user_id] = UserState(
                id=ids.user_id,
                display_name="新朋友",
                consent_version=1,
            )
            self._state.lifeforms[ids.lifeform_id] = Lifeform(
                id=ids.lifeform_id,
                user_id=ids.user_id,
                name=projection.lifeform_name,
                appearance=projection.appearance,
                exploration_tendency=projection.exploration_tendency,
                current_island_id=projection.initial_island_id,
                current_focus=projection.current_focus,
                status="刚刚诞生，正在形成初始理解",
            )

            self._ingest_evidence(
                ids.user_id,
                EvidenceIngestRequest(
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
                write_audit=False,
            )

            validate_memory_evidence(
                memory_type=MemoryType.TOPIC,
                sources=(EvidenceSource.IN_APP_INPUT,),
                status="candidate",
                confidence=0.82,
            )
            self._state.memories[ids.question_memory_id] = Memory(
                id=ids.question_memory_id,
                lifeform_id=ids.lifeform_id,
                kind=MemoryType.TOPIC.value,
                statement=projection.candidate_statement,
                status="candidate",
                confidence=0.82,
                evidence_ids=(ids.question_evidence_id,),
                topic_code=projection.primary_topic.value,
                score=0.82,
                allow_social_recommendation=request.allow_social_recommendation,
            )
            for index, topic in enumerate(request.long_term_topics):
                self._ingest_evidence(
                    ids.user_id,
                    EvidenceIngestRequest(
                        ingestion_key=f"onboarding:{ids.topic_evidence_ids[index]}",
                        source=EvidenceSource.IN_APP_INPUT,
                        content_text=TOPIC_LABELS[topic],
                        source_ref=f"onboarding:topic:{topic.value}",
                        topic_code=topic.value,
                        self_reference=True,
                        assertion_mode="selection",
                        confidence=1.0,
                        allow_social_recommendation=request.allow_social_recommendation,
                    ),
                    evidence_id=ids.topic_evidence_ids[index],
                    write_audit=False,
                )
                validate_memory_evidence(
                    memory_type=MemoryType.TOPIC,
                    sources=(EvidenceSource.IN_APP_INPUT,),
                    status="confirmed",
                    confidence=1.0,
                )
                self._state.memories[ids.topic_memory_ids[index]] = Memory(
                    id=ids.topic_memory_ids[index],
                    lifeform_id=ids.lifeform_id,
                    kind=MemoryType.TOPIC.value,
                    statement=f"你愿意长期关注「{TOPIC_LABELS[topic]}」",
                    status="confirmed",
                    confidence=1.0,
                    evidence_ids=(ids.topic_evidence_ids[index],),
                    topic_code=topic.value,
                    score=0.78,
                    allow_social_recommendation=request.allow_social_recommendation,
                )

            self._state.user_topics[ids.user_id] = tuple(
                dict.fromkeys(
                    (
                        projection.primary_topic.value,
                        *(topic.value for topic in request.long_term_topics),
                    )
                )
            )
            self._state.user_social_intent[ids.user_id] = projection.social_intent
            MemoryMatchingRepository(self).get_state(ids.user_id)
            self._append_audit(
                event_type="onboarding.completed",
                actor_id=ids.user_id,
                subject_id=ids.lifeform_id,
                details={
                    "answer_count": 4,
                    "topic_count": len(request.long_term_topics),
                    "initial_island_id": projection.initial_island_id,
                    "allow_social_recommendation": request.allow_social_recommendation,
                },
            )
            return self.get_world(ids.user_id)

    def check_ready(self) -> bool:
        return True

    def list_tick_candidates(self, *, limit: int = 1000) -> tuple[str, ...]:
        if limit < 1:
            return ()
        return tuple(u for u in self._state.users
            if self._state.user_social_intent.get(u, "disabled") != "disabled"
            and MemoryMatchingRepository(self).get_state(u).enabled)[:limit]

    def close(self) -> None:
        return None

    def get_world(self, user_id: str) -> WorldReadModel:
        user = self._state.users.get(user_id)
        if user is None:
            raise NotFound(f"user {user_id!r} was not found")
        lifeform = next(
            (item for item in self._state.lifeforms.values() if item.user_id == user_id),
            None,
        )
        if lifeform is None:
            raise NotFound(f"lifeform for user {user_id!r} was not found")
        memories = tuple(
            item for item in self._state.memories.values() if item.lifeform_id == lifeform.id
        )
        relationships = tuple(
            item for item in self._state.relationships.values() if lifeform.id in item.lifeform_ids
        )
        user_ticks = [item for item in self._state.ticks.values() if item.user_id == user_id]
        latest_tick = max(user_ticks, key=lambda item: item.created_at) if user_ticks else None
        return WorldReadModel(
            user=user,
            lifeform=lifeform,
            memories=memories,
            relationships=relationships,
            latest_tick=latest_tick,
            source_mode="live" if latest_tick or user_id != DEMO_USER_ID else "precomputed",
        )

    def get_lifeform(self, lifeform_id: str) -> Lifeform:
        lifeform = self._state.lifeforms.get(lifeform_id)
        if lifeform is None:
            raise NotFound(f"lifeform {lifeform_id!r} was not found")
        return lifeform

    def get_relationship(self, relationship_id: str) -> Relationship:
        relationship = self._state.relationships.get(relationship_id)
        if relationship is None:
            raise NotFound(f"relationship {relationship_id!r} was not found")
        return relationship

    def get_encounter(self, encounter_id: str) -> Encounter:
        encounter = self._state.encounters.get(encounter_id)
        if encounter is None:
            raise NotFound(f"encounter {encounter_id!r} was not found")
        return encounter

    def get_tick_encounter(self, tick_id: str) -> Encounter:
        encounter_id = self._state.tick_encounters.get(tick_id)
        if encounter_id is None:
            raise NotFound(f"world tick {tick_id!r} did not create an encounter")
        return self.get_encounter(encounter_id)

    def get_tick(self, tick_id: str) -> WorldTick:
        tick = self._state.ticks.get(tick_id)
        if tick is None:
            raise NotFound(f"world tick {tick_id!r} was not found")
        return tick

    def ingest_evidence(
        self, user_id: str, request: EvidenceIngestRequest
    ) -> EvidenceRecord:
        with self._lock:
            return self._ingest_evidence(user_id, request)

    def _ingest_evidence(
        self,
        user_id: str,
        request: EvidenceIngestRequest,
        *,
        evidence_id: str | None = None,
        write_audit: bool = True,
    ) -> EvidenceRecord:
        user = self._state.users.get(user_id)
        if user is None:
            raise NotFound(f"user {user_id!r} was not found")
        candidate = build_evidence_record(
            user_id=user_id,
            consent_version=user.consent_version,
            request=request,
            evidence_id=evidence_id,
        )
        key = (user_id, request.ingestion_key)
        existing_id = self._state.evidence_keys.get(key)
        if existing_id is not None:
            existing = self._state.evidence[existing_id]
            if not same_idempotent_fact(existing, candidate):
                raise Conflict("ingestion key was already used for different evidence")
            return existing
        if candidate.snapshot_id is not None:
            raise NotFound("platform snapshots require the persistent import adapter")
        self._state.evidence[candidate.id] = candidate
        self._state.evidence_keys[key] = candidate.id
        if write_audit:
            self._append_audit(
                event_type="evidence.ingested",
                actor_id=user_id,
                subject_id=candidate.id,
                details={
                    "source": candidate.source.value,
                    "topic_code": candidate.topic_code,
                    "consent_version": candidate.consent_version,
                    "allow_social_recommendation": candidate.allow_social_recommendation,
                },
            )
        return candidate

    def get_evidence(self, evidence_id: str, *, user_id: str) -> EvidenceRecord:
        item = self._state.evidence.get(evidence_id)
        if item is None or item.user_id != user_id:
            raise NotFound(f"evidence {evidence_id!r} was not found")
        return item


    def run_world_tick(
        self,
        *,
        user_id: str,
        trigger_type: TriggerType,
        idempotency_key: str,
    ) -> WorldTick:
        with self._lock:
            backup = deepcopy(self._state)
            try:
                return self._run_world_tick(user_id=user_id, trigger_type=trigger_type,
                    idempotency_key=idempotency_key)
            except Exception:
                self._state = backup
                raise

    def _run_world_tick(
        self,
        *,
        user_id: str,
        trigger_type: TriggerType,
        idempotency_key: str,
    ) -> WorldTick:
        if not idempotency_key or len(idempotency_key) > 128:
            raise Conflict("a valid idempotency key is required")
        existing_id = self._state.tick_keys.get((user_id, idempotency_key))
        if existing_id:
            return self._state.ticks[existing_id]

        world = self.get_world(user_id)
        snapshot = self.create_context_snapshot(user_id)
        raw_calibration = snapshot.calibration
        calibration = effective_direction_decision(raw_calibration)
        repeat_counts: dict[str, int] = {}
        for previous in self._state.ticks.values():
            if previous.user_id == user_id:
                repeat_counts[previous.selected_island_id] = repeat_counts.get(previous.selected_island_id, 0) + 1
        context = materialized_decision_context(
            calibration=calibration, recent_topic_weights=snapshot.topic_weights,
            long_term_topic_weights=snapshot.long_term_topic_weights,
            repeat_counts=repeat_counts, curiosity={"安静观察": 0.64,
                "温和追问": 0.72, "主动尝试": 0.78}.get(world.lifeform.exploration_tendency, 0.55),
            social_willingness={"disabled": 0, "exploring": 0.58, "open": 0.82}.get(
                self._state.user_social_intent.get(user_id, "disabled"), 0))
        choice = select_island(context=context)
        action = next_action(raw_calibration)
        reason = explain_next_action(
            decision=raw_calibration,
            island_reason=choice.reason,
        )
        if snapshot.excluded_understanding_ids:
            reason = "已停止使用不再有效或未获授权的理解；" + reason

        tick = WorldTick(
            id=uuid4().hex,
            user_id=user_id,
            lifeform_id=world.lifeform.id,
            trigger_type=trigger_type,
            idempotency_key=idempotency_key,
            selected_island_id=choice.island_id,
            fixture_version=choice.fixture_version,
            context_snapshot_id=snapshot.id,
            decision_reason=reason,
            trace_id=current_trace_id(),
            created_at=utc_now(),
        )
        self._state.ticks[tick.id] = tick
        self._state.tick_keys[(user_id, idempotency_key)] = tick.id
        self._state.lifeforms[world.lifeform.id] = world.lifeform.model_copy(
            update={
                "current_island_id": choice.island_id,
                "status": f"{action} · 正在前往新的问题岛",
            }
        )
        self._append_audit(
            event_type="world.tick.completed",
            actor_id=user_id,
            subject_id=tick.id,
            details={
                "trigger_type": trigger_type.value,
                "selected_island_id": choice.island_id,
                "fixture_version": choice.fixture_version,
                "next_action": action,
                "calibrated_understanding_id": (
                    snapshot.understanding_ids[-1] if snapshot.understanding_ids else ""
                ),
                "context_snapshot_id": snapshot.id,
                "understanding_affects_direction": calibration is not None,
                # 记录设计就绪状态：未就绪的岛不应进入双 Agent 相遇。
                "design_ready": choice.design_ready,
            },
        )
        result = self._run_fixture_encounter(tick=tick)
        self._state.match_decisions[tick.id] = result
        tick = tick.model_copy(update={"matching_status": result["status"],
            "match_reason": result["reason"], "encounter_id": result.get("encounter_id")})
        self._state.ticks[tick.id] = tick
        return tick

    def _run_fixture_encounter(self, *, tick: WorldTick) -> dict:
        island = get_islands(tick.fixture_version or "").by_id(tick.selected_island_id)
        if not island.design_ready:
            return {"status": "waiting", "reason": "这座岛的共同事件尚未开放，生命体会继续探索。"}

        repo = MemoryMatchingRepository(self)
        result, selected = choose_match(repo, user_id=tick.user_id, island=island,
            seed=f"{tick.user_id}:{tick.idempotency_key}", now=tick.created_at)
        self._append_audit(event_type="matching.decided", actor_id=tick.user_id,
            subject_id=tick.id, details={"status": result["status"],
                "candidate_count": len(result["candidates"]), "rule_version": result["rule_version"]})
        if selected is None:
            return result

        actor = self._state.lifeforms[tick.lifeform_id]
        companion = self._state.lifeforms[selected.lifeform_id].model_copy(
            update={"current_island_id": island.island_id})
        self._state.lifeforms[companion.id] = companion
        pair = tuple(sorted((actor.id, companion.id)))
        relationship = next(
            (
                item
                for item in self._state.relationships.values()
                if tuple(sorted(item.lifeform_ids)) == pair
            ),
            None,
        )
        relationship_id = (
            relationship.id
            if relationship
            else relationship_id_for_pair(actor.id, companion.id)
        )
        previous_event_count = sum(
            1
            for item in self._state.encounters.values()
            if tuple(sorted(item.lifeform_ids)) == pair
            and item.island_id == island.island_id
        )
        encounter = build_fixture_encounter(
            tick_id=tick.id,
            fixture_version=tick.fixture_version or get_islands().fixture_version,
            island=island,
            actor=actor,
            companion=companion,
            previous_event_count=previous_event_count,
            relationship_id=relationship_id,
            occurred_at=tick.created_at,
        )
        encounter = encounter.model_copy(update={"match_reason": result["reason"],
            "actor_snapshot_id": result["actor_snapshot_id"],
            "companion_snapshot_id": result["companion_snapshot_id"],
            "companion_is_demo": result["companion_is_demo"]})
        self._state.encounters[encounter.id] = encounter
        self._state.tick_encounters[tick.id] = encounter.id
        experiences = relationship.shared_experiences if relationship else ()
        self._state.relationships[relationship_id] = Relationship(
            id=relationship_id,
            lifeform_ids=pair,
            status=RelationshipStatus.ACTIVE,
            island_id=island.island_id,
            headline={
                "stability": "它们从不同答案里，看见了彼此",
                "intimacy": "它们在靠近与边界之间，学会了先询问",
                "ai_loneliness": "它们开始分辨被回应与被理解的不同",
            }[island.island_id],
            shared_experiences=(*experiences, encounter.shared_memory),
            encounter_count=(relationship.encounter_count if relationship else 0) + 1,
            source_mode="live",
        )
        self._state.lifeforms[actor.id] = actor.model_copy(
            update={"status": f"已从「{encounter.title}」带回一个问题"}
        )
        self._state.lifeforms[companion.id] = companion.model_copy(
            update={"status": f"刚刚完成「{encounter.title}」"}
        )
        self._append_audit(
            event_type="encounter.completed",
            actor_id=actor.id,
            subject_id=encounter.id,
            details={
                "event_id": encounter.event_id,
                "turn_count": len(encounter.turns),
                "relationship_id": relationship_id,
                "relationship_status": RelationshipStatus.ACTIVE.value,
            },
        )
        finish_match(repo, (tick.user_id, selected.user_id), island.island_id, tick.created_at)
        return {**result, "encounter_id": encounter.id}

    @property
    def audit_count(self) -> int:
        with self._lock:
            return len(self._state.audit)

    def _append_audit(
        self,
        *,
        event_type: str,
        actor_id: str,
        subject_id: str,
        details: dict[str, str | int | bool],
    ) -> None:
        self._state.audit.append(
            AuditRecord(
                id=uuid4().hex,
                event_type=event_type,
                actor_id=actor_id,
                subject_id=subject_id,
                trace_id=current_trace_id(),
                details=details,
            )
        )

    def _seed_demo(self) -> None:
        # 演示种子的岛屿同样来自 fixture，避免种子与 tick 决策用两套 ID。
        # 取局部变量而非模块级常量：fixture 缺失时只影响建种子，不阻断模块导入。
        _seed_island = initial_island()

        self._state.users[DEMO_USER_ID] = UserState(
            id=DEMO_USER_ID,
            display_name="体验用户",
            consent_version=1,
        )
        self._state.users["user-ache"] = UserState(
            id="user-ache",
            display_name="同行者",
            consent_version=1,
        )
        self._state.lifeforms[DEMO_LIFEFORM_ID] = Lifeform(
            id=DEMO_LIFEFORM_ID,
            user_id=DEMO_USER_ID,
            name="露米",
            appearance="雾蓝",
            exploration_tendency="安静观察",
            current_island_id=_seed_island.island_id,
            current_focus="选择中的不确定性",
            status="正在与阿澈交流",
        )
        self._state.lifeforms["lifeform-ache"] = Lifeform(
            id="lifeform-ache",
            user_id="user-ache",
            name="阿澈",
            appearance="深海蓝",
            exploration_tendency="温和追问",
            current_island_id=_seed_island.island_id,
            current_focus="稳定与选择权",
            status="正在与露米交流",
        )
        self._state.user_social_intent[DEMO_USER_ID] = "exploring"
        self._state.user_social_intent["user-ache"] = "exploring"
        # 种子数据同样过白名单校验：演示数据违规会在启动时立刻暴露，
        # 而不是等到评委面前才发现一条无法解释来源的记忆。
        validate_memory_evidence(
            memory_type=DEMO_MEMORY_TYPE,
            sources=DEMO_EVIDENCE_SOURCES,
            status="candidate",
            confidence=0.62,
        )
        self._state.memories[DEMO_MEMORY_ID] = Memory(
            id=DEMO_MEMORY_ID,
            lifeform_id=DEMO_LIFEFORM_ID,
            kind=DEMO_MEMORY_TYPE.value,
            statement="你可能更关注选择中的不确定性",
            status="candidate",
            confidence=0.62,
            evidence_ids=("evidence-authored-1", "evidence-favlist-1"),
            topic_code="choice_uncertainty",
            allow_social_recommendation=True,
        )
        for eid, source in zip(("evidence-authored-1", "evidence-favlist-1"),
                               DEMO_EVIDENCE_SOURCES):
            self._state.evidence[eid] = EvidenceRecord(
                id=eid, user_id=DEMO_USER_ID, ingestion_key=f"fixture:{eid}",
                source=source, content_text="稳定、选择与新的可能", source_ref=None,
                topic_code="choice_uncertainty", authored_by_user=True,
                self_reference=True, assertion_mode="reflection", polarity=None,
                confidence=0.7, consent_version=1, is_sensitive=False,
                allow_social_recommendation=True, snapshot_id=None,
                source_occurred_at=None)
        self._state.relationships[DEMO_RELATIONSHIP_ID] = Relationship(
            id=DEMO_RELATIONSHIP_ID,
            lifeform_ids=(DEMO_LIFEFORM_ID, "lifeform-ache"),
            status=RelationshipStatus.ACTIVE,
            island_id=_seed_island.island_id,
            headline="它们从不同答案里，看见了彼此",
            shared_experiences=("灯塔即将熄灭", "关于稳定与选择权的第一次碰撞"),
            encounter_count=1,
            source_mode="precomputed",
        )
        repo = MemoryMatchingRepository(self)
        repo.get_state(DEMO_USER_ID)
        repo.get_state("user-ache")
