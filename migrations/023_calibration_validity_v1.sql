PRAGMA foreign_keys=ON;

CREATE TABLE thetadata_timestamp_semantics_v1_runs (
    id INTEGER PRIMARY KEY,
    semantics_version TEXT NOT NULL,
    validated_at TEXT NOT NULL,
    documented_market_timezone TEXT NOT NULL CHECK(documented_market_timezone='America/New_York'),
    summer_offset_hours REAL NOT NULL,
    winter_offset_hours REAL NOT NULL,
    aware_conversion_pass INTEGER NOT NULL CHECK(aware_conversion_pass IN(0,1)),
    dst_contract_pass INTEGER NOT NULL CHECK(dst_contract_pass IN(0,1)),
    documentation_contract_pass INTEGER NOT NULL CHECK(documentation_contract_pass IN(0,1)),
    live_probe_state TEXT NOT NULL CHECK(live_probe_state IN('NOT_RUN','UNAVAILABLE','PASSED','FAILED')),
    confidence_state TEXT NOT NULL CHECK(confidence_state IN('FAILED','DOCUMENTED_CONTRACT_VALIDATED_NOT_LIVE_PROBED','DOCUMENTED_AND_LIVE_VALIDATED')),
    evidence_json TEXT NOT NULL,
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0)
);

CREATE TABLE local_surface_calibration_validity_v1_runs (
    id INTEGER PRIMARY KEY,
    validity_version TEXT NOT NULL,
    source_calibration_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_readiness_v1_runs(id),
    timestamp_semantics_run_id INTEGER NOT NULL REFERENCES thetadata_timestamp_semantics_v1_runs(id),
    fitted_at TEXT NOT NULL,
    distinct_session_dates INTEGER NOT NULL CHECK(distinct_session_dates>0),
    dte_14_20_instability_state TEXT NOT NULL CHECK(dte_14_20_instability_state IN('NOT_EVALUABLE','OBSERVED_UNSTABLE','NO_INSTABILITY_OBSERVED')),
    timestamp_confidence_state TEXT NOT NULL,
    readiness_state TEXT NOT NULL CHECK(readiness_state IN('INSUFFICIENT_INDEPENDENT_DATES','MODEL_INSTABILITY_UNRESOLVED','EXPLORATORY_VALIDITY_ONLY','READY_FOR_PREREGISTRATION_REVIEW_ONLY')),
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0),
    fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
    UNIQUE(source_calibration_run_id,validity_version,config_hash)
);

CREATE TABLE local_surface_calibration_validity_v1_dte_transfer (
    id INTEGER PRIMARY KEY,
    validity_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_validity_v1_runs(id),
    train_session_date TEXT NOT NULL,
    test_session_date TEXT NOT NULL,
    dte_bucket TEXT NOT NULL,
    stratum_count INTEGER NOT NULL CHECK(stratum_count>0),
    test_observation_count INTEGER NOT NULL CHECK(test_observation_count>0),
    weighted_tail_fraction REAL NOT NULL CHECK(weighted_tail_fraction BETWEEN 0 AND 1),
    max_stratum_tail_fraction REAL NOT NULL CHECK(max_stratum_tail_fraction BETWEEN 0 AND 1),
    nominal_reference_tail REAL NOT NULL DEFAULT 0.05,
    tail_inflation_ratio REAL NOT NULL CHECK(tail_inflation_ratio>=0),
    UNIQUE(validity_run_id,train_session_date,test_session_date,dte_bucket)
);

CREATE TABLE local_surface_calibration_validity_v1_episode_transfer (
    id INTEGER PRIMARY KEY,
    validity_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_validity_v1_runs(id),
    train_session_date TEXT NOT NULL,
    test_session_date TEXT NOT NULL,
    dte_bucket TEXT NOT NULL,
    train_episode_count INTEGER NOT NULL CHECK(train_episode_count>0),
    test_episode_count INTEGER NOT NULL CHECK(test_episode_count>0),
    train_q025 REAL NOT NULL,
    train_q975 REAL NOT NULL,
    test_tail_fraction REAL NOT NULL CHECK(test_tail_fraction BETWEEN 0 AND 1),
    UNIQUE(validity_run_id,train_session_date,test_session_date,dte_bucket)
);

CREATE TABLE local_surface_calibration_validity_v1_model_comparison (
    id INTEGER PRIMARY KEY,
    validity_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_validity_v1_runs(id),
    dte_bucket TEXT NOT NULL,
    observation_count INTEGER NOT NULL CHECK(observation_count>0),
    quadratic_median_abs_residual REAL NOT NULL CHECK(quadratic_median_abs_residual>=0),
    local_linear_median_abs_residual REAL NOT NULL CHECK(local_linear_median_abs_residual>=0),
    quadratic_q95_abs_residual REAL NOT NULL CHECK(quadratic_q95_abs_residual>=0),
    local_linear_q95_abs_residual REAL NOT NULL CHECK(local_linear_q95_abs_residual>=0),
    local_linear_better_fraction REAL NOT NULL CHECK(local_linear_better_fraction BETWEEN 0 AND 1),
    UNIQUE(validity_run_id,dte_bucket)
);

CREATE TABLE local_surface_calibration_validity_v1_quality_dte (
    id INTEGER PRIMARY KEY,
    validity_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_validity_v1_runs(id),
    dte_bucket TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    bucket_name TEXT NOT NULL,
    episode_count INTEGER NOT NULL CHECK(episode_count>0),
    median_abs_episode_median REAL NOT NULL CHECK(median_abs_episode_median>=0),
    q95_peak_abs_residual REAL NOT NULL CHECK(q95_peak_abs_residual>=0),
    UNIQUE(validity_run_id,dte_bucket,metric_name,bucket_name)
);

INSERT INTO schema_version(version,applied_at)
SELECT 23,strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS(SELECT 1 FROM schema_version WHERE version=23);
