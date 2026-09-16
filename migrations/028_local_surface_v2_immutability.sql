-- =====================================================================
-- Christiania — migration 028
--
-- Hostile-review remediation: local_surface_residual_v2_observations is
-- frozen scientific evidence and must be append-only once persisted.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE TRIGGER trg_local_surface_v2_observation_no_update
BEFORE UPDATE
ON local_surface_residual_v2_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Local surface residual V2 observations are immutable scientific evidence.'
    );
END;

CREATE TRIGGER trg_local_surface_v2_observation_no_delete
BEFORE DELETE
ON local_surface_residual_v2_observations
BEGIN
    SELECT RAISE(
        ABORT,
        'Local surface residual V2 observations cannot be deleted.'
    );
END;

INSERT INTO schema_version (version, applied_at)
SELECT 28, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 28
);
