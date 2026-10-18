-- M0 freezes the boundary between lifeform encounters and human connection.
-- Emotional progression is removed from persisted state; only operational
-- exploration status remains. Existing observations stay in event history.

ALTER TABLE relationships DROP CHECK chk_relationship_stage;

UPDATE relationships
SET current_stage = CASE
    WHEN current_stage = 'ended' THEN 'ended'
    ELSE 'active'
END;

ALTER TABLE relationships RENAME COLUMN current_stage TO status;

ALTER TABLE relationships
    ADD CONSTRAINT chk_relationship_status
    CHECK (status IN ('active', 'ended', 'blocked'));

ALTER TABLE relationship_events
    RENAME COLUMN previous_stage TO previous_status;

ALTER TABLE relationship_events
    RENAME COLUMN proposed_stage TO proposed_status;

ALTER TABLE relationship_events
    RENAME COLUMN committed_stage TO committed_status;

ALTER TABLE connections DROP CHECK chk_connection_status;

UPDATE connections
SET status = CASE
    WHEN status = 'pending' THEN 'waiting'
    WHEN status = 'mutual_accepted' THEN 'mutual_accepted'
    ELSE 'ended'
END;

ALTER TABLE connections
    ADD CONSTRAINT chk_connection_status
    CHECK (status IN ('waiting', 'mutual_accepted', 'active', 'ended'));

CREATE TABLE IF NOT EXISTS encounter_decisions (
    id CHAR(36) PRIMARY KEY,
    encounter_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    decision VARCHAR(24) NOT NULL,
    decided_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_encounter_decision_viewer (encounter_id, user_id),
    KEY idx_encounter_decisions_user (user_id, decided_at),
    CONSTRAINT fk_encounter_decision_encounter FOREIGN KEY (encounter_id) REFERENCES encounters(id),
    CONSTRAINT fk_encounter_decision_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_encounter_decision CHECK (
        decision IN ('observe_again', 'invite', 'distance', 'end', 'block')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS messages (
    id CHAR(36) PRIMARY KEY,
    channel_id CHAR(36) NOT NULL,
    sender_user_id CHAR(36) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'sent',
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    deleted_at TIMESTAMP(6) NULL,
    KEY idx_messages_channel (channel_id, created_at, id),
    CONSTRAINT fk_messages_channel FOREIGN KEY (channel_id) REFERENCES chat_channels(id),
    CONSTRAINT fk_messages_sender FOREIGN KEY (sender_user_id) REFERENCES users(id),
    CONSTRAINT chk_messages_status CHECK (status IN ('sent', 'deleted')),
    CONSTRAINT chk_deleted_message_erased CHECK (
        status <> 'deleted' OR (content = '' AND deleted_at IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
