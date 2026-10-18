CREATE TABLE IF NOT EXISTS matching_guard (
    id INT PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT IGNORE INTO matching_guard (id) VALUES (1);

CREATE TABLE IF NOT EXISTS exploration_states (
    lifeform_id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    island_id VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    allow_cross_island BOOLEAN NOT NULL DEFAULT FALSE,
    allow_demo_partners BOOLEAN NOT NULL DEFAULT FALSE,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    social_pace VARCHAR(32) NOT NULL,
    excluded_topics JSON NOT NULL,
    availability VARCHAR(16) NOT NULL DEFAULT 'available',
    waiting_since TIMESTAMP(6) NOT NULL,
    available_at TIMESTAMP(6) NOT NULL,
    latest_social_snapshot_id CHAR(36) NULL,
    UNIQUE KEY uq_exploration_user (user_id),
    KEY idx_exploration_recall (island_id, enabled, availability, available_at, waiting_since),
    CONSTRAINT fk_exploration_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_exploration_lifeform FOREIGN KEY (lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_exploration_availability CHECK (availability IN ('available', 'busy')),
    CONSTRAINT chk_exploration_pace CHECK (social_pace IN ('observe_first', 'shared_experiences', 'open_to_connection'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO exploration_states
(lifeform_id,user_id,island_id,enabled,allow_cross_island,allow_demo_partners,is_demo,
 social_pace,excluded_topics,availability,waiting_since,available_at)
SELECT l.id,l.user_id,COALESCE(l.current_island_id,'stability'),u.social_intent <> 'disabled',
 l.id IN ('lifeform-lumi','lifeform-ache'),l.id IN ('lifeform-lumi','lifeform-ache'),
 l.id IN ('lifeform-lumi','lifeform-ache'),
 CASE u.social_intent WHEN 'open' THEN 'open_to_connection' WHEN 'exploring' THEN 'shared_experiences' ELSE 'observe_first' END,
 JSON_ARRAY(),'available',l.created_at,l.created_at
FROM lifeforms l JOIN users u ON u.id=l.user_id;

CREATE TABLE IF NOT EXISTS pair_exclusions (
    lifeform_id CHAR(36) NOT NULL,
    target_lifeform_id CHAR(36) NOT NULL,
    decision VARCHAR(24) NOT NULL,
    until_at TIMESTAMP(6) NULL,
    PRIMARY KEY (lifeform_id,target_lifeform_id),
    KEY idx_pair_exclusions_reverse (target_lifeform_id,lifeform_id),
    CONSTRAINT fk_exclusion_actor FOREIGN KEY (lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT fk_exclusion_target FOREIGN KEY (target_lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_pair_exclusion CHECK (decision IN ('distance','end','block'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS private_encounter_decisions (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    encounter_id CHAR(36) NOT NULL,
    lifeform_id CHAR(36) NOT NULL,
    target_lifeform_id CHAR(36) NOT NULL,
    decision VARCHAR(24) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMP(6) NOT NULL,
    UNIQUE KEY uq_private_decision_key (user_id,idempotency_key),
    CONSTRAINT fk_private_decision_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_private_decision_encounter FOREIGN KEY (encounter_id) REFERENCES encounters(id),
    CONSTRAINT fk_private_decision_actor FOREIGN KEY (lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT fk_private_decision_target FOREIGN KEY (target_lifeform_id) REFERENCES lifeforms(id),
    CONSTRAINT chk_private_decision CHECK (decision IN ('observe_again','invite','distance','end','block'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE world_ticks ADD COLUMN match_payload JSON NULL;
ALTER TABLE encounters ADD COLUMN match_payload JSON NULL;
