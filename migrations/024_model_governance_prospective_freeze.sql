PRAGMA foreign_keys=ON;

CREATE TABLE research_model_registry_v1 (
    id INTEGER PRIMARY KEY,
    model_key TEXT NOT NULL UNIQUE,
    model_version TEXT NOT NULL,
    model_family TEXT NOT NULL,
    governance_role TEXT NOT NULL CHECK(governance_role IN(
        'FROZEN_PRIMARY_OBSERVATIONAL',
        'CHALLENGER_OBSERVATIONAL',
        'RESERVED_NOT_IMPLEMENTED'
    )),
    implementation_ref TEXT,
    evidence_use_enabled INTEGER NOT NULL DEFAULT 0 CHECK(evidence_use_enabled IN(0,1)),
    admission_enabled INTEGER NOT NULL DEFAULT 0 CHECK(admission_enabled=0),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
    notes TEXT NOT NULL
);

CREATE TABLE prospective_research_freeze_v1_runs (
    id INTEGER PRIMARY KEY,
    protocol_version TEXT NOT NULL,
    source_validity_run_id INTEGER NOT NULL REFERENCES local_surface_calibration_validity_v1_runs(id),
    frozen_at TEXT NOT NULL,
    frozen_through_session_date TEXT NOT NULL,
    prospective_start_session_date TEXT NOT NULL,
    timestamp_confidence_state TEXT NOT NULL,
    source_readiness_state TEXT NOT NULL,
    source_dte_14_20_state TEXT NOT NULL,
    protocol_state TEXT NOT NULL CHECK(protocol_state='FROZEN_PROSPECTIVE_OBSERVATION_ONLY'),
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    p_values_enabled INTEGER NOT NULL DEFAULT 0 CHECK(p_values_enabled=0),
    fdr_enabled INTEGER NOT NULL DEFAULT 0 CHECK(fdr_enabled=0),
    admission_enabled INTEGER NOT NULL DEFAULT 0 CHECK(admission_enabled=0),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
    UNIQUE(protocol_version,source_validity_run_id,config_hash)
);

CREATE TABLE prospective_research_hypotheses_v1 (
    id INTEGER PRIMARY KEY,
    freeze_run_id INTEGER NOT NULL REFERENCES prospective_research_freeze_v1_runs(id),
    hypothesis_key TEXT NOT NULL,
    description TEXT NOT NULL,
    primary_unit TEXT NOT NULL,
    primary_metric TEXT NOT NULL,
    minimum_independent_dates INTEGER NOT NULL CHECK(minimum_independent_dates>=2),
    evaluation_rule_json TEXT NOT NULL,
    hypothesis_state TEXT NOT NULL CHECK(hypothesis_state='UNTESTED_PROSPECTIVE'),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK(decision_enabled=0),
    UNIQUE(freeze_run_id,hypothesis_key)
);

CREATE TABLE prospective_model_dte_baseline_v1 (
    id INTEGER PRIMARY KEY,
    freeze_run_id INTEGER NOT NULL REFERENCES prospective_research_freeze_v1_runs(id),
    dte_bucket TEXT NOT NULL,
    quadratic_median_abs_residual REAL NOT NULL,
    local_linear_median_abs_residual REAL NOT NULL,
    quadratic_q95_abs_residual REAL NOT NULL,
    local_linear_q95_abs_residual REAL NOT NULL,
    local_linear_better_fraction REAL NOT NULL CHECK(local_linear_better_fraction BETWEEN 0 AND 1),
    raw_transfer_max_inflation REAL NOT NULL CHECK(raw_transfer_max_inflation>=0),
    episode_transfer_min_tail REAL NOT NULL CHECK(episode_transfer_min_tail BETWEEN 0 AND 1),
    episode_transfer_max_tail REAL NOT NULL CHECK(episode_transfer_max_tail BETWEEN 0 AND 1),
    review_state TEXT NOT NULL CHECK(review_state IN(
        'PROSPECTIVE_COMPARISON_REQUIRED',
        'KNOWN_INSTABILITY_PROSPECTIVE_RETEST_REQUIRED'
    )),
    UNIQUE(freeze_run_id,dte_bucket)
);

CREATE VIEW v_local_surface_v2_prospective_partition_v1 AS
WITH latest_freeze AS (
    SELECT *
    FROM prospective_research_freeze_v1_runs
    ORDER BY id DESC
    LIMIT 1
)
SELECT
    d.*,
    f.id AS freeze_run_id,
    f.frozen_through_session_date,
    f.prospective_start_session_date,
    CASE
        WHEN d.us_session_date <= f.frozen_through_session_date THEN 'PRE_FREEZE_DISCOVERY'
        ELSE 'POST_FREEZE_PROSPECTIVE'
    END AS evidence_phase
FROM v_local_surface_residual_v2_discovery_dataset AS d
CROSS JOIN latest_freeze AS f;

INSERT INTO schema_version(version,applied_at)
SELECT 24,strftime('%Y-%m-%dT%H:%M:%SZ','now')
WHERE NOT EXISTS(SELECT 1 FROM schema_version WHERE version=24);
