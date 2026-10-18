ALTER TABLE memories ADD COLUMN topic_code VARCHAR(64) NOT NULL DEFAULT 'unclassified';

UPDATE memories m JOIN memory_evidence me ON me.memory_id = m.id
JOIN evidence e ON e.id = me.evidence_id
SET m.topic_code = e.topic_code WHERE m.topic_code = 'unclassified';

ALTER TABLE memory_revisions DROP CHECK chk_memory_revision_decision;
ALTER TABLE memory_revisions ADD CONSTRAINT chk_memory_revision_decision
CHECK (decision IN ('like_me', 'recent', 'opposes', 'wrong', 'edit', 'delete', 'permission'));
ALTER TABLE memory_revisions ADD COLUMN revision_payload JSON NULL;

-- Decay changes effective context even without a memory revision. Content
-- addressed IDs replace the coarse version tuple as the uniqueness boundary.
ALTER TABLE agent_context_snapshots ADD INDEX idx_agent_context_lifeform (lifeform_id);
ALTER TABLE agent_context_snapshots DROP INDEX uq_agent_context_version;
ALTER TABLE world_ticks ADD COLUMN context_snapshot_id CHAR(36) NULL;
ALTER TABLE world_ticks ADD CONSTRAINT fk_tick_context
FOREIGN KEY (context_snapshot_id) REFERENCES agent_context_snapshots(id);
