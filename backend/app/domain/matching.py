"""Bounded, replayable candidate recall. No private text leaves this module."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from .memory_layer import aware, stable_id
from .models import AgentContextSnapshot, ExplorationState, ContextPurpose

MATCH_RULE_VERSION = "matching.v1"
MAX_CANDIDATES = 30
POOL_LIMIT = 120
ENCOUNTER_COOLDOWN_SECONDS = 600
PAIR_COOLDOWN_SECONDS = 86400
# Public editorial taxonomy, not inferred personal stances.
RELATED_TOPICS = {
    "choice_uncertainty": {"intimacy_and_autonomy"},
    "intimacy_and_autonomy": {"choice_uncertainty", "ai_and_loneliness"},
    "ai_and_loneliness": {"intimacy_and_autonomy"},
}
TOPIC_LABELS = {"choice_uncertainty": "稳定与选择", "intimacy_and_autonomy": "亲密与独立",
                "ai_and_loneliness": "AI与真实陪伴"}


@dataclass(frozen=True)
class MatchProfile:
    state: ExplorationState
    snapshot: AgentContextSnapshot
    consent_enabled: bool


@dataclass(frozen=True)
class MatchCandidate:
    lifeform_id: str
    user_id: str
    snapshot_id: str
    recall_source: str
    shared_topics: tuple[str, ...]
    encounter_count: int
    is_demo: bool
    score: float
    reason: str
    score_breakdown: dict[str, float]


def can_participate(profile: MatchProfile, now: datetime, topic: str) -> bool:
    s = profile.state
    return (s.enabled and s.social_pace != "observe_first" and profile.consent_enabled
        and s.availability == "available" and aware(s.available_at) <= now
        and topic not in s.excluded_topics and bool(profile.snapshot.topics)
        and profile.snapshot.purpose == ContextPurpose.SOCIAL_RECOMMENDATION)


def recall_candidates(*, actor: MatchProfile, pool: tuple[MatchProfile, ...],
    island_id: str, topic_code: str, seed: str, now: datetime,
    excluded_ids: frozenset[str] = frozenset(),
    encounter_counts: dict[str, int] | None = None, limit: int = MAX_CANDIDATES
) -> tuple[MatchCandidate, ...]:
    if not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("limit must be between 1 and 30")
    if not can_participate(actor, now, topic_code):
        return ()
    counts = encounter_counts or {}
    recalled = []
    for candidate in pool:
        state = candidate.state
        if state.lifeform_id == actor.state.lifeform_id or state.lifeform_id in excluded_ids:
            continue
        if state.is_demo and not actor.state.allow_demo_partners:
            continue
        if actor.state.is_demo and not state.allow_demo_partners:
            continue
        if not can_participate(candidate, now, topic_code):
            continue
        shared = tuple(sorted(set(actor.snapshot.topics) & set(candidate.snapshot.topics)))
        same_island = state.island_id == island_id
        related = (topic_code in candidate.snapshot.topics or
            bool(RELATED_TOPICS.get(topic_code, set()) & set(candidate.snapshot.topics)))
        if not same_island and (not state.allow_cross_island or not related):
            continue
        count = counts.get(state.lifeform_id, 0)
        # Recall priority: local pool, unseen partners, longest waiting time,
        # then a stable seeded tie breaker. Never cut by account ID alone.
        waiting_hours = max(0, (now - aware(state.waiting_since)).total_seconds() / 3600)
        priority = (not same_island, count > 0, -int(waiting_hours),
            sha256(f"{seed}:{state.lifeform_id}".encode()).hexdigest())
        breakdown = {"shared_topics": min(len(shared), 3) * .25,
            "same_island": .20 if same_island else 0,
            "pace": .15 if state.social_pace == actor.state.social_pace else .05,
            "waiting": min(waiting_hours / 24, 1) * .10,
            "repetition": -.15 * min(count, 3)}
        names = "、".join(TOPIC_LABELS[t] for t in shared if t in TOPIC_LABELS)
        reason = (f"你们都在关注「{names}」" if names else "你们正在探索同一个公开问题")
        reason += "；" + ("在同一座岛上相遇" if same_island else "对方允许跨岛探索，来到相关问题旁")
        if state.is_demo or actor.state.is_demo:
            reason += "（包含明确标记的演示伙伴）"
        recalled.append((priority, MatchCandidate(state.lifeform_id, state.user_id,
            candidate.snapshot.id, "same_island" if same_island else "related_topic",
            shared, count, state.is_demo, round(sum(breakdown.values()), 6), reason, breakdown)))
    return tuple(c for _, c in sorted(recalled, key=lambda row: row[0])[:limit])


def select_candidate(candidates: tuple[MatchCandidate, ...]) -> MatchCandidate | None:
    # Reserve opportunities for new partners; score within that recall group.
    if not candidates:
        return None
    group = min((c.recall_source != "same_island", c.encounter_count > 0) for c in candidates)
    eligible = [c for c in candidates if
        (c.recall_source != "same_island", c.encounter_count > 0) == group]
    return max(eligible, key=lambda c: c.score)  # stable recall order breaks ties


def demo_snapshot(snapshot: AgentContextSnapshot) -> AgentContextSnapshot:
    """Explicit demo fixtures carry public editorial topics, never user data."""
    digest = sha256(f"demo-social.v1:{snapshot.lifeform_id}:{snapshot.consent_version}".encode()).hexdigest()
    return snapshot.model_copy(update={"id": stable_id(digest), "content_hash": digest,
        "topics": tuple(TOPIC_LABELS), "topic_weights": {t: .5 for t in TOPIC_LABELS},
        "rule_version": "demo-social.v1"})
