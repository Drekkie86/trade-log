-- =====================================================================
-- Christiania — migration 025
--
-- Recovery provenance visibility for prospective observational analysis.
-- No model, threshold, p-value, FDR, admission, candidate, or trading change.
-- =====================================================================
PRAGMA foreign_keys = ON;

ALTER TABLE research_run_underlyings
ADD COLUMN recovery_error_type TEXT;

ALTER TABLE research_run_underlyings
ADD COLUMN recovery_error_message TEXT;

CREATE VIEW v_local_surface_v2_prospective_partition_v2 AS
SELECT
    p.*,
    ru.status AS underlying_collection_status,
    COALESCE(ru.retry_count, 0) AS recovery_attempt_count,
    CASE
        WHEN COALESCE(ru.retry_count, 0) > 0
         AND ru.status = 'SUCCESS'
        THEN 1
        ELSE 0
    END AS was_recovered,
    CASE
        WHEN ru.run_id IS NULL THEN 'UNDERLYING_PROVENANCE_MISSING'
        WHEN COALESCE(ru.retry_count, 0) > 0
         AND ru.status = 'SUCCESS'
            THEN 'RECOVERED_AFTER_TRANSIENT_PROVIDER_FAILURE'
        WHEN COALESCE(ru.retry_count, 0) = 0
            THEN 'CLEAN_NO_RECOVERY'
        ELSE 'RETRY_ATTEMPTED_NOT_RECOVERED'
    END AS recovery_provenance_state,
    ru.recovery_error_type,
    ru.recovery_error_message
FROM v_local_surface_v2_prospective_partition_v1 AS p
LEFT JOIN research_run_underlyings AS ru
  ON ru.run_id = p.research_run_id
 AND ru.underlying = p.underlying;

INSERT INTO schema_version (version, applied_at)
SELECT 25, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version = 25);
