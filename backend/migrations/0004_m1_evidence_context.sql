-- M1 separates immutable growth evidence, versioned understandings, and the
-- read-only context consumed by one concrete lifeform decision.

ALTER TABLE evidence
    ADD COLUMN ingestion_key VARCHAR(128) NULL AFTER id;

UPDATE evidence
SET ingestion_key = CONCAT('legacy:', id)
WHERE ingestion_key IS NULL;

ALTER TABLE evidence
    MODIFY COLUMN ingestion_key VARCHAR(128) NOT NULL;

ALTER TABLE evidence
    ADD COLUMN content_text TEXT NULL AFTER source_ref;

UPDATE evidence
SET content_text = CONCAT('历史证据：', topic_code)
WHERE content_text IS NULL;

ALTER TABLE evidence
    MODIFY COLUMN content_text TEXT NOT NULL;

ALTER TABLE evidence
    ADD CONSTRAINT uq_evidence_ingestion UNIQUE (user_id, ingestion_key);

ALTER TABLE memories
    ADD COLUMN version BIGINT UNSIGNED NOT NULL DEFAULT 1 AFTER allow_social_recommendation;

ALTER TABLE memories
    ADD COLUMN supersedes_memory_id CHAR(36) NULL AFTER version;

ALTER TABLE memories
    ADD CONSTRAINT fk_memories_supersedes
    FOREIGN KEY (supersedes_memory_id) REFERENCES memories(id);

CREATE TABLE IF NOT EXISTS agent_context_snapshots (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    lifeform_id CHAR(36) NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    consent_version BIGINT UNSIGNED NOT NULL,
    understanding_version BIGINT UNSIGNED NOT NULL,
    understanding_ids JSON NOT NULL,
    context_payload JSON NOT NULL,
    evidence_cutoff_at TIMESTAMP(6) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_agent_context_version (
        lifeform_id,
        purpose,
        consent_version,
        understanding_version
    ),
    KEY idx_agent_context_user_created (user_id, created_at),
    CONSTRAINT fk_agent_context_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_agent_context_lifeform FOREIGN KEY (lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_agent_context_purpose CHECK (
        purpose IN ('exploration', 'social_recommendation')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
