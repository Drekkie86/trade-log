-- =====================================================================
-- Christiania — migration 034
--
-- Storage V2C parent-delete FK support.
--
-- SQLite verifies child foreign keys while deleting parent rows. Parent
-- deletes can become effectively quadratic when the child FK column is not
-- the leading column of an index. Storage V2C deletes old rows from
-- listing_reference_contracts and option_quotes, so every child FK into those
-- parents must have a leading support index.
--
-- This migration adds only the four support indexes proven missing by the
-- complete migration-history audit. No evidence rows or semantics change.
-- =====================================================================

PRAGMA foreign_keys = ON;

CREATE INDEX idx_shadow_candidates_reference_contract
ON shadow_candidates(reference_contract_id);

CREATE INDEX idx_hypothesis_scanner_evaluations_reference_contract
ON hypothesis_scanner_evaluations(reference_contract_id);

CREATE INDEX idx_hypothesis_scanner_evaluations_option_quote
ON hypothesis_scanner_evaluations(option_quote_id);

CREATE INDEX idx_surface_v2_reference_contract
ON local_surface_residual_v2_observations(reference_contract_id);

INSERT INTO schema_version(version, applied_at)
SELECT
    34,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
WHERE NOT EXISTS (
    SELECT 1
    FROM schema_version
    WHERE version = 34
);
