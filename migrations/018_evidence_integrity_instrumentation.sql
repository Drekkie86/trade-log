-- =====================================================================
-- Christiania — migration 018
--
-- Evidence-integrity instrumentation.
--
-- 1. Persist signed ThetaData Greek timing diagnostics without introducing
--    any freshness/admission threshold.
-- 2. Add derived views over already-immutable unmatched-provider evidence;
--    no duplicate summary table is created.
-- =====================================================================

PRAGMA foreign_keys = ON;

ALTER TABLE provider_model_observations
ADD COLUMN timing_diagnostic_version TEXT;

ALTER TABLE provider_model_observations
ADD COLUMN greek_age_seconds REAL;

ALTER TABLE provider_model_observations
ADD COLUMN quote_greek_skew_seconds REAL;

ALTER TABLE provider_model_observations
ADD COLUMN underlying_greek_skew_seconds REAL;

CREATE VIEW v_unmatched_provider_gap_by_run AS
SELECT
    research_run_id,
    provider,
    anomaly_type,
    underlying,
    COUNT(*) AS observation_count,
    COUNT(DISTINCT expiration) AS expiration_count,
    SUM(
        CASE
            WHEN strike IS NULL THEN 0
            WHEN ABS(strike - ROUND(strike)) < 0.000000001 THEN 1
            ELSE 0
        END
    ) AS integer_strike_count,
    SUM(
        CASE
            WHEN strike IS NULL THEN 0
            WHEN ABS(strike - ROUND(strike)) >= 0.000000001
             AND ABS((strike * 2.0) - ROUND(strike * 2.0)) < 0.000000001
            THEN 1
            ELSE 0
        END
    ) AS half_increment_strike_count,
    SUM(
        CASE
            WHEN strike IS NULL THEN 0
            WHEN ABS((strike * 2.0) - ROUND(strike * 2.0)) >= 0.000000001
            THEN 1
            ELSE 0
        END
    ) AS other_fractional_strike_count
FROM unmatched_provider_contract_observations
GROUP BY
    research_run_id,
    provider,
    anomaly_type,
    underlying;

CREATE VIEW v_unmatched_provider_identity_recurrence AS
SELECT
    provider,
    anomaly_type,
    underlying,
    expiration,
    strike,
    right,
    COUNT(DISTINCT research_run_id) AS distinct_run_count,
    MIN(research_run_id) AS first_research_run_id,
    MAX(research_run_id) AS last_research_run_id,
    COUNT(*) AS observation_count
FROM unmatched_provider_contract_observations
GROUP BY
    provider,
    anomaly_type,
    underlying,
    expiration,
    strike,
    right;

INSERT INTO schema_version (version, applied_at)
SELECT 18, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1 FROM schema_version WHERE version = 18
);
