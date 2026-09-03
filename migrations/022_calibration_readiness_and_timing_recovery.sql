PRAGMA foreign_keys=ON;

CREATE TABLE provider_model_timing_reconstruction_v1_runs (
    id INTEGER PRIMARY KEY,
    method_version TEXT NOT NULL,
    fitted_at TEXT NOT NULL,
    eligible_count INTEGER NOT NULL CHECK(eligible_count>=0),
    reconstructed_count INTEGER NOT NULL CHECK(reconstructed_count>=0),
    partial_count INTEGER NOT NULL CHECK(partial_count>=0),
    unavailable_count INTEGER NOT NULL CHECK(unavailable_count>=0),
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE provider_model_timing_reconstruction_v1 (
    id INTEGER PRIMARY KEY,
    reconstruction_run_id INTEGER NOT NULL REFERENCES provider_model_timing_reconstruction_v1_runs(id),
    provider_model_observation_id INTEGER NOT NULL UNIQUE REFERENCES provider_model_observations(id),
    method_version TEXT NOT NULL,
    reconstruction_state TEXT NOT NULL CHECK(reconstruction_state IN ('COMPLETE','PARTIAL','UNAVAILABLE')),
    source_ingested_at TEXT,
    source_quote_at TEXT,
    source_greek_at TEXT,
    source_underlying_at TEXT,
    greek_age_seconds REAL,
    quote_greek_skew_seconds REAL,
    underlying_greek_skew_seconds REAL,
    evidence_json TEXT NOT NULL
);

CREATE INDEX idx_timing_reconstruction_run ON provider_model_timing_reconstruction_v1(reconstruction_run_id);
CREATE INDEX idx_timing_reconstruction_pmo ON provider_model_timing_reconstruction_v1(provider_model_observation_id);

CREATE VIEW v_provider_model_timing_effective_v1 AS
SELECT
    pmo.id AS provider_model_observation_id,
    pmo.option_quote_id,
    pmo.provider,
    CASE
      WHEN pmo.timing_diagnostic_version IS NOT NULL THEN 'NATIVE_V18'
      WHEN tr.id IS NOT NULL AND tr.reconstruction_state <> 'UNAVAILABLE' THEN 'RECONSTRUCTED_FROM_PERSISTED_RAW_V1'
      ELSE 'UNAVAILABLE'
    END AS timing_source,
    COALESCE(pmo.greek_age_seconds,tr.greek_age_seconds) AS greek_age_seconds,
    COALESCE(pmo.quote_greek_skew_seconds,tr.quote_greek_skew_seconds) AS quote_greek_skew_seconds,
    COALESCE(pmo.underlying_greek_skew_seconds,tr.underlying_greek_skew_seconds) AS underlying_greek_skew_seconds,
    tr.reconstruction_state,
    tr.method_version AS reconstruction_method_version
FROM provider_model_observations pmo
LEFT JOIN provider_model_timing_reconstruction_v1 tr
  ON tr.provider_model_observation_id=pmo.id;

CREATE VIEW v_local_surface_null_v1_discovery_membership_timing_v1 AS
SELECT
    m.*,
    eff.timing_source AS effective_timing_source,
    eff.greek_age_seconds AS effective_greek_age_seconds,
    eff.quote_greek_skew_seconds AS effective_quote_greek_skew_seconds,
    eff.underlying_greek_skew_seconds AS effective_underlying_greek_skew_seconds
FROM v_local_surface_null_v1_discovery_membership m
JOIN local_surface_residual_v2_observations v2o ON v2o.id=m.v2_observation_id
LEFT JOIN v_provider_model_timing_effective_v1 eff
  ON eff.option_quote_id=v2o.option_quote_id AND eff.provider='THETADATA';

CREATE TABLE local_surface_calibration_readiness_v1_runs (
    id INTEGER PRIMARY KEY,
    calibration_version TEXT NOT NULL,
    source_robustness_run_id INTEGER NOT NULL REFERENCES local_surface_robustness_v1_runs(id),
    source_null_run_id INTEGER NOT NULL REFERENCES local_surface_null_v1_runs(id),
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    fitted_at TEXT NOT NULL,
    observation_count INTEGER NOT NULL CHECK(observation_count>0),
    distinct_session_dates INTEGER NOT NULL CHECK(distinct_session_dates>0),
    episode_count INTEGER NOT NULL CHECK(episode_count>0),
    cross_day_contract_count INTEGER NOT NULL CHECK(cross_day_contract_count>=0),
    native_timing_count INTEGER NOT NULL CHECK(native_timing_count>=0),
    reconstructed_timing_count INTEGER NOT NULL CHECK(reconstructed_timing_count>=0),
    unavailable_timing_count INTEGER NOT NULL CHECK(unavailable_timing_count>=0),
    readiness_state TEXT NOT NULL CHECK(readiness_state IN ('INSUFFICIENT_INDEPENDENT_DATES','EXPLORATORY_STABILITY_ONLY','READY_FOR_PREREGISTRATION_REVIEW_ONLY')),
    p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0),
    fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
    UNIQUE(source_robustness_run_id,calibration_version,config_hash)
);

