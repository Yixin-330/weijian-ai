-- Keep observation counts distinct from projection versions. Projection
-- versions may also advance for user decisions and must not be shown as the
-- number of encounters that actually occurred.

ALTER TABLE relationships
    ADD COLUMN encounter_count BIGINT UNSIGNED NOT NULL DEFAULT 0
    AFTER shared_experiences;

UPDATE relationships AS relationship_row
LEFT JOIN (
    SELECT
        lifeform_a_id,
        lifeform_b_id,
        COUNT(*) AS completed_count
    FROM encounters
    WHERE status IN ('completed', 'left')
    GROUP BY lifeform_a_id, lifeform_b_id
) AS encounter_totals
ON encounter_totals.lifeform_a_id = relationship_row.lifeform_a_id
AND encounter_totals.lifeform_b_id = relationship_row.lifeform_b_id
SET relationship_row.encounter_count = CASE
    WHEN COALESCE(encounter_totals.completed_count, 0) = 0
         AND relationship_row.source_mode = 'precomputed'
        THEN 1
    ELSE COALESCE(encounter_totals.completed_count, 0)
END;
