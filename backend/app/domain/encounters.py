"""压缩版 MVP 相遇执行器。

事件情境来自已审核 fixture；执行器只在动作白名单内生成三步以内的确定性
回放。它不冒充实时 LLM，但提供与未来模型提议器相同的结构化结果。
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from app.islands import Island

from .models import (
    Encounter,
    EncounterAction,
    EncounterTurn,
    Lifeform,
    RelationshipStage,
)


_SHARED_MEMORY = {
    "stability": "选择可以不同，但彼此都希望保有自主决定的权利。",
    "intimacy": "靠近的方式可以不同，但双方都重视边界被看见。",
    "ai_loneliness": "对技术陪伴的期待可以不同，但双方都在意真实回应的来处。",
}

_HEADLINE = {
    "stability": "它们从不同答案里，看见了彼此",
    "intimacy": "它们在靠近与边界之间，学会了先询问",
    "ai_loneliness": "它们开始分辨被回应与被理解的不同",
}


def encounter_id_for_tick(tick_id: str) -> str:
    return uuid5(NAMESPACE_URL, f"weijian:encounter:{tick_id}").hex


def relationship_id_for_pair(lifeform_a_id: str, lifeform_b_id: str) -> str:
    first, second = sorted((lifeform_a_id, lifeform_b_id))
    return uuid5(NAMESPACE_URL, f"weijian:relationship:{first}:{second}").hex


def advance_relationship(stage: RelationshipStage) -> RelationshipStage:
    return {
        RelationshipStage.UNMET: RelationshipStage.SHARED_EXPERIENCE,
        RelationshipStage.NOTICED: RelationshipStage.SHARED_EXPERIENCE,
        RelationshipStage.SHARED_EXPERIENCE: RelationshipStage.CARED,
        RelationshipStage.CARED: RelationshipStage.CONNECTION_CANDIDATE,
    }.get(stage, stage)


def build_fixture_encounter(
    *,
    tick_id: str,
    fixture_version: str,
    island: Island,
    actor: Lifeform,
    companion: Lifeform,
    previous_event_count: int,
    relationship_id: str,
    relationship_before: RelationshipStage,
    occurred_at: datetime,
) -> Encounter:
    if not island.design_ready or not island.events:
        raise ValueError(f"island {island.island_id!r} is not ready for encounters")

    event = island.events[previous_event_count % len(island.events)]
    encounter_id = encounter_id_for_tick(tick_id)
    first_action = {
        "安静观察": EncounterAction.OBSERVE,
        "温和追问": EncounterAction.RESPOND,
        "主动尝试": EncounterAction.APPROACH,
    }.get(actor.exploration_tendency, EncounterAction.OBSERVE)
    allowed = set(event["available_actions"])
    if first_action.value not in allowed:
        first_action = EncounterAction.OBSERVE

    planned = (
        (
            actor.id,
            first_action,
            f"面对「{event['title']}」，我想先听听你最不愿失去的是什么。",
            "依据已授权的探索倾向，先理解情境与对方。",
        ),
        (
            companion.id,
            EncounterAction.RESPOND,
            "我的答案可能不同，但我愿意说明自己在意的代价。",
            "回应当前事件，不推断或代表主人的私人立场。",
        ),
        (
            actor.id,
            EncounterAction.COOPERATE,
            "我们可以保留不同答案，再看看是否仍愿意继续理解彼此。",
            "在不消除差异的前提下完成一次有限共同经历。",
        ),
    )
    usable = tuple(item for item in planned if item[1].value in allowed)
    turn_count = min(int(event["max_turns"]), len(usable))
    turns = tuple(
        EncounterTurn(
            id=uuid5(NAMESPACE_URL, f"{encounter_id}:turn:{number}").hex,
            turn_number=number,
            actor_lifeform_id=item[0],
            action=item[1],
            public_utterance=item[2],
            reason_summary=item[3],
        )
        for number, item in enumerate(usable[:turn_count], start=1)
    )
    after = advance_relationship(relationship_before)
    shared_memory = _SHARED_MEMORY[island.island_id]
    return Encounter(
        id=encounter_id,
        world_tick_id=tick_id,
        island_id=island.island_id,
        fixture_version=fixture_version,
        event_id=event["event_id"],
        title=event["title"],
        dilemma=event["dilemma"],
        lifeform_ids=(actor.id, companion.id),
        status="completed",
        turns=turns,
        outcome_summary=f"它们完成了「{event['title']}」，答案不同，但愿意继续理解彼此。",
        relationship_id=relationship_id,
        relationship_before=relationship_before,
        relationship_after=after,
        shared_memory=shared_memory,
        return_question=event["return_question"],
        created_at=occurred_at,
        completed_at=occurred_at,
    )
