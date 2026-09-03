-- =====================================================================
-- Christiania — migration 016
--
-- Structural scanner planner performance.
--
-- The deterministic scanner joins option_quotes -> market_snapshots ->
-- provider_model_observations. On the accumulated production database,
-- SQLite selected the provider-only PMO index, causing pathological
-- repeated work across a heavily skewed provider column.
--
-- These composite indexes make the run/provider and quote/provider
-- lookup shapes explicit. ANALYZE refreshes planner statistics so SQLite
-- can cost the indexes using the actual data distribution.
--
-- IF NOT EXISTS is deliberate: the live v15 database received these
-- exact indexes as an emergency additive hotfix before migration 016 was
-- formalized. Fresh databases still create them normally.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE INDEX IF NOT EXISTS idx_provider_model_option_quote_provider
ON provider_model_observations(
    option_quote_id,
    provider
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_run_provider
ON market_snapshots(
    research_run_id,
    provider
);

ANALYZE;

INSERT INTO schema_version (
    version,
    applied_at
)
SELECT
    16,
    strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        'now'
    )
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 16
);
