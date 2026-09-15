-- 未见 MVP initial MySQL 8 schema.
-- Application code encrypts OAuth-derived raw responses before writing ciphertext.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id CHAR(36) PRIMARY KEY,
    external_zhihu_uid VARCHAR(64) NULL,
    display_name VARCHAR(120) NOT NULL,
    consent_version BIGINT UNSIGNED NOT NULL DEFAULT 1,
    social_intent VARCHAR(24) NOT NULL DEFAULT 'disabled',
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_users_zhihu_uid (external_zhihu_uid),
    CONSTRAINT chk_users_consent_version CHECK (consent_version >= 1),
    CONSTRAINT chk_users_social_intent CHECK (social_intent IN ('disabled', 'exploring', 'open'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_consents (
    user_id CHAR(36) NOT NULL,
    scope VARCHAR(48) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    version BIGINT UNSIGNED NOT NULL,
    changed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (user_id, scope),
    CONSTRAINT fk_user_consents_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_user_consents_scope CHECK (scope IN ('zhihu_import', 'memory_inference', 'social_recommendation', 'sensitive_memory')),
    CONSTRAINT chk_user_consents_version CHECK (version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS oauth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    provider VARCHAR(24) NOT NULL,
    access_token_ciphertext LONGBLOB NOT NULL,
    refresh_token_ciphertext LONGBLOB NULL,
    expires_at TIMESTAMP(6) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_oauth_credentials_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_oauth_provider CHECK (provider IN ('zhihu')),
    CONSTRAINT chk_oauth_status CHECK (status IN ('active', 'expired', 'revoked', 'deleted'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS import_jobs (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    consent_version BIGINT UNSIGNED NOT NULL,
    call_budget TINYINT UNSIGNED NOT NULL,
    calls_used TINYINT UNSIGNED NOT NULL DEFAULT 0,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    stop_reason VARCHAR(120) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    UNIQUE KEY uq_import_job_idempotency (user_id, idempotency_key),
    CONSTRAINT fk_import_jobs_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_import_job_budget CHECK (call_budget BETWEEN 1 AND 6),
    CONSTRAINT chk_import_job_usage CHECK (calls_used <= call_budget),
    CONSTRAINT chk_import_job_status CHECK (status IN ('queued', 'running', 'partial', 'completed', 'quota_blocked', 'failed', 'cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS lifeforms (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    name VARCHAR(80) NOT NULL,
    appearance JSON NOT NULL,
    exploration_tendency VARCHAR(32) NOT NULL,
    current_island_id VARCHAR(64) NULL,
    current_focus VARCHAR(255) NOT NULL,
    status VARCHAR(120) NOT NULL,
    version BIGINT UNSIGNED NOT NULL DEFAULT 1,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_lifeforms_user (user_id),
    KEY idx_lifeforms_island (current_island_id),
    CONSTRAINT fk_lifeforms_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_lifeforms_version CHECK (version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS platform_import_snapshots (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    import_job_id CHAR(36) NOT NULL,
    endpoint VARCHAR(160) NOT NULL,
    capability_group VARCHAR(40) NOT NULL,
    call_sequence SMALLINT UNSIGNED NOT NULL,
    consent_version BIGINT UNSIGNED NOT NULL,
    schema_version VARCHAR(32) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    raw_response_ciphertext LONGBLOB NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    imported_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    source_content_at TIMESTAMP(6) NULL,
    UNIQUE KEY uq_import_snapshot_hash (user_id, endpoint, content_hash),
    KEY idx_import_snapshot_user_status (user_id, status, imported_at),
    CONSTRAINT fk_import_snapshot_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_import_snapshot_job FOREIGN KEY (import_job_id) REFERENCES import_jobs(id),
    CONSTRAINT chk_import_snapshot_status CHECK (status IN ('active', 'revoked', 'deleted')),
    CONSTRAINT chk_deleted_snapshot_erased CHECK (status <> 'deleted' OR raw_response_ciphertext IS NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS evidence (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    snapshot_id CHAR(36) NULL,
    source_type VARCHAR(40) NOT NULL,
    source_ref VARCHAR(500) NULL,
    topic_code VARCHAR(64) NOT NULL,
    authored_by_user BOOLEAN NOT NULL DEFAULT FALSE,
    self_reference BOOLEAN NOT NULL DEFAULT FALSE,
    assertion_mode VARCHAR(24) NULL,
    polarity VARCHAR(24) NULL,
    confidence DECIMAL(5,4) NOT NULL,
    consent_version BIGINT UNSIGNED NOT NULL,
    is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
    allow_social_recommendation BOOLEAN NOT NULL DEFAULT FALSE,
    source_occurred_at TIMESTAMP(6) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_evidence_user_topic (user_id, topic_code, created_at),
    KEY idx_evidence_snapshot (snapshot_id),
    CONSTRAINT fk_evidence_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_evidence_snapshot FOREIGN KEY (snapshot_id) REFERENCES platform_import_snapshots(id),
    CONSTRAINT chk_evidence_confidence CHECK (confidence >= 0 AND confidence <= 1),
    -- 词表与 app.domain.evidence_policy.EvidenceSource 一一对应。
    -- 前四项为平台一次性导入，后四项为应用内持续行为。
    -- 这道约束只防词表漂移（拼错的来源会被数据库拒绝）；
    -- 「立场记忆只能用白名单来源」是跨 memories/memory_evidence/evidence
    -- 三张表的规则，无法用 CHECK 表达，由应用层 validate_memory_evidence 强制。
    CONSTRAINT chk_evidence_source_type CHECK (source_type IN (
        'authored_content',
        'favlist_naming',
        'favorite_item',
        'followee_headline',
        'in_app_input',
        'calibration',
        'returned_question_reply',
        'in_app_browse'
    ))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS memories (
    id CHAR(36) PRIMARY KEY,
    lifeform_id CHAR(36) NOT NULL,
    memory_type VARCHAR(24) NOT NULL,
    statement TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'candidate',
    confidence DECIMAL(5,4) NOT NULL,
    importance DECIMAL(5,4) NOT NULL,
    score DECIMAL(12,6) NOT NULL DEFAULT 0,
    score_updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    allow_social_recommendation BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NULL,
    KEY idx_memories_lifeform_status (lifeform_id, status, memory_type),
    CONSTRAINT fk_memories_lifeform FOREIGN KEY (lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_memories_type CHECK (memory_type IN ('topic', 'stance', 'preference', 'boundary', 'social_intent')),
    CONSTRAINT chk_memories_status CHECK (status IN ('candidate', 'confirmed', 'rejected', 'superseded', 'deleted')),
    CONSTRAINT chk_memories_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_memories_importance CHECK (importance >= 0 AND importance <= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id CHAR(36) NOT NULL,
    evidence_id CHAR(36) NOT NULL,
    contribution DECIMAL(8,6) NOT NULL,
    PRIMARY KEY (memory_id, evidence_id),
    CONSTRAINT fk_memory_evidence_memory FOREIGN KEY (memory_id) REFERENCES memories(id),
    CONSTRAINT fk_memory_evidence_evidence FOREIGN KEY (evidence_id) REFERENCES evidence(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS memory_revisions (
    id CHAR(36) PRIMARY KEY,
    memory_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    decision VARCHAR(24) NOT NULL,
    previous_status VARCHAR(16) NOT NULL,
    next_status VARCHAR(16) NOT NULL,
    allow_social_recommendation BOOLEAN NOT NULL,
    occurred_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_memory_revisions_memory (memory_id, occurred_at),
    CONSTRAINT fk_memory_revisions_memory FOREIGN KEY (memory_id) REFERENCES memories(id),
    CONSTRAINT fk_memory_revisions_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_memory_revision_decision CHECK (decision IN ('like_me', 'recent', 'opposes', 'wrong'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS islands (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    question_title VARCHAR(255) NOT NULL,
    question_url VARCHAR(500) NOT NULL,
    topic_code VARCHAR(64) NOT NULL,
    active_fixture_version VARCHAR(32) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS island_fixtures (
    id CHAR(36) PRIMARY KEY,
    island_id VARCHAR(64) NOT NULL,
    fixture_version VARCHAR(32) NOT NULL,
    source_payload JSON NOT NULL,
    content_hash CHAR(64) NOT NULL,
    fetched_at TIMESTAMP(6) NOT NULL,
    safety_status VARCHAR(16) NOT NULL,
    UNIQUE KEY uq_island_fixture_version (island_id, fixture_version),
    CONSTRAINT fk_island_fixture_island FOREIGN KEY (island_id) REFERENCES islands(id),
    CONSTRAINT chk_island_fixture_safety CHECK (safety_status IN ('pending', 'accepted', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS world_ticks (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    lifeform_id CHAR(36) NOT NULL,
    trigger_type VARCHAR(16) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    fixture_version VARCHAR(32) NULL,
    selected_island_id VARCHAR(64) NULL,
    decision_reason VARCHAR(500) NULL,
    source_mode VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    started_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    UNIQUE KEY uq_world_tick_idempotency (user_id, idempotency_key),
    KEY idx_world_ticks_status (status, started_at),
    CONSTRAINT fk_world_ticks_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_world_ticks_lifeform FOREIGN KEY (lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_world_ticks_trigger CHECK (trigger_type IN ('cron', 'manual', 'fixture')),
    CONSTRAINT chk_world_ticks_source CHECK (source_mode IN ('precomputed', 'live', 'fallback')),
    CONSTRAINT chk_world_ticks_status CHECK (status IN ('queued', 'running', 'completed', 'failed', 'discarded'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS encounters (
    id CHAR(36) PRIMARY KEY,
    world_tick_id CHAR(36) NOT NULL,
    island_id VARCHAR(64) NOT NULL,
    lifeform_a_id CHAR(36) NOT NULL,
    lifeform_b_id CHAR(36) NOT NULL,
    consent_version_a BIGINT UNSIGNED NOT NULL,
    consent_version_b BIGINT UNSIGNED NOT NULL,
    fixture_version VARCHAR(32) NOT NULL,
    status VARCHAR(24) NOT NULL,
    outcome_summary TEXT NULL,
    trace_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    KEY idx_encounters_lifeform_a (lifeform_a_id, status),
    KEY idx_encounters_lifeform_b (lifeform_b_id, status),
    CONSTRAINT fk_encounters_tick FOREIGN KEY (world_tick_id) REFERENCES world_ticks(id),
    CONSTRAINT fk_encounters_island FOREIGN KEY (island_id) REFERENCES islands(id),
    CONSTRAINT fk_encounters_lifeform_a FOREIGN KEY (lifeform_a_id) REFERENCES lifeforms(id),
    CONSTRAINT fk_encounters_lifeform_b FOREIGN KEY (lifeform_b_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_encounters_distinct_lifeforms CHECK (lifeform_a_id <> lifeform_b_id),
    CONSTRAINT chk_encounters_status CHECK (status IN ('queued', 'running', 'completed', 'invalid', 'left', 'failed', 'discarded'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS encounter_turns (
    id CHAR(36) PRIMARY KEY,
    encounter_id CHAR(36) NOT NULL,
    turn_number TINYINT UNSIGNED NOT NULL,
    actor_lifeform_id CHAR(36) NOT NULL,
    action VARCHAR(24) NOT NULL,
    public_utterance TEXT NULL,
    proposal_payload JSON NOT NULL,
    validation_status VARCHAR(16) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_encounter_turn (encounter_id, turn_number),
    CONSTRAINT fk_encounter_turn_encounter FOREIGN KEY (encounter_id) REFERENCES encounters(id),
    CONSTRAINT fk_encounter_turn_actor FOREIGN KEY (actor_lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_encounter_turn_number CHECK (turn_number BETWEEN 1 AND 5),
    CONSTRAINT chk_encounter_action CHECK (action IN ('approach', 'observe', 'respond', 'cooperate', 'avoid', 'leave')),
    CONSTRAINT chk_encounter_turn_validation CHECK (validation_status IN ('pending', 'accepted', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS relationships (
    id CHAR(36) PRIMARY KEY,
    lifeform_a_id CHAR(36) NOT NULL,
    lifeform_b_id CHAR(36) NOT NULL,
    current_stage VARCHAR(32) NOT NULL,
    last_island_id VARCHAR(64) NOT NULL,
    headline VARCHAR(255) NOT NULL,
    shared_experiences JSON NOT NULL,
    source_mode VARCHAR(16) NOT NULL,
    projection_version BIGINT UNSIGNED NOT NULL DEFAULT 0,
    ended_at TIMESTAMP(6) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_relationship_pair (lifeform_a_id, lifeform_b_id),
    CONSTRAINT fk_relationship_lifeform_a FOREIGN KEY (lifeform_a_id) REFERENCES lifeforms(id),
    CONSTRAINT fk_relationship_lifeform_b FOREIGN KEY (lifeform_b_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_relationship_distinct_lifeforms CHECK (lifeform_a_id <> lifeform_b_id),
    CONSTRAINT chk_relationship_pair_order CHECK (lifeform_a_id < lifeform_b_id),
    CONSTRAINT chk_relationship_source CHECK (source_mode IN ('precomputed', 'live', 'fallback')),
    CONSTRAINT chk_relationship_stage CHECK (current_stage IN ('unmet', 'noticed', 'shared_experience', 'cared', 'connection_candidate', 'stalled', 'distant', 'ended'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS relationship_events (
    id CHAR(36) PRIMARY KEY,
    relationship_id CHAR(36) NOT NULL,
    event_type VARCHAR(48) NOT NULL,
    previous_stage VARCHAR(32) NOT NULL,
    proposed_stage VARCHAR(32) NULL,
    committed_stage VARCHAR(32) NOT NULL,
    encounter_id CHAR(36) NULL,
    actor_user_id CHAR(36) NULL,
    dimensions_delta JSON NOT NULL,
    evidence_refs JSON NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    occurred_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_relationship_events_stream (relationship_id, occurred_at, id),
    CONSTRAINT fk_relationship_event_relationship FOREIGN KEY (relationship_id) REFERENCES relationships(id),
    CONSTRAINT fk_relationship_event_encounter FOREIGN KEY (encounter_id) REFERENCES encounters(id),
    CONSTRAINT fk_relationship_event_actor FOREIGN KEY (actor_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS connections (
    id CHAR(36) PRIMARY KEY,
    relationship_id CHAR(36) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    recommendation_reason TEXT NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_connection_relationship (relationship_id),
    CONSTRAINT fk_connection_relationship FOREIGN KEY (relationship_id) REFERENCES relationships(id),
    CONSTRAINT chk_connection_status CHECK (status IN ('pending', 'mutual_accepted', 'declined', 'expired', 'revoked'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS connection_decisions (
    connection_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    decision VARCHAR(16) NOT NULL,
    decision_version BIGINT UNSIGNED NOT NULL DEFAULT 1,
    decided_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (connection_id, user_id),
    CONSTRAINT fk_connection_decision_connection FOREIGN KEY (connection_id) REFERENCES connections(id),
    CONSTRAINT fk_connection_decision_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_connection_decision CHECK (decision IN ('accepted', 'declined', 'deferred', 'revoked'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_channels (
    id CHAR(36) PRIMARY KEY,
    connection_id CHAR(36) NOT NULL,
    opened_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_chat_channel_connection (connection_id),
    CONSTRAINT fk_chat_channel_connection FOREIGN KEY (connection_id) REFERENCES connections(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS icebreakers (
    id CHAR(36) PRIMARY KEY,
    connection_id CHAR(36) NOT NULL,
    source_encounter_id CHAR(36) NOT NULL,
    content TEXT NOT NULL,
    evidence_refs JSON NOT NULL,
    validation_status VARCHAR(16) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_icebreakers_connection (connection_id, created_at),
    CONSTRAINT fk_icebreaker_connection FOREIGN KEY (connection_id) REFERENCES connections(id),
    CONSTRAINT fk_icebreaker_encounter FOREIGN KEY (source_encounter_id) REFERENCES encounters(id),
    CONSTRAINT chk_icebreaker_validation CHECK (validation_status IN ('pending', 'accepted', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS agent_runs (
    id CHAR(36) PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    run_type VARCHAR(40) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    model_name VARCHAR(120) NULL,
    prompt_template_version VARCHAR(32) NOT NULL,
    prompt_hash CHAR(64) NOT NULL,
    input_evidence_ids JSON NOT NULL,
    consent_version BIGINT UNSIGNED NULL,
    schema_version VARCHAR(32) NOT NULL,
    output_hash CHAR(64) NULL,
    validation_status VARCHAR(16) NOT NULL,
    commit_status VARCHAR(16) NOT NULL,
    latency_ms INT UNSIGNED NULL,
    input_tokens INT UNSIGNED NULL,
    output_tokens INT UNSIGNED NULL,
    started_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    KEY idx_agent_runs_trace (trace_id),
    KEY idx_agent_runs_subject (subject_id, started_at),
    CONSTRAINT chk_agent_run_validation CHECK (validation_status IN ('pending', 'accepted', 'rejected', 'failed')),
    CONSTRAINT chk_agent_run_commit CHECK (commit_status IN ('pending', 'committed', 'discarded', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS audit_events (
    id CHAR(36) PRIMARY KEY,
    event_type VARCHAR(80) NOT NULL,
    actor_id CHAR(36) NULL,
    subject_id CHAR(36) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    redacted_details JSON NOT NULL,
    occurred_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY idx_audit_subject (subject_id, occurred_at),
    KEY idx_audit_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
