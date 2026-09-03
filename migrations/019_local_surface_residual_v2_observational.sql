-- =====================================================================
-- Christiania — migration 019
--
-- LOCAL_SURFACE_RESIDUAL_V2 observational instrumentation.
-- No threshold, p-value, FDR decision, candidate creation or admission path.
-- =====================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE local_surface_residual_v2_runs (
    id INTEGER PRIMARY KEY,
    research_run_id INTEGER NOT NULL REFERENCES research_runs(id),
    model_family_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    fit_spec_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    structural_input_count INTEGER NOT NULL,
    reference_mapped_count INTEGER NOT NULL,
    evaluable_count INTEGER NOT NULL,
    surfaced_count INTEGER NOT NULL DEFAULT 0 CHECK (surfaced_count = 0),
    decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK (decision_enabled = 0),
    UNIQUE (research_run_id, model_version),
    CHECK (structural_input_count >= 0),
    CHECK (reference_mapped_count >= 0),
    CHECK (evaluable_count >= 0)
);

CREATE TABLE local_surface_residual_v2_observations (
    id INTEGER PRIMARY KEY,
    model_run_id INTEGER NOT NULL REFERENCES local_surface_residual_v2_runs(id),
    reference_contract_id INTEGER NOT NULL REFERENCES listing_reference_contracts(id),
    option_quote_id INTEGER NOT NULL REFERENCES option_quotes(id),
    underlying TEXT NOT NULL,
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL CHECK (right IN ('C','P')),
    delta REAL,
    implied_volatility REAL,
    usable_strike_count INTEGER NOT NULL CHECK (usable_strike_count >= 0),
    fit_point_count INTEGER,
    fit_dof INTEGER,
    fitted_iv REAL,
    loo_residual REAL,
    abs_loo_residual REAL,
    fit_sse REAL,
    fit_rmse REAL,
    design_condition_number REAL,
    observation_state TEXT NOT NULL CHECK (observation_state IN ('EVALUATED_OBSERVATIONAL','NOT_EVALUABLE')),
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'LOO_QUADRATIC_RESIDUAL_MEASURED',
        'DELTA_MISSING',
        'DELTA_OUT_OF_BAND',
        'IV_MISSING',
        'INSUFFICIENT_USABLE_STRIKES',
        'FIT_FAILED'
    )),
    evidence_json TEXT NOT NULL,
    UNIQUE (model_run_id, option_quote_id),
    CHECK (fit_point_count IS NULL OR fit_point_count >= 0),
    CHECK (fit_dof IS NULL OR fit_dof >= 0),
    CHECK (abs_loo_residual IS NULL OR abs_loo_residual >= 0),
    CHECK (fit_sse IS NULL OR fit_sse >= 0),
    CHECK (fit_rmse IS NULL OR fit_rmse >= 0),
    CHECK (design_condition_number IS NULL OR design_condition_number >= 0),
    CHECK (
        (observation_state = 'EVALUATED_OBSERVATIONAL'
         AND reason_code = 'LOO_QUADRATIC_RESIDUAL_MEASURED'
         AND fitted_iv IS NOT NULL
         AND loo_residual IS NOT NULL
         AND abs_loo_residual IS NOT NULL
         AND fit_dof IS NOT NULL)
        OR observation_state = 'NOT_EVALUABLE'
    )
);

CREATE INDEX idx_surface_v2_run_underlying_expiry_right
ON local_surface_residual_v2_observations(model_run_id, underlying, expiration, right);

CREATE INDEX idx_surface_v2_quote
ON local_surface_residual_v2_observations(option_quote_id);

CREATE VIEW v_local_surface_residual_v2_discovery_dataset AS
SELECT
    r.research_run_id,
    r.model_version,
    r.fit_spec_version,
    o.id AS observation_id,
    o.underlying,
    o.expiration,
    o.strike,
    o.right,
    o.delta,
    ABS(o.delta) AS abs_delta,
    o.implied_volatility,
    o.usable_strike_count,
    o.fit_point_count,
    o.fit_dof,
    o.fitted_iv,
    o.loo_residual,
    o.abs_loo_residual,
    o.fit_sse,
    o.fit_rmse,
    o.design_condition_number,
    oq.bid,
    oq.ask,
    CASE WHEN oq.bid IS NOT NULL AND oq.ask IS NOT NULL THEN (oq.bid + oq.ask) / 2.0 END AS mid,
    CASE
        WHEN oq.bid IS NOT NULL AND oq.ask IS NOT NULL AND (oq.bid + oq.ask) > 0
        THEN (oq.ask - oq.bid) / ((oq.bid + oq.ask) / 2.0)
    END AS spread_to_mid,
    ms.us_session_date,
    CAST(julianday(o.expiration) - julianday(ms.us_session_date) AS INTEGER) AS dte,
    pmo.greek_age_seconds,
    pmo.quote_greek_skew_seconds,
    pmo.underlying_greek_skew_seconds,
    o.observation_state,
    o.reason_code
FROM local_surface_residual_v2_observations AS o
JOIN local_surface_residual_v2_runs AS r ON r.id = o.model_run_id
JOIN option_quotes AS oq ON oq.id = o.option_quote_id
JOIN market_snapshots AS ms ON ms.id = oq.snapshot_id
LEFT JOIN provider_model_observations AS pmo
  ON pmo.option_quote_id = oq.id
 AND pmo.provider = 'THETADATA';

INSERT INTO schema_version (version, applied_at)
SELECT 19, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version = 19);
