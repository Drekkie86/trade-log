-- =====================================================================
-- Christiania — migration 020
--
-- LOCAL_SURFACE empirical-null discovery statistics.
-- This layer is descriptive/discovery-only. It does not produce p-values,
-- FDR decisions, candidate creation, admission, or trading instructions.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE local_surface_null_v1_runs (
    id INTEGER PRIMARY KEY,
    null_family_id TEXT NOT NULL,
    null_model_version TEXT NOT NULL,
    stratification_version TEXT NOT NULL,
    dependence_spec_version TEXT NOT NULL,
    source_v2_model_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    fitted_at TEXT NOT NULL,
    source_first_session_date TEXT NOT NULL,
    source_last_session_date TEXT NOT NULL,
    source_max_observation_id INTEGER NOT NULL,
    observation_count INTEGER NOT NULL CHECK (observation_count >= 0),
    stratum_count INTEGER NOT NULL CHECK (stratum_count >= 0),
    discovery_window_count INTEGER NOT NULL CHECK (discovery_window_count > 0),
    model_state TEXT NOT NULL DEFAULT 'ESTIMATED_DISCOVERY_ONLY'
        CHECK (model_state = 'ESTIMATED_DISCOVERY_ONLY'),
    p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK (p_values_enabled = 0),
    fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK (fdr_enabled = 0),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK (decision_enabled = 0),
    UNIQUE (null_model_version, config_hash, source_max_observation_id)
);

CREATE TABLE local_surface_null_v1_strata (
    id INTEGER PRIMARY KEY,
    null_run_id INTEGER NOT NULL REFERENCES local_surface_null_v1_runs(id),
    stratum_key TEXT NOT NULL,
    right TEXT NOT NULL CHECK (right IN ('C','P')),
    dte_bucket TEXT NOT NULL,
    abs_delta_bucket TEXT NOT NULL,
    observation_count INTEGER NOT NULL CHECK (observation_count > 0),
    raw_mean REAL NOT NULL,
    raw_std REAL NOT NULL CHECK (raw_std >= 0),
    raw_median REAL NOT NULL,
    raw_mad REAL NOT NULL CHECK (raw_mad >= 0),
    raw_robust_scale REAL NOT NULL CHECK (raw_robust_scale >= 0),
    q01 REAL NOT NULL,
    q025 REAL NOT NULL,
    q05 REAL NOT NULL,
    q50 REAL NOT NULL,
    q95 REAL NOT NULL,
    q975 REAL NOT NULL,
    q99 REAL NOT NULL,
    parent_observation_count INTEGER NOT NULL CHECK (parent_observation_count > 0),
    parent_location REAL NOT NULL,
    parent_scale REAL NOT NULL CHECK (parent_scale >= 0),
    shrinkage_weight REAL NOT NULL CHECK (shrinkage_weight BETWEEN 0.0 AND 1.0),
    shrunk_location REAL NOT NULL,
    shrunk_scale REAL NOT NULL CHECK (shrunk_scale >= 0),
    UNIQUE (null_run_id, stratum_key)
);

CREATE TABLE local_surface_null_v1_membership (
    id INTEGER PRIMARY KEY,
    null_run_id INTEGER NOT NULL REFERENCES local_surface_null_v1_runs(id),
    v2_observation_id INTEGER NOT NULL REFERENCES local_surface_residual_v2_observations(id),
    stratum_id INTEGER NOT NULL REFERENCES local_surface_null_v1_strata(id),
    session_date TEXT NOT NULL,
    loo_residual REAL NOT NULL,
    centered_residual REAL NOT NULL,
    abs_centered_residual REAL NOT NULL CHECK (abs_centered_residual >= 0),
    UNIQUE (null_run_id, v2_observation_id)
);

CREATE TABLE local_surface_null_v1_dependence (
    id INTEGER PRIMARY KEY,
    null_run_id INTEGER NOT NULL REFERENCES local_surface_null_v1_runs(id),
    cluster_dimension TEXT NOT NULL CHECK (cluster_dimension IN (
        'CONTRACT_SESSION',
        'SURFACE_SESSION',
        'UNDERLYING_SESSION',
        'SESSION_DATE'
    )),
    raw_observation_count INTEGER NOT NULL CHECK (raw_observation_count > 0),
    cluster_count INTEGER NOT NULL CHECK (cluster_count > 0),
    repeated_cluster_count INTEGER NOT NULL CHECK (repeated_cluster_count >= 0),
    mean_cluster_size REAL NOT NULL CHECK (mean_cluster_size > 0),
    median_cluster_size REAL NOT NULL CHECK (median_cluster_size > 0),
    max_cluster_size INTEGER NOT NULL CHECK (max_cluster_size > 0),
    cluster_size_cv REAL NOT NULL CHECK (cluster_size_cv >= 0),
    icc_oneway REAL,
    design_effect_proxy REAL,
    effective_n_proxy REAL,
    estimator_state TEXT NOT NULL CHECK (estimator_state IN (
        'ESTIMATED_EXPLORATORY',
        'INSUFFICIENT_REPEATED_CLUSTERS'
    )),
    UNIQUE (null_run_id, cluster_dimension),
    CHECK (design_effect_proxy IS NULL OR design_effect_proxy >= 1.0),
    CHECK (effective_n_proxy IS NULL OR effective_n_proxy > 0)
);

CREATE INDEX idx_null_v1_membership_observation
ON local_surface_null_v1_membership(v2_observation_id);

CREATE INDEX idx_null_v1_membership_stratum
ON local_surface_null_v1_membership(stratum_id);

CREATE VIEW v_local_surface_null_v1_discovery_membership AS
SELECT
    nr.id AS null_run_id,
    nr.null_model_version,
    nr.model_state,
    nr.p_values_enabled,
    nr.fdr_enabled,
    nr.decision_enabled,
    m.v2_observation_id,
    v2.research_run_id,
    m.session_date,
    v2.observation_id,
    v2.underlying,
    v2.expiration,
    v2.strike,
    v2.right,
    v2.abs_delta,
    v2.dte,
    v2.spread_to_mid,
    v2.greek_age_seconds,
    v2.quote_greek_skew_seconds,
    v2.underlying_greek_skew_seconds,
    m.loo_residual,
    m.centered_residual,
    m.abs_centered_residual,
    s.stratum_key,
    s.observation_count AS stratum_observation_count,
    s.raw_median AS stratum_raw_median,
    s.raw_robust_scale AS stratum_raw_robust_scale,
    s.shrunk_location AS stratum_shrunk_location,
    s.shrunk_scale AS stratum_shrunk_scale,
    s.q025 AS stratum_q025,
    s.q975 AS stratum_q975
FROM local_surface_null_v1_membership AS m
JOIN local_surface_null_v1_runs AS nr ON nr.id = m.null_run_id
JOIN local_surface_null_v1_strata AS s ON s.id = m.stratum_id
JOIN v_local_surface_residual_v2_discovery_dataset AS v2
  ON v2.observation_id = m.v2_observation_id;

INSERT INTO schema_version (version, applied_at)
SELECT 20, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version = 20);