CREATE TABLE local_surface_calibration_readiness_v1_episodes (
    id INTEGER PRIMARY KEY,
    calibration_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_readiness_v1_runs(id),
    episode_key TEXT NOT NULL,
    session_date TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL CHECK(right IN('C','P')),
    observation_count INTEGER NOT NULL CHECK(observation_count>0),
    median_centered_residual REAL NOT NULL,
    peak_abs_centered_residual REAL NOT NULL CHECK(peak_abs_centered_residual>=0),
    persistence_ratio REAL NOT NULL CHECK(persistence_ratio BETWEEN 0 AND 1),
    sign_consistency_fraction REAL NOT NULL CHECK(sign_consistency_fraction BETWEEN 0.5 AND 1),
    median_spread_to_mid REAL,
    median_abs_greek_age_seconds REAL,
    median_abs_quote_greek_skew_seconds REAL,
    median_abs_underlying_greek_skew_seconds REAL,
    native_timing_observation_count INTEGER NOT NULL DEFAULT 0,
    reconstructed_timing_observation_count INTEGER NOT NULL DEFAULT 0,
    unavailable_timing_observation_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(calibration_run_id,episode_key)
);

CREATE TABLE local_surface_calibration_readiness_v1_cross_day_contracts (
    id INTEGER PRIMARY KEY,
    calibration_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_readiness_v1_runs(id),
    contract_key TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL CHECK(right IN('C','P')),
    session_date_count INTEGER NOT NULL CHECK(session_date_count>=2),
    total_observation_count INTEGER NOT NULL CHECK(total_observation_count>0),
    median_of_daily_medians REAL NOT NULL,
    max_abs_daily_median REAL NOT NULL CHECK(max_abs_daily_median>=0),
    daily_median_range REAL NOT NULL CHECK(daily_median_range>=0),
    same_sign_all_nonzero_days INTEGER NOT NULL CHECK(same_sign_all_nonzero_days IN(0,1)),
    sign_agreement_fraction REAL NOT NULL CHECK(sign_agreement_fraction BETWEEN 0.5 AND 1),
    UNIQUE(calibration_run_id,contract_key)
);

CREATE TABLE local_surface_calibration_readiness_v1_quality_episode_summary (
    id INTEGER PRIMARY KEY,
    calibration_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_readiness_v1_runs(id),
    metric_name TEXT NOT NULL,
    bucket_name TEXT NOT NULL,
    episode_count INTEGER NOT NULL CHECK(episode_count>0),
    median_abs_episode_median REAL NOT NULL CHECK(median_abs_episode_median>=0),
    q95_peak_abs_residual REAL NOT NULL CHECK(q95_peak_abs_residual>=0),
    median_persistence_ratio REAL NOT NULL CHECK(median_persistence_ratio BETWEEN 0 AND 1),
    UNIQUE(calibration_run_id,metric_name,bucket_name)
);

CREATE INDEX idx_calibration_episode_peak ON local_surface_calibration_readiness_v1_episodes(calibration_run_id,peak_abs_centered_residual DESC);
CREATE INDEX idx_calibration_cross_day_abs ON local_surface_calibration_readiness_v1_cross_day_contracts(calibration_run_id,max_abs_daily_median DESC);

INSERT INTO schema_version(version,applied_at)
SELECT 22,strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS(SELECT 1 FROM schema_version WHERE version=22);
