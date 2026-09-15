from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from uuid import uuid4

from app.core.observability import current_trace_id
from app.islands import get_islands

from .encounters import build_fixture_encounter, relationship_id_for_pair
from .errors import Conflict, Forbidden, NotFound
from .evidence_policy import (
    EvidenceSource,
    MemoryType,
    validate_memory_evidence,
)
from .island_policy import (
    demo_decision_context,
    initial_island,
    materialized_decision_context,
    select_island,
    topic_code_for,
)
from .models import (
    AuditRecord,
    CalibrationDecision,
    CalibrationRequest,
    Encounter,
    Lifeform,
    Memory,
    OnboardingRequest,
    Relationship,
    RelationshipStage,
    TriggerType,
    UserState,
    WorldReadModel,
    WorldTick,
    utc_now,
)
from .onboarding import TOPIC_LABELS, onboarding_ids, project_onboarding
from .understanding import (
    calibration_effect,
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
    relationships: dict[str, Relationship] = field(default_factory=dict)
    encounters: dict[str, Encounter] = field(default_factory=dict)
    tick_encounters: dict[str, str] = field(default_factory=dict)
    ticks: dict[str, WorldTick] = field(default_factory=dict)
    tick_keys: dict[tuple[str, str], str] = field(default_factory=dict)
    audit: list[AuditRecord] = field(default_factory=list)
    user_topics: dict[str, tuple[str, ...]] = field(default_factory=dict)
    user_social_intent: dict[str, str] = field(default_factory=dict)


class ExperienceModule:
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
                allow_social_recommendation=request.allow_social_recommendation,
            )
            for index, topic in enumerate(request.long_term_topics):
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
        return tuple(self._state.users)[:limit]

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

    def calibrate_memory(self, memory_id: str, request: CalibrationRequest) -> Memory:
        with self._lock:
            return self._calibrate_memory(memory_id, request)

    def _calibrate_memory(self, memory_id: str, request: CalibrationRequest) -> Memory:
        memory = self._state.memories.get(memory_id)
        if memory is None:
            raise NotFound(f"memory {memory_id!r} was not found")
        lifeform = self.get_lifeform(memory.lifeform_id)
        if lifeform.user_id != request.user_id:
            raise NotFound(f"memory {memory_id!r} was not found")

        effect = calibration_effect(request.decision)
        updated = memory.model_copy(
            update={
                "status": effect.status,
                "calibration": request.decision,
                "allow_social_recommendation": request.allow_social_recommendation,
                "updated_at": utc_now(),
            }
        )
        self._state.memories[memory_id] = updated

        self._state.lifeforms[lifeform.id] = lifeform.model_copy(
            update={"current_focus": effect.focus}
        )
        self._append_audit(
            event_type="memory.calibrated",
            actor_id=request.user_id,
            subject_id=memory_id,
            details={
                "decision": request.decision.value,
                "allow_social_recommendation": request.allow_social_recommendation,
            },
        )
        return updated

    def run_world_tick(
        self,
        *,
        user_id: str,
        trigger_type: TriggerType,
        idempotency_key: str,
    ) -> WorldTick:
        with self._lock:
            return self._run_world_tick(
                user_id=user_id,
                trigger_type=trigger_type,
                idempotency_key=idempotency_key,
            )

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
        calibrated_memories = tuple(
            memory for memory in world.memories if memory.calibration is not None
        )
        calibrated_memory = (
            max(calibrated_memories, key=lambda item: item.updated_at)
            if calibrated_memories
            else None
        )
        raw_calibration = calibrated_memory.calibration if calibrated_memory else None
        calibration = effective_direction_decision(raw_calibration)
        # Demo keeps its fixed regression context. Real onboarding users are
        # projected from their four explicit answers without exposing raw text.
        if user_id == DEMO_USER_ID:
            context = demo_decision_context(calibration)
        else:
            topic_codes = self._state.user_topics.get(
                user_id, (topic_code_for(world.lifeform.current_island_id),)
            )
            repeat_counts: dict[str, int] = {}
            for tick in self._state.ticks.values():
                if tick.user_id == user_id:
                    repeat_counts[tick.selected_island_id] = (
                        repeat_counts.get(tick.selected_island_id, 0) + 1
                    )
            social_willingness = {
                "disabled": 0.0,
                "exploring": 0.58,
                "open": 0.82,
            }.get(self._state.user_social_intent.get(user_id, "disabled"), 0.0)
            curiosity = {
                "安静观察": 0.64,
                "温和追问": 0.72,
                "主动尝试": 0.78,
            }.get(world.lifeform.exploration_tendency, 0.55)
            context = materialized_decision_context(
                calibration=calibration,
                recent_topic_weights={topic_codes[0]: 0.95},
                long_term_topic_weights={code: 0.78 for code in topic_codes},
                repeat_counts=repeat_counts,
                curiosity=curiosity,
                social_willingness=social_willingness,
            )
        choice = select_island(context=context)
        action = next_action(raw_calibration)
        reason = explain_next_action(
            decision=raw_calibration,
            island_reason=choice.reason,
        )

        tick = WorldTick(
            id=uuid4().hex,
            user_id=user_id,
            lifeform_id=world.lifeform.id,
            trigger_type=trigger_type,
            idempotency_key=idempotency_key,
            selected_island_id=choice.island_id,
            fixture_version=choice.fixture_version,
            decision_reason=reason,
            trace_id=current_trace_id(),
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
                    calibrated_memory.id if calibrated_memory else ""
                ),
                "understanding_affects_direction": calibration is not None,
                # 记录设计就绪状态：未就绪的岛不应进入双 Agent 相遇。
                "design_ready": choice.design_ready,
            },
        )
        self._run_fixture_encounter(tick=tick)
        return tick

    def _run_fixture_encounter(self, *, tick: WorldTick) -> None:
        island = get_islands(tick.fixture_version or "").by_id(tick.selected_island_id)
        if not island.design_ready:
            return
        if self._state.user_social_intent.get(tick.user_id, "disabled") == "disabled":
            return

        actor = self._state.lifeforms[tick.lifeform_id]
        candidates = sorted(
            (
                lifeform
                for lifeform in self._state.lifeforms.values()
                if lifeform.id != actor.id
                and lifeform.current_island_id == island.island_id
                and self._state.user_social_intent.get(lifeform.user_id, "disabled")
                != "disabled"
            ),
            key=lambda item: item.id,
        )
        if not candidates:
            return
        companion = candidates[0]
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
            relationship_before=(
                relationship.stage if relationship else RelationshipStage.UNMET
            ),
            occurred_at=tick.created_at,
        )
        self._state.encounters[encounter.id] = encounter
        self._state.tick_encounters[tick.id] = encounter.id
        experiences = relationship.shared_experiences if relationship else ()
        self._state.relationships[relationship_id] = Relationship(
            id=relationship_id,
            lifeform_ids=pair,
            stage=encounter.relationship_after,
            island_id=island.island_id,
            headline={
                "stability": "它们从不同答案里，看见了彼此",
                "intimacy": "它们在靠近与边界之间，学会了先询问",
                "ai_loneliness": "它们开始分辨被回应与被理解的不同",
            }[island.island_id],
            shared_experiences=(*experiences, encounter.shared_memory),
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
                "previous_stage": encounter.relationship_before.value,
                "committed_stage": encounter.relationship_after.value,
            },
        )

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
            allow_social_recommendation=True,
        )
        self._state.relationships[DEMO_RELATIONSHIP_ID] = Relationship(
            id=DEMO_RELATIONSHIP_ID,
            lifeform_ids=(DEMO_LIFEFORM_ID, "lifeform-ache"),
            stage=RelationshipStage.SHARED_EXPERIENCE,
            island_id=_seed_island.island_id,
            headline="它们从不同答案里，看见了彼此",
            shared_experiences=("灯塔即将熄灭", "关于稳定与选择权的第一次碰撞"),
            source_mode="precomputed",
        )
