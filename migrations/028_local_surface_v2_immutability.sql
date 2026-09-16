-- =====================================================================
-- Christiania — migration 028
--
-- Hostile-review remediation for DB-IMMUTABILITY-01/02.
-- These tables contain completed scientific/governance evidence with
-- insert-only production write paths. Once persisted, rows are append-only.
-- research_run_underlyings is deliberately excluded because it is mutable
-- lifecycle state by design.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- LOCAL_SURFACE_QUADRATIC_V2 residual observations.
CREATE TRIGGER trg_local_surface_v2_observation_no_update
BEFORE UPDATE
ON local_surface_residual_v2_observations
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_local_surface_v2_observation_no_delete
BEFORE DELETE
ON local_surface_residual_v2_observations
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Calibration-readiness computation runs.
CREATE TRIGGER trg_local_surface_calibration_readiness_no_update
BEFORE UPDATE
ON local_surface_calibration_readiness_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_local_surface_calibration_readiness_no_delete
BEFORE DELETE
ON local_surface_calibration_readiness_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Calibration-validity computation runs.
CREATE TRIGGER trg_local_surface_calibration_validity_no_update
BEFORE UPDATE
ON local_surface_calibration_validity_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_local_surface_calibration_validity_no_delete
BEFORE DELETE
ON local_surface_calibration_validity_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Empirical-null computation runs.
CREATE TRIGGER trg_local_surface_null_no_update
BEFORE UPDATE
ON local_surface_null_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_local_surface_null_no_delete
BEFORE DELETE
ON local_surface_null_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Residual-V2 fitted computation runs.
CREATE TRIGGER trg_local_surface_residual_v2_run_no_update
BEFORE UPDATE
ON local_surface_residual_v2_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_local_surface_residual_v2_run_no_delete
BEFORE DELETE
ON local_surface_residual_v2_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Robustness computation runs.
CREATE TRIGGER trg_local_surface_robustness_no_update
BEFORE UPDATE
ON local_surface_robustness_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_local_surface_robustness_no_delete
BEFORE DELETE
ON local_surface_robustness_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Prospective research-freeze governance records.
CREATE TRIGGER trg_prospective_research_freeze_no_update
BEFORE UPDATE
ON prospective_research_freeze_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_prospective_research_freeze_no_delete
BEFORE DELETE
ON prospective_research_freeze_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- Provider-model timing reconstruction runs.
CREATE TRIGGER trg_provider_model_timing_reconstruction_no_update
BEFORE UPDATE
ON provider_model_timing_reconstruction_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_provider_model_timing_reconstruction_no_delete
BEFORE DELETE
ON provider_model_timing_reconstruction_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

-- ThetaData timestamp-semantics validation runs.
CREATE TRIGGER trg_thetadata_timestamp_semantics_no_update
BEFORE UPDATE
ON thetadata_timestamp_semantics_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence is immutable.');
END;

CREATE TRIGGER trg_thetadata_timestamp_semantics_no_delete
BEFORE DELETE
ON thetadata_timestamp_semantics_v1_runs
BEGIN
    SELECT RAISE(ABORT, 'Frozen research/governance evidence cannot be deleted.');
END;

INSERT INTO schema_version (version, applied_at)
SELECT 28, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 28
);
