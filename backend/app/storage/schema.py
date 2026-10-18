from __future__ import annotations

# Runtime projection used by the persistence adapter and its tests. The complete
# migration contract remains migrations/0001_core.sql; Alembic autogeneration is
# intentionally disabled so this focused projection cannot propose table drops.

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


metadata = MetaData()

islands = Table(
    "islands",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("question_title", String(255), nullable=False),
    Column("question_url", String(500), nullable=False),
    Column("topic_code", String(64), nullable=False),
    Column("active_fixture_version", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

island_fixtures = Table(
    "island_fixtures",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("island_id", String(64), ForeignKey("islands.id"), nullable=False),
    Column("fixture_version", String(32), nullable=False),
    Column("source_payload", JSON, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("safety_status", String(16), nullable=False),
    UniqueConstraint("island_id", "fixture_version", name="uq_island_fixture_version"),
)

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("external_zhihu_uid", String(64), nullable=True, unique=True),
    Column("display_name", String(120), nullable=False),
    Column("consent_version", Integer, nullable=False),
    Column("social_intent", String(24), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

lifeforms = Table(
    "lifeforms",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, unique=True),
    Column("name", String(80), nullable=False),
    Column("appearance", JSON, nullable=False),
    Column("exploration_tendency", String(32), nullable=False),
    Column("current_island_id", String(64), nullable=True),
    Column("current_focus", String(255), nullable=False),
    Column("status", String(120), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

evidence = Table(
    "evidence",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("ingestion_key", String(128), nullable=False),
    Column("user_id", String(36), nullable=False),
    Column("snapshot_id", String(36), nullable=True),
    Column("source_type", String(40), nullable=False),
    Column("source_ref", String(500), nullable=True),
    Column("content_text", Text, nullable=False),
    Column("topic_code", String(64), nullable=False),
    Column("authored_by_user", Boolean, nullable=False),
    Column("self_reference", Boolean, nullable=False),
    Column("assertion_mode", String(24), nullable=True),
    Column("polarity", String(24), nullable=True),
    Column("confidence", Float, nullable=False),
    Column("consent_version", Integer, nullable=False),
    Column("is_sensitive", Boolean, nullable=False),
    Column("allow_social_recommendation", Boolean, nullable=False),
    Column("source_occurred_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("user_id", "ingestion_key", name="uq_evidence_ingestion"),
)

memories = Table(
    "memories",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("lifeform_id", String(36), nullable=False),
    Column("memory_type", String(24), nullable=False),
    Column("statement", Text, nullable=False),
    Column("status", String(16), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("importance", Float, nullable=False),
    Column("score", Float, nullable=False),
    Column("score_updated_at", DateTime(timezone=True), nullable=False),
    Column("allow_social_recommendation", Boolean, nullable=False),
    Column("version", Integer, nullable=False),
    Column("supersedes_memory_id", String(36), nullable=True),
    Column("topic_code", String(64), nullable=False, server_default="unclassified"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
)

memory_evidence = Table(
    "memory_evidence",
    metadata,
    Column("memory_id", String(36), primary_key=True),
    Column("evidence_id", String(36), primary_key=True),
    Column("contribution", Float, nullable=False),
)

memory_revisions = Table(
    "memory_revisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("memory_id", String(36), nullable=False),
    Column("user_id", String(36), nullable=False),
    Column("decision", String(24), nullable=False),
    Column("previous_status", String(16), nullable=False),
    Column("next_status", String(16), nullable=False),
    Column("allow_social_recommendation", Boolean, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("revision_payload", JSON, nullable=True),
)

agent_context_snapshots = Table(
    "agent_context_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("lifeform_id", String(36), ForeignKey("lifeforms.id"), nullable=False),
    Column("purpose", String(32), nullable=False),
    Column("consent_version", Integer, nullable=False),
    Column("understanding_version", Integer, nullable=False),
    Column("understanding_ids", JSON, nullable=False),
    Column("context_payload", JSON, nullable=False),
    Column("evidence_cutoff_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

world_ticks = Table(
    "world_ticks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False),
    Column("lifeform_id", String(36), nullable=False),
    Column("trigger_type", String(16), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("fixture_version", String(32), nullable=True),
    Column("context_snapshot_id", String(36), nullable=True),
    Column("match_payload", JSON, nullable=True),
    Column("selected_island_id", String(64), nullable=True),
    Column("decision_reason", String(500), nullable=True),
    Column("source_mode", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("trace_id", String(64), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("user_id", "idempotency_key", name="uq_world_tick_idempotency"),
)

encounters = Table(
    "encounters",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("world_tick_id", String(36), ForeignKey("world_ticks.id"), nullable=False),
    Column("island_id", String(64), ForeignKey("islands.id"), nullable=False),
    Column("lifeform_a_id", String(36), ForeignKey("lifeforms.id"), nullable=False),
    Column("lifeform_b_id", String(36), ForeignKey("lifeforms.id"), nullable=False),
    Column("consent_version_a", Integer, nullable=False),
    Column("consent_version_b", Integer, nullable=False),
    Column("fixture_version", String(32), nullable=False),
    Column("status", String(24), nullable=False),
    Column("outcome_summary", Text, nullable=True),
    Column("match_payload", JSON, nullable=True),
    Column("trace_id", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

encounter_turns = Table(
    "encounter_turns",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("encounter_id", String(36), ForeignKey("encounters.id"), nullable=False),
    Column("turn_number", Integer, nullable=False),
    Column("actor_lifeform_id", String(36), ForeignKey("lifeforms.id"), nullable=False),
    Column("action", String(24), nullable=False),
    Column("public_utterance", Text, nullable=True),
    Column("proposal_payload", JSON, nullable=False),
    Column("validation_status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("encounter_id", "turn_number", name="uq_encounter_turn"),
)

relationships = Table(
    "relationships",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("lifeform_a_id", String(36), nullable=False),
    Column("lifeform_b_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("last_island_id", String(64), nullable=False),
    Column("headline", String(255), nullable=False),
    Column("shared_experiences", JSON, nullable=False),
    Column("encounter_count", Integer, nullable=False),
    Column("source_mode", String(16), nullable=False),
    Column("projection_version", Integer, nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("lifeform_a_id", "lifeform_b_id", name="uq_relationship_pair"),
)

relationship_events = Table(
    "relationship_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("relationship_id", String(36), ForeignKey("relationships.id"), nullable=False),
    Column("event_type", String(48), nullable=False),
    Column("previous_status", String(32), nullable=False),
    Column("proposed_status", String(32), nullable=True),
    Column("committed_status", String(32), nullable=False),
    Column("encounter_id", String(36), ForeignKey("encounters.id"), nullable=True),
    Column("actor_user_id", String(36), ForeignKey("users.id"), nullable=True),
    Column("dimensions_delta", JSON, nullable=False),
    Column("evidence_refs", JSON, nullable=False),
    Column("trace_id", String(64), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

encounter_decisions = Table(
    "encounter_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("encounter_id", String(36), ForeignKey("encounters.id"), nullable=False),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("decision", String(24), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("encounter_id", "user_id", name="uq_encounter_decision_viewer"),
)

connections = Table(
    "connections",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("relationship_id", String(36), ForeignKey("relationships.id"), nullable=False),
    Column("status", String(24), nullable=False),
    Column("recommendation_reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("relationship_id", name="uq_connection_relationship"),
)

chat_channels = Table(
    "chat_channels",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("connection_id", String(36), ForeignKey("connections.id"), nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("connection_id", name="uq_chat_channel_connection"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("channel_id", String(36), ForeignKey("chat_channels.id"), nullable=False),
    Column("sender_user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("content", Text, nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("event_type", String(80), nullable=False),
    Column("actor_id", String(36), nullable=True),
    Column("subject_id", String(36), nullable=False),
    Column("trace_id", String(64), nullable=False),
    Column("redacted_details", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)


# --- 平台导入相关（PRD 8.12）---
#
# 与本文件其他表一致，这里只投影运行时查询需要的结构与唯一约束；
# CHECK 约束以 migrations/0001_core.sql 为准，不在此重复声明，
# 避免同一约束出现两份定义后各自漂移。

user_consents = Table(
    "user_consents",
    metadata,
    # 复合主键 (user_id, scope)：逐项授权，每项独立记录版本与变更时间。
    Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
    Column("scope", String(48), primary_key=True),
    Column("enabled", Boolean, nullable=False),
    Column("version", Integer, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
)

oauth_credentials = Table(
    "oauth_credentials",
    metadata,
    # 主键是 user_id 而非独立 id：一个用户对一个 provider 只保留一份有效凭证。
    Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
    Column("provider", String(24), nullable=False),
    # AES-GCM 密文，AAD 绑定 user_id 与用途，详见 app/core/crypto.py。
    Column("access_token_ciphertext", LargeBinary, nullable=False),
    # 平台当前不提供 refresh token（oauth.md 待确认项 3），列先留空。
    Column("refresh_token_ciphertext", LargeBinary, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("status", String(16), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

import_jobs = Table(
    "import_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("consent_version", Integer, nullable=False),
    # 数据库 CHECK 限定 1..6，与 PRD 8.4 的单次导入预算一致。
    Column("call_budget", Integer, nullable=False),
    Column("calls_used", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("stop_reason", String(120), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    # 重复提交同一导入请求必须复用同一 job，而不是再花一遍额度。
    UniqueConstraint("user_id", "idempotency_key", name="uq_import_job_idempotency"),
)

platform_import_snapshots = Table(
    "platform_import_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("import_job_id", String(36), ForeignKey("import_jobs.id"), nullable=False),
    Column("endpoint", String(160), nullable=False),
    # 额度能力组（user_data / creator / question_answers ...），用于额度归账。
    Column("capability_group", String(40), nullable=False),
    Column("call_sequence", Integer, nullable=False),
    # 记录当时的授权版本：撤销授权后旧快照不再参与新决策，但审计仍可回溯。
    Column("consent_version", Integer, nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("content_hash", String(64), nullable=False),
    # 可为 NULL：status='deleted' 时必须清空（chk_deleted_snapshot_erased）。
    Column("raw_response_ciphertext", LargeBinary, nullable=True),
    Column("status", String(16), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    # 平台内容自身的时间（如收藏时间），与导入时刻区分开。
    Column("source_content_at", DateTime(timezone=True), nullable=True),
    # 同一用户、同一接口、同一内容只存一份，重新导入不产生重复快照。
    UniqueConstraint("user_id", "endpoint", "content_hash", name="uq_import_snapshot_hash"),
)
